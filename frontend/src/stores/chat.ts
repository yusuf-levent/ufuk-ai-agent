/**
 * Chat state (Zustand): live agent turns per conversation. Events arrive
 * from the main process over the chat:event channel and are folded into
 * per-conversation live state; finished runs reload the persisted
 * conversation (single source of truth: the store in main).
 *
 * Optimistic bubbles: a sent message renders instantly as a
 * `PendingMessage`; main persists it at run start and reports back via
 * queueEvent 'started' with the authoritative userIndex. Once a reloaded
 * history contains the message (positional match), the bubble is dropped
 * (consumeCovered) so the persisted copy renders exactly once.
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

/**
 * An optimistically rendered user message. Dropped by consumeCovered once
 * the reloaded persisted history contains it (positional match on
 * userIndex — duplicate texts cannot confuse it).
 */
export interface PendingMessage {
  id: string;
  text: string;
  /**
   * 0-based index among the conversation's persisted user messages.
   * Authoritative value arrives with queueEvent 'started' from main;
   * null while the message is still queued.
   */
  userIndex: number | null;
  state: "queued" | "running";
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
  /** Epoch-ms when the current run started (elapsed/activity indicator). */
  startedAt: number | null;
  /** Agent step counter (progress events, one per LLM tool round). */
  stepCount: number;
  /** User message of the current run (retry + covered fallback). */
  userText: string | null;
  /** Positional index of the run's user message in persisted history. */
  userIndex: number | null;
  /** Workspace root of the run (kept across 'started' resets). */
  root: string | null;
}

export interface ChatStore {
  turns: Record<string, LiveTurn>;
  /** Optimistic user bubbles per conversation (send-time UX). */
  pending: Record<string, PendingMessage[]>;
  /**
   * Draft text restored into the composer after stop() cleared queued
   * messages (queueEvent 'cleared'); consumed by the Composer.
   */
  drafts: Record<string, string | null>;
  /** Last user message per conversation (legacy retry fallback). */
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
  /**
   * Drop optimistic bubbles whose message has landed in the (re)loaded
   * history: entry.userIndex points at the persisted copy positionally.
   */
  consumeCovered: (
    conversationId: string,
    messages: { role: string; content?: string | null }[],
  ) => void;
  /** Mark a restored composer draft as consumed. */
  clearDraft: (conversationId: string) => void;
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
  startedAt: null,
  stepCount: 0,
  userText: null,
  userIndex: null,
  root: null,
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
    pending: {},
    drafts: {},
    lastMessage: {},

    subscribe: () => {
      api.subscribe("chat:event", (payload) => {
        get().handleEvent(payload);
      });
    },

    send: async (root, conversationId, message, model) => {
      // optimistic bubble — the message is visible IMMEDIATELY; main
      // persists it at run start and confirms via queueEvent 'started'
      const bubbleId =
        globalThis.crypto?.randomUUID?.() ?? `pending_${Date.now()}`;
      set((state) => ({
        pending: {
          ...state.pending,
          [conversationId]: [
            ...(state.pending[conversationId] ?? []),
            {
              id: bubbleId,
              text: message,
              userIndex: null,
              state: "running" as const,
            },
          ],
        },
        lastMessage: { ...state.lastMessage, [conversationId]: message },
      }));
      // a fresh turn only when idle — a message sent while a run is active
      // must not wipe the streaming turn (main queues it instead)
      const running = get().turns[conversationId]?.running ?? false;
      if (!running) {
        patchTurn(conversationId, () => ({
          ...emptyTurn(),
          running: true,
          startedAt: Date.now(),
          userText: message,
          root,
        }));
      }
      try {
        await api.sendChat({ root, conversationId, message, model });
      } catch (err) {
        // the bridge rejected the send: remove the bubble again (it will
        // never be persisted) and surface the error on the turn
        set((state) => ({
          pending: {
            ...state.pending,
            [conversationId]: (state.pending[conversationId] ?? []).filter(
              (p) => p.id !== bubbleId,
            ),
          },
        }));
        patchTurn(conversationId, (t) => ({
          ...t,
          running: false,
          error: err instanceof Error ? err.message : String(err),
        }));
      }
    },

    retry: async (root, conversationId, model) => {
      const turn = get().turns[conversationId];
      const last = turn?.userText ?? get().lastMessage[conversationId];
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

    consumeCovered: (conversationId, messages) => {
      const current = get().pending[conversationId];
      if (!current || current.length === 0) return;
      const userTexts = messages
        .filter((m) => m.role === "user")
        .map((m) => m.content ?? "");
      const next = current.filter(
        (p) =>
          p.userIndex === null ||
          p.userIndex >= userTexts.length ||
          userTexts[p.userIndex] !== p.text,
      );
      if (next.length !== current.length) {
        set((state) => ({
          pending: { ...state.pending, [conversationId]: next },
        }));
      }
    },

    clearDraft: (conversationId) => {
      set((state) => ({
        drafts: { ...state.drafts, [conversationId]: null },
      }));
    },

    handleEvent: (payload) => {
      // run-queue lifecycle pushes (queue support)
      if ("queueEvent" in payload) {
        const { conversationId, queueEvent } = payload;
        if (queueEvent === "queued") {
          // the just-sent optimistic bubble flips to a dimmed queued state
          set((state) => {
            const list = [...(state.pending[conversationId] ?? [])];
            for (let i = list.length - 1; i >= 0; i--) {
              const p = list[i]!;
              if (
                p.state === "running" &&
                p.userIndex === null &&
                p.text === payload.message
              ) {
                list[i] = { ...p, state: "queued" };
                break;
              }
            }
            return { pending: { ...state.pending, [conversationId]: list } };
          });
          return;
        }
        if (queueEvent === "started") {
          // a run began for this message (first, or after queue drain):
          // flip its bubble to running with the authoritative userIndex
          // and reset the live turn for the new run
          set((state) => {
            const list = [...(state.pending[conversationId] ?? [])];
            // queue drain: the first queued bubble with this text…
            let idx = list.findIndex(
              (p) => p.state === "queued" && p.text === payload.message,
            );
            if (idx < 0) {
              // …first send: the optimistic bubble is already 'running'
              // with no authoritative index yet — FIFO match (runs start
              // in order)
              idx = list.findIndex(
                (p) =>
                  p.state === "running" &&
                  p.userIndex === null &&
                  p.text === payload.message,
              );
            }
            if (idx >= 0) {
              list[idx] = {
                ...list[idx]!,
                state: "running",
                userIndex: payload.userIndex ?? null,
              };
            }
            return { pending: { ...state.pending, [conversationId]: list } };
          });
          patchTurn(conversationId, (t) => ({
            ...emptyTurn(),
            running: true,
            startedAt: Date.now(),
            userText: payload.message ?? null,
            userIndex: payload.userIndex ?? null,
            root: t.root, // keep the root captured at send time
          }));
          return;
        }
        // 'cleared': stop() dropped queued messages — remove their bubbles
        // and hand the texts back to the composer so nothing is lost
        set((state) => {
          const list = state.pending[conversationId] ?? [];
          const queuedTexts = list
            .filter((p) => p.state === "queued")
            .map((p) => p.text);
          return {
            pending: {
              ...state.pending,
              [conversationId]: list.filter((p) => p.state !== "queued"),
            },
            drafts:
              queuedTexts.length > 0
                ? {
                    ...state.drafts,
                    [conversationId]: queuedTexts.join("\n\n"),
                  }
                : state.drafts,
          };
        });
        return;
      }

      const { conversationId, event, errorInfo } = payload;
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
        case "step":
          patchTurn(conversationId, (t) => ({
            ...t,
            running: true,
            stepCount: event.step,
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
          break;
      }
    },
  };
});
