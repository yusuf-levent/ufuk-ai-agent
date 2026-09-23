/**
 * Chat state (Zustand): live agent turns per conversation. Events arrive
 * from the main process over the chat:event channel and are folded into
 * per-conversation live state; finished runs reload the persisted
 * conversation (single source of truth: the store in main).
 */
import { create } from "zustand";
import { api } from "../ipc/client";
import type { ChatEventPayload, ChatErrorInfo } from "@shared/ipc";
import type { Usage } from "@evren/agent-core";

/** One tool step in the timeline (tool_call + matching tool_result). */
export interface ToolStep {
  id: string;
  name: string;
  /** Compact argument preview (JSON, truncated). */
  argsSummary: string;
  output: string;
  ok: boolean | null;
  durationMs: number | null;
  status: "running" | "done" | "denied";
}

/** A file touched during the run (file_changed events). */
export interface FileChange {
  path: string;
  change: "created" | "modified" | "deleted";
}

export interface LiveTurn {
  text: string;
  reasoning: string;
  steps: ToolStep[];
  fileChanges: FileChange[];
  usage: Usage | null;
  error: string | null;
  /** Structured error code for actionable UI (M8). */
  errorCode: ChatErrorInfo["code"] | null;
  /** Epoch-ms timestamp until a rate-limit retry is allowed. */
  retryUntil: number | null;
  running: boolean;
  /** Pending approval_request awaiting a renderer decision. */
  approval: { id: string; tool: string; input: unknown } | null;
}

export interface ChatStore {
  turns: Record<string, LiveTurn>;
  /** Last user message per conversation (for retry). */
  lastMessage: Record<string, string>;
  subscribe: () => void;
  send: (
    root: string,
    conversationId: string,
    message: string,
    model?: string,
  ) => Promise<void>;
  retry: (
    root: string,
    conversationId: string,
    model?: string,
  ) => Promise<void>;
  stop: (conversationId: string) => void;
  respondApproval: (
    conversationId: string,
    approvalId: string,
    approved: boolean,
    remember: boolean,
  ) => void;
  /** Clear live state (e.g. when switching conversations). */
  reset: (conversationId: string) => void;
  handleEvent: (payload: ChatEventPayload) => void;
}

const emptyTurn = (): LiveTurn => ({
  text: "",
  reasoning: "",
  steps: [],
  fileChanges: [],
  usage: null,
  error: null,
  errorCode: null,
  retryUntil: null,
  running: false,
  approval: null,
});

/** Guard against unbounded live buffers (long outputs must not freeze the UI). */
const MAX_LIVE_CHARS = 200_000;
const cap = (current: string, delta: string): string => {
  const next = current + delta;
  return next.length > MAX_LIVE_CHARS
    ? next.slice(next.length - MAX_LIVE_CHARS)
    : next;
};

function argsSummary(raw: string): string {
  let preview = raw;
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    preview = Object.entries(parsed)
      .map(([k, v]) => {
        const value = typeof v === "string" ? v : JSON.stringify(v);
        const short =
          value && value.length > 120 ? `${value.slice(0, 120)}…` : value;
        return `${k}: ${short ?? ""}`;
      })
      .join(", ");
  } catch {
    // raw JSON parse failed: show the raw text truncated
    preview = preview.slice(0, 160);
  }
  return preview;
}

export const useChatStore = create<ChatStore>((set, get) => {
  const patchTurn = (
    conversationId: string,
    patch: (turn: LiveTurn) => LiveTurn,
  ): void => {
    set((state) => ({
      turns: {
        ...state.turns,
        [conversationId]: patch(state.turns[conversationId] ?? emptyTurn()),
      },
    }));
  };

  return {
    turns: {},
    lastMessage: {},

    subscribe: () => {
      api.subscribe("chat:event", (payload) => {
        get().handleEvent(payload);
      });
    },

    send: async (root, conversationId, message, model) => {
      patchTurn(conversationId, () => ({
        ...emptyTurn(),
        running: true,
      }));
      set((state) => ({
        lastMessage: { ...state.lastMessage, [conversationId]: message },
      }));
      try {
        await api.sendChat({ root, conversationId, message, model });
      } catch (err) {
        patchTurn(conversationId, (t) => ({
          ...t,
          running: false,
          error: err instanceof Error ? err.message : String(err),
        }));
      }
    },

    retry: async (root, conversationId, model) => {
      const last = get().lastMessage[conversationId];
      if (!last) return;
      await get().send(root, conversationId, last, model);
    },

    stop: (conversationId) => {
      void api.stopChat(conversationId).catch(() => {
        // no active run — nothing to do
      });
    },

    respondApproval: (conversationId, approvalId, approved, remember) => {
      void api
        .respondApproval({ conversationId, approvalId, approved, remember })
        .catch(() => {
          // run already ended
        });
      patchTurn(conversationId, (t) => ({ ...t, approval: null }));
    },

    reset: (conversationId) => {
      set((state) => {
        const turns = { ...state.turns };
        delete turns[conversationId];
        return { turns };
      });
    },

    handleEvent: ({ conversationId, event, errorInfo }) => {
      switch (event.type) {
        case "message_delta":
          patchTurn(conversationId, (t) => ({
            ...t,
            running: true,
            text: cap(t.text, event.text),
          }));
          break;
        case "reasoning_delta":
          patchTurn(conversationId, (t) => ({
            ...t,
            running: true,
            reasoning: cap(t.reasoning, event.text),
          }));
          break;
        case "tool_call":
          patchTurn(conversationId, (t) => ({
            ...t,
            running: true,
            steps: [
              ...t.steps,
              {
                id: event.id,
                name: event.name,
                argsSummary: argsSummary(event.arguments),
                output: "",
                ok: null,
                durationMs: null,
                status: "running",
              },
            ],
          }));
          break;
        case "tool_result":
          patchTurn(conversationId, (t) => ({
            ...t,
            steps: t.steps.map((s) =>
              s.id === event.id
                ? {
                    ...s,
                    output:
                      event.output.length > 4_000
                        ? `${event.output.slice(0, 4_000)}…`
                        : event.output,
                    ok: event.ok,
                    durationMs: event.durationMs,
                    // a denied action stays marked denied even though the
                    // loop reports it as a failed tool_result
                    status:
                      s.status === "denied" ||
                      event.output.startsWith("Permission denied")
                        ? "denied"
                        : "done",
                  }
                : s,
            ),
          }));
          break;
        case "approval_request":
          patchTurn(conversationId, (t) => ({
            ...t,
            approval: {
              id: event.id,
              tool: event.tool,
              input: event.input,
            },
          }));
          break;
        case "approval_resolved":
          patchTurn(conversationId, (t) => ({
            ...t,
            approval: null,
            // denied actions stay visible in the timeline
            steps: event.approved
              ? t.steps
              : t.steps.map((s, i) =>
                  i === t.steps.length - 1 && s.status === "running"
                    ? { ...s, status: "denied" }
                    : s,
                ),
          }));
          break;
        case "file_changed":
          patchTurn(conversationId, (t) => ({
            ...t,
            fileChanges: [
              ...t.fileChanges.filter((f) => f.path !== event.path),
              { path: event.path, change: event.change },
            ],
          }));
          break;
        case "usage":
          patchTurn(conversationId, (t) => ({ ...t, usage: event.usage }));
          break;
        case "error":
          patchTurn(conversationId, (t) => ({
            ...t,
            error: event.message,
            errorCode: errorInfo?.code ?? null,
            retryUntil:
              errorInfo?.retryAfterMs !== undefined
                ? Date.now() + errorInfo.retryAfterMs
                : null,
            ...(event.fatal ? { running: false } : {}),
          }));
          break;
        case "done":
          patchTurn(conversationId, (t) => ({
            ...t,
            running: false,
            usage: event.usage,
          }));
          break;
        default:
          // 'step' events: progress counter, no separate UI yet
          break;
      }
    },
  };
});
