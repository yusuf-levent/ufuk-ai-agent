/**
 * Agent runtime host (main process). Owns the live agent runs:
 * builds the provider/tools/permissions exactly like the CLI, streams
 * AgentEvents to the renderer over the chat:event channel, persists
 * finished turns (messages + tool calls + audit) to the conversation store,
 * and bridges approval decisions back from the renderer.
 *
 * One run per conversation at a time; stop() aborts and persists partial
 * work (same semantics as the CLI's SIGINT handling).
 */
import { existsSync, readFileSync } from "node:fs";
import * as path from "node:path";
import {
  Agent,
  buildSystemPrompt,
  ContextManager,
  EvrenGatewayProvider,
  mapGatewayError,
  ProviderError,
  ToolRegistry,
  type AgentEvent,
  type ApprovalHandler,
  type PermissionDecision,
  type PermissionRequest,
  type PermissionRule,
  type ToolCallRecord,
} from "@evren/agent-core";
import {
  createFileTools,
  createGitTools,
  createRunCommandTool,
  PermissionEngine,
  ShadowCheckpointStore,
  deriveRememberRule,
} from "@evren/local-runner";
import type { BrowserWindow } from "electron";
import { EVENT_CHANNELS } from "@shared/channels";
import type { GatewaySession } from "./gateway";
import type { ProjectManager } from "./projects";
import type { SettingsStore } from "./settings";

export interface AgentRuntimeDeps {
  win: () => BrowserWindow | null;
  settings: SettingsStore;
  session: () => GatewaySession;
  projects: ProjectManager;
}

interface PendingApproval {
  id: string;
  request: PermissionRequest;
  resolve: (decision: PermissionDecision) => void;
}

interface Run {
  conversationId: string;
  root: string;
  controller: AbortController;
  /** id of the approval_request currently awaiting a renderer decision */
  expectedApprovalId: string | null;
  pending: PendingApproval | null;
}

function safeParse(raw: string): unknown {
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

export class AgentRuntime {
  private readonly runs = new Map<string, Run>();

  constructor(private readonly deps: AgentRuntimeDeps) {}

  isRunning(conversationId: string): boolean {
    return this.runs.has(conversationId);
  }

  /**
   * Start a run. Errors are reported through chat:error events (and the
   * returned promise never rejects for run-level failures) so the renderer
   * can always rely on the event stream.
   */
  async send(
    root: string,
    conversationId: string,
    message: string,
    model?: string,
  ): Promise<void> {
    if (this.runs.has(conversationId)) {
      this.emit(conversationId, {
        type: "error",
        fatal: true,
        message: "This conversation is already running.",
      });
      return;
    }
    const run: Run = {
      conversationId,
      root,
      controller: new AbortController(),
      expectedApprovalId: null,
      pending: null,
    };
    this.runs.set(conversationId, run);
    try {
      await this.runTurn(run, conversationId, message, model);
    } finally {
      // deny any approval that never got answered
      run.pending?.resolve({ effect: "deny", note: "run ended" });
      this.runs.delete(conversationId);
    }
  }

  stop(conversationId: string): boolean {
    const run = this.runs.get(conversationId);
    if (!run) return false;
    run.controller.abort();
    return true;
  }

  /** Renderer answered an approval_request. */
  respondApproval(
    conversationId: string,
    approvalId: string,
    approved: boolean,
    remember: boolean,
  ): boolean {
    const run = this.runs.get(conversationId);
    if (!run || !run.pending || run.pending.id !== approvalId) return false;
    const pending = run.pending;
    run.pending = null;
    if (approved && remember) {
      // "always allow": same rule derivation as the CLI (npm test prefix
      // for run_command, whole tool otherwise); the engine persists it
      const rule = deriveRememberRule(pending.request);
      pending.resolve({ effect: "allow", remember: rule });
      return true;
    }
    pending.resolve(
      approved
        ? { effect: "allow" }
        : { effect: "deny", note: "denied by user" },
    );
    return true;
  }

  /**
   * Preview of the "always allow" rule for the pending approval (shown in
   * the modal before the user decides). Returns null when there is no
   * matching pending approval.
   */
  approvalPreview(
    conversationId: string,
    approvalId: string,
  ): { tool: string; pattern?: string } | null {
    const run = this.runs.get(conversationId);
    if (!run || !run.pending || run.pending.id !== approvalId) return null;
    const rule = deriveRememberRule(run.pending.request);
    return { tool: rule.tool, pattern: rule.pattern };
  }

  private emit(conversationId: string, event: AgentEvent): void {
    const win = this.deps.win();
    if (win && !win.isDestroyed()) {
      win.webContents.send(EVENT_CHANNELS.chatEvent, { conversationId, event });
    }
  }

  private async runTurn(
    run: Run,
    conversationId: string,
    message: string,
    model?: string,
  ): Promise<void> {
    const { projects, settings, session } = this.deps;
    const workspace = projects.requireKnownRoot(run.root);
    const opened = await projects.store(run.root);
    const loaded = await opened.store.loadConversation(conversationId);
    if (!loaded) {
      this.emit(conversationId, {
        type: "error",
        fatal: true,
        message: "Conversation not found.",
      });
      return;
    }

    const tier = model ?? loaded.summary.model ?? settings.load().defaultTier;
    const gw = session();
    const provider = new EvrenGatewayProvider({
      auth: gw.auth,
      baseURL: gw.baseURL,
      model: tier,
    });

    const checkpoints = new ShadowCheckpointStore(
      workspace,
      path.join(opened.dbDir, "checkpoints"),
    );
    const registry = new ToolRegistry();
    for (const tool of createFileTools(workspace, { checkpoints })) {
      registry.register(tool);
    }
    registry.register(createRunCommandTool(workspace));
    for (const tool of createGitTools(workspace)) {
      registry.register(tool);
    }

    // workspace instructions: <root>/AGENT.md if present
    const agentMd = path.join(workspace.root, "AGENT.md");
    const workspaceInstructions = existsSync(agentMd)
      ? readFileSync(agentMd, "utf8")
      : null;
    const systemPrompt = buildSystemPrompt({
      workspaceRoot: workspace.root,
      workspaceInstructions,
    });

    // remembered rules live in the conversation store (per project)
    const rememberedStore = {
      load: async (): Promise<PermissionRule[]> =>
        opened.store.listRememberedPermissions(workspace.root),
      save: async (rule: PermissionRule): Promise<void> => {
        await opened.store.rememberPermission(workspace.root, rule);
      },
    };

    const handler: ApprovalHandler = async (req) => {
      // the loop emits approval_request (with id) right before calling
      // check(), so the expected id is already registered on the run
      return await new Promise<PermissionDecision>((resolve) => {
        run.pending = {
          id: run.expectedApprovalId ?? "unknown",
          request: req,
          resolve,
        };
      });
    };

    // per-project permission mode: 'auto-edits' allows file edits inside
    // the workspace (deny floors still apply; commands still ask);
    // there is NO allow-everything mode
    const mode = projects.effectivePermissionMode(
      run.root,
      settings.load().permissionMode,
    );
    const rules =
      mode === "auto-edits"
        ? [
            { tool: "write_file", effect: "allow" as const },
            { tool: "edit_file", effect: "allow" as const },
          ]
        : [];

    const permissionEngine = new PermissionEngine(
      { rules },
      { workspace, handler, rememberedStore },
    );

    const history = loaded.messages.filter((m) => m.role !== "system");
    let persisted = loaded.messages.length;
    const agent = new Agent({
      provider,
      registry,
      systemPrompt,
      permissions: permissionEngine,
      contextManager: new ContextManager(),
      maxSteps: 30,
      history,
    });

    const toolCallArgs = new Map<string, unknown>();
    const toolRecords: ToolCallRecord[] = [];
    try {
      for await (const ev of agent.run(message, run.controller.signal)) {
        if (ev.type === "approval_request") {
          run.expectedApprovalId = ev.id;
        }
        this.emit(conversationId, ev);
        if (ev.type === "tool_call") {
          toolCallArgs.set(ev.id, safeParse(ev.arguments));
        } else if (ev.type === "tool_result") {
          toolRecords.push({
            callId: ev.id,
            tool: ev.name,
            argsJson: JSON.stringify(toolCallArgs.get(ev.id) ?? null),
            ok: ev.ok,
            output: ev.output,
            durationMs: ev.durationMs,
          });
        }
      }
      // persist the finished turn (also on cancel — same as the CLI)
      const fresh = agent.messagesSince(persisted + 1); // +1: system prompt
      if (fresh.length > 0) {
        await opened.store.appendMessages(conversationId, fresh);
        persisted += fresh.length;
      }
      for (const record of toolRecords) {
        await opened.store.appendToolCall(conversationId, record);
        await opened.store.appendAudit(
          workspace.root,
          record.tool,
          safeParse(record.argsJson),
          record.ok,
        );
      }
    } catch (err) {
      // map gateway transport errors to the friendly messages the CLI
      // shows; ReauthRequiredError already carries a friendly message
      const mapped =
        err instanceof ProviderError ? mapGatewayError(err, tier) : err;
      this.emit(conversationId, {
        type: "error",
        fatal: true,
        message: mapped instanceof Error ? mapped.message : String(err),
      });
    }
  }
}
