/**
 * IPC handler registration. Every renderer->main call:
 *   1. is checked against the trusted-sender policy (our origin only),
 *   2. has its payload zod-validated,
 *   3. returns an IpcResult envelope (never a bare throw across the bridge).
 */
import { ipcMain, shell, dialog, BrowserWindow } from "electron";
import { z } from "zod";
import {
  ApprovalPreviewRequestSchema,
  ApprovalRespondRequestSchema,
  ChatSendRequestSchema,
  ChatStopRequestSchema,
  CheckpointRevertRequestSchema,
  ConversationIdRequestSchema,
  ConversationRenameRequestSchema,
  DiffRequestSchema,
  LoginRequestSchema,
  OpenExternalRequestSchema,
  ProjectPathRequestSchema,
  ProjectRootRequestSchema,
  RegisterRequestSchema,
  SetPermissionModeRequestSchema,
  SettingsPatchSchema,
  type IpcResult,
  type Settings,
} from "@shared/ipc";
import { INVOKE_CHANNELS } from "@shared/channels";
import { isTrustedSender, parseExternalUrl } from "./security";
import type { SettingsStore } from "./settings";
import {
  authErrorCode,
  buildGatewaySession,
  fetchPrivacyInfo,
  fetchSessionSnapshot,
  fetchTierCatalog,
  fetchUsage,
  mapClientError,
  type GatewaySession,
} from "./gateway";
import { ProjectManager, ProjectValidationError } from "./projects";
import type { AgentRuntime } from "./agent-runtime";
import { diffLines } from "./diff";
import { readFile } from "node:fs/promises";

export interface IpcDeps {
  win: () => BrowserWindow | null;
  settings: SettingsStore;
  /** Electron user-data dir (%APPDATA%/ufuk). */
  userDataDir: string;
  /** safeStorage (injected for tests). */
  safe: {
    isEncryptionAvailable(): boolean;
    encryptString(plainText: string): Buffer;
    decryptString(encrypted: Buffer): string;
  };
  /** Rebuilt whenever settings change; also returns the active session. */
  session: () => GatewaySession;
  setSession: (s: GatewaySession) => void;
  versions: () => { version: string; electron: string; node: string };
  /** Project manager (recent projects + conversation stores). */
  projects: ProjectManager;
  /** Agent runtime (chat runs + approvals). */
  runtime: AgentRuntime;
}

type Handler = (
  event: Electron.IpcMainInvokeEvent,
  payload: unknown,
) => Promise<IpcResult<unknown>>;

function register(
  channel: string,
  schema: z.ZodTypeAny,
  handler: Handler,
): void {
  ipcMain.handle(channel, async (event, payload) => {
    if (!isTrustedSender(event.sender)) {
      return {
        ok: false,
        error: { message: "untrusted sender", code: "forbidden" },
      };
    }
    if (payload !== undefined) {
      const parsed = schema.safeParse(payload);
      if (!parsed.success) {
        return {
          ok: false,
          error: {
            message: `invalid request for ${channel}`,
            code: "invalid_request",
          },
        };
      }
    }
    try {
      return await handler(event, payload);
    } catch (err) {
      if (err instanceof ProjectValidationError) {
        return { ok: false, error: { message: err.message, code: err.code } };
      }
      const mapped = authErrorCode(err);
      return { ok: false, error: mapped };
    }
  });
}

export function registerIpcHandlers(deps: IpcDeps): void {
  register(INVOKE_CHANNELS.appVersion, z.void(), async () => ({
    ok: true,
    value: deps.versions(),
  }));

  register(INVOKE_CHANNELS.settingsGet, z.void(), async () => ({
    ok: true,
    value: deps.settings.load(),
  }));

  register(
    INVOKE_CHANNELS.settingsSet,
    SettingsPatchSchema,
    async (_e, payload) => {
      const settings: Settings = deps.settings.patch(
        SettingsPatchSchema.parse(payload),
      );
      // backend URL changes rebuild the gateway session (new token namespace)
      deps.setSession(
        buildGatewaySession(settings, deps.userDataDir, deps.safe),
      );
      return { ok: true, value: settings };
    },
  );

  register(
    INVOKE_CHANNELS.authLogin,
    LoginRequestSchema,
    async (_e, payload) => {
      const { email, password } = LoginRequestSchema.parse(payload);
      await deps.session().auth.login(email, password);
      return { ok: true, value: null };
    },
  );

  register(
    INVOKE_CHANNELS.authRegister,
    RegisterRequestSchema,
    async (_e, payload) => {
      const { email, password, displayName } =
        RegisterRequestSchema.parse(payload);
      await deps.session().auth.register(email, password, displayName);
      return { ok: true, value: null };
    },
  );

  register(INVOKE_CHANNELS.authLogout, z.void(), async () => {
    await deps.session().auth.logout();
    return { ok: true, value: null };
  });

  register(INVOKE_CHANNELS.authSession, z.void(), async () => {
    const snapshot = await fetchSessionSnapshot(deps.session());
    return { ok: true, value: snapshot };
  });

  register(INVOKE_CHANNELS.privacyInfo, z.void(), async () => {
    const info = await fetchPrivacyInfo(deps.session());
    return { ok: true, value: info };
  });

  register(
    INVOKE_CHANNELS.openExternal,
    OpenExternalRequestSchema,
    async (_e, payload) => {
      const { url } = OpenExternalRequestSchema.parse(payload);
      const parsed = parseExternalUrl(url);
      if (!parsed) {
        return {
          ok: false,
          error: {
            message: "only http(s) links can be opened",
            code: "invalid_request",
          },
        };
      }
      const win = deps.win();
      if (win) {
        const choice = await dialog.showMessageBox(win, {
          type: "question",
          buttons: ["Open in browser", "Cancel"],
          defaultId: 1,
          cancelId: 1,
          title: "Open link",
          message: "Open this link in your system browser?",
          detail: url,
          noLink: true,
        });
        if (choice.response !== 0) {
          return { ok: true, value: false };
        }
      }
      await shell.openExternal(parsed.toString());
      return { ok: true, value: true };
    },
  );

  // -----------------------------------------------------------------------
  // projects & conversations (Milestone 5)
  // -----------------------------------------------------------------------

  register(INVOKE_CHANNELS.projectsList, z.void(), async () => ({
    ok: true,
    value: deps.projects.list(),
  }));

  register(
    INVOKE_CHANNELS.projectsAdd,
    ProjectPathRequestSchema,
    async (_e, payload) => {
      const { path } = ProjectPathRequestSchema.parse(payload);
      // throws ProjectValidationError -> coded envelope
      return { ok: true, value: deps.projects.add(path) };
    },
  );

  register(
    INVOKE_CHANNELS.projectsRemove,
    ProjectPathRequestSchema,
    async (_e, payload) => {
      const { path } = ProjectPathRequestSchema.parse(payload);
      deps.projects.remove(path);
      return { ok: true, value: null };
    },
  );

  register(INVOKE_CHANNELS.projectsPickFolder, z.void(), async () => {
    const win = deps.win();
    const result = win
      ? await dialog.showOpenDialog(win, {
          title: "Add project folder",
          properties: ["openDirectory"],
        })
      : { canceled: true, filePaths: [] as string[] };
    if (result.canceled || result.filePaths.length === 0) {
      return { ok: true, value: null };
    }
    return { ok: true, value: result.filePaths[0] ?? null };
  });

  register(
    INVOKE_CHANNELS.conversationsList,
    ProjectRootRequestSchema,
    async (_e, payload) => {
      const { root } = ProjectRootRequestSchema.parse(payload);
      deps.projects.touch(root);
      return { ok: true, value: await deps.projects.listConversations(root) };
    },
  );

  register(
    INVOKE_CHANNELS.conversationsCreate,
    ProjectRootRequestSchema,
    async (_e, payload) => {
      const { root } = ProjectRootRequestSchema.parse(payload);
      const workspace = deps.projects.requireKnownRoot(root);
      const opened = await deps.projects.store(root);
      const model = deps.settings.load().defaultTier;
      const id = await opened.store.createConversation(workspace.root, model);
      const created = await opened.store.loadConversation(id);
      if (!created) {
        return {
          ok: false,
          error: { message: "conversation vanished", code: "internal" },
        };
      }
      return { ok: true, value: created.summary };
    },
  );

  register(
    INVOKE_CHANNELS.conversationsLoad,
    ConversationIdRequestSchema,
    async (_e, payload) => {
      const { root, id } = ConversationIdRequestSchema.parse(payload);
      deps.projects.requireKnownRoot(root);
      const opened = await deps.projects.store(root);
      return { ok: true, value: await opened.store.loadConversation(id) };
    },
  );

  register(
    INVOKE_CHANNELS.conversationsRename,
    ConversationRenameRequestSchema,
    async (_e, payload) => {
      const { root, id, title } =
        ConversationRenameRequestSchema.parse(payload);
      deps.projects.requireKnownRoot(root);
      const opened = await deps.projects.store(root);
      return {
        ok: true,
        value: await opened.store.renameConversation(id, title),
      };
    },
  );

  register(
    INVOKE_CHANNELS.conversationsDelete,
    ConversationIdRequestSchema,
    async (_e, payload) => {
      const { root, id } = ConversationIdRequestSchema.parse(payload);
      deps.projects.requireKnownRoot(root);
      const opened = await deps.projects.store(root);
      return {
        ok: true,
        value: await opened.store.deleteConversation(id),
      };
    },
  );

  // -----------------------------------------------------------------------
  // chat runs & approvals (Milestone 6)
  // -----------------------------------------------------------------------

  register(
    INVOKE_CHANNELS.chatSend,
    ChatSendRequestSchema,
    async (_e, payload) => {
      const { root, conversationId, message, model } =
        ChatSendRequestSchema.parse(payload);
      // fire-and-forget: the run streams its results via chat:event;
      // the promise only rejects on programming errors (caught above)
      void deps.runtime.send(root, conversationId, message, model);
      return { ok: true, value: null };
    },
  );

  register(
    INVOKE_CHANNELS.chatStop,
    ChatStopRequestSchema,
    async (_e, payload) => {
      const { conversationId } = ChatStopRequestSchema.parse(payload);
      return { ok: true, value: deps.runtime.stop(conversationId) };
    },
  );

  register(
    INVOKE_CHANNELS.approvalsRespond,
    ApprovalRespondRequestSchema,
    async (_e, payload) => {
      const { conversationId, approvalId, approved, remember } =
        ApprovalRespondRequestSchema.parse(payload);
      return {
        ok: true,
        value: deps.runtime.respondApproval(
          conversationId,
          approvalId,
          approved,
          remember,
        ),
      };
    },
  );

  register(
    INVOKE_CHANNELS.approvalsPreview,
    ApprovalPreviewRequestSchema,
    async (_e, payload) => {
      const { conversationId, approvalId } =
        ApprovalPreviewRequestSchema.parse(payload);
      return {
        ok: true,
        value: deps.runtime.approvalPreview(conversationId, approvalId),
      };
    },
  );

  // -----------------------------------------------------------------------
  // permission modes, checkpoints, diffs, changed files (Milestone 7)
  // -----------------------------------------------------------------------

  register(
    INVOKE_CHANNELS.projectsSetPermissionMode,
    SetPermissionModeRequestSchema,
    async (_e, payload) => {
      const { root, mode } = SetPermissionModeRequestSchema.parse(payload);
      const info = deps.projects.setPermissionMode(root, mode);
      if (!info) {
        return {
          ok: false,
          error: { message: "Unknown project.", code: "not_a_directory" },
        };
      }
      return { ok: true, value: info };
    },
  );

  register(
    INVOKE_CHANNELS.checkpointsList,
    ProjectRootRequestSchema,
    async (_e, payload) => {
      const { root } = ProjectRootRequestSchema.parse(payload);
      const store = await deps.projects.checkpoints(root);
      return { ok: true, value: await store.list(50) };
    },
  );

  register(
    INVOKE_CHANNELS.checkpointsUndo,
    ProjectRootRequestSchema,
    async (_e, payload) => {
      const { root } = ProjectRootRequestSchema.parse(payload);
      const store = await deps.projects.checkpoints(root);
      return { ok: true, value: await store.undoLast() };
    },
  );

  register(
    INVOKE_CHANNELS.checkpointsRevert,
    CheckpointRevertRequestSchema,
    async (_e, payload) => {
      const { root, id } = CheckpointRevertRequestSchema.parse(payload);
      const store = await deps.projects.checkpoints(root);
      return { ok: true, value: await store.revertTo(id) };
    },
  );

  register(
    INVOKE_CHANNELS.checkpointsDiff,
    DiffRequestSchema,
    async (_e, payload) => {
      const {
        root,
        path: file,
        checkpointId,
      } = DiffRequestSchema.parse(payload);
      const workspace = deps.projects.requireKnownRoot(root);
      const store = await deps.projects.checkpoints(root);

      // resolve + confine the requested path
      let abs: string;
      try {
        abs = workspace.resolve(file);
      } catch (err) {
        return {
          ok: false,
          error: {
            message: err instanceof Error ? err.message : "unsafe path",
            code: "invalid_request",
          },
        };
      }

      // find the newest checkpoint that snapshotted this file (or use the
      // explicitly requested one)
      let cpId = checkpointId;
      if (!cpId) {
        const list = await store.list(50);
        const found = list.find((c) =>
          c.files.some((f) => workspaceRelativeEq(workspace, f.path, file)),
        );
        cpId = found?.id;
      }
      let oldContent: string | null = null;
      if (cpId) {
        oldContent = await store.readFile(cpId, file);
      }
      let newContent = "";
      try {
        newContent = await readFile(abs, "utf8");
      } catch {
        newContent = ""; // file deleted since
      }
      const result = diffLines(oldContent ?? "", newContent);
      return {
        ok: true,
        value: {
          path: workspace.relative(abs),
          snapshotMissing: oldContent === null,
          identical: result.identical,
          oldLines: result.oldLines,
          newLines: result.newLines,
          hunks: result.hunks,
        },
      };
    },
  );

  register(
    INVOKE_CHANNELS.conversationsChangedFiles,
    ConversationIdRequestSchema,
    async (_e, payload) => {
      const { root, id } = ConversationIdRequestSchema.parse(payload);
      const workspace = deps.projects.requireKnownRoot(root);
      const opened = await deps.projects.store(root);
      const records = await opened.store.listToolCalls(id);
      // unique paths from edit tools, newest first
      const out: {
        path: string;
        tool: string;
        ok: boolean;
        at: string;
      }[] = [];
      const seen = new Set<string>();
      for (const r of [...records].reverse()) {
        if (r.tool !== "write_file" && r.tool !== "edit_file") continue;
        let rel: string | undefined;
        try {
          const parsed = JSON.parse(r.argsJson) as { path?: unknown };
          if (typeof parsed["path"] === "string") {
            rel = workspace.relative(workspace.resolve(parsed["path"]));
          }
        } catch {
          continue;
        }
        if (!rel || seen.has(rel)) continue;
        seen.add(rel);
        out.push({ path: rel, tool: r.tool, ok: r.ok, at: "" });
      }
      return { ok: true, value: out };
    },
  );

  // -----------------------------------------------------------------------
  // tiers & usage (Milestone 8)
  // -----------------------------------------------------------------------

  register(INVOKE_CHANNELS.modelsList, z.void(), async () => {
    try {
      return { ok: true, value: await fetchTierCatalog(deps.session()) };
    } catch (err) {
      return { ok: false, error: mapClientError(err) };
    }
  });

  register(INVOKE_CHANNELS.usageGet, z.void(), async () => {
    try {
      return { ok: true, value: await fetchUsage(deps.session()) };
    } catch (err) {
      return { ok: false, error: mapClientError(err) };
    }
  });
}

function workspaceRelativeEq(
  workspace: { relative(p: string): string },
  checkpointPath: string,
  file: string,
): boolean {
  try {
    return workspace.relative(checkpointPath) === workspace.relative(file);
  } catch {
    return false;
  }
}
