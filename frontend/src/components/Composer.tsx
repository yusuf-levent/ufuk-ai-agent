/**
 * Composer (bottom bar): tier selector from the live catalog (display name
 * + real upstream provider/model in a details popover; locked tiers with
 * an explanation) + message input. Enter sends, Shift+Enter inserts a
 * newline (configurable: enterToSend swaps Enter for Ctrl+Enter); sending
 * while a run is active QUEUES the message (never blocks the input); Stop
 * aborts the run and returns queued texts to the input; Retry re-sends
 * the failed message. Chat-mode conversations (root = CHAT_ROOT_ID) get
 * chat-flavored copy.
 */
import { useEffect, useState } from "react";
import { CHAT_ROOT_ID } from "@shared/ipc";
import { useAppStore } from "../stores/app";
import { useChatStore } from "../stores/chat";
import { useModelsStore } from "../stores/models";

export function Composer({
  root,
  conversationId,
  onTurnStarted,
}: {
  root: string;
  conversationId: string;
  /** Called when a run starts (lets the parent scroll/track activity). */
  onTurnStarted: () => void;
}) {
  const { settings, patchSettings } = useAppStore();
  const catalog = useModelsStore((s) => s.catalog);
  const turn = useChatStore((s) => s.turns[conversationId]);
  const running = turn?.running ?? false;
  const hasError = turn?.error ?? null;
  const lastMessage = useChatStore(
    (s) => s.lastMessage[conversationId] ?? null,
  );
  const queuedCount = useChatStore(
    (s) =>
      (s.pending[conversationId] ?? []).filter((p) => p.state === "queued")
        .length,
  );
  /** Queued texts returned by stop() — restored into the input once. */
  const draft = useChatStore((s) => s.drafts[conversationId] ?? null);
  const clearDraft = useChatStore((s) => s.clearDraft);
  const send = useChatStore((s) => s.send);
  const stop = useChatStore((s) => s.stop);
  const retry = useChatStore((s) => s.retry);
  const [input, setInput] = useState("");
  const [tierDetails, setTierDetails] = useState<string | null>(null);

  useEffect(() => {
    if (draft) {
      setInput(draft);
      clearDraft(conversationId);
    }
  }, [draft, conversationId, clearDraft]);

  /** Enter sends (default) or Ctrl+Enter sends — a settings toggle. */
  const enterToSend = settings?.enterToSend ?? true;

  const submit = (): void => {
    const message = input.trim();
    if (!message) return;
    // no running guard: a message sent mid-run is queued in main and runs
    // right after the current reply — the user can keep typing meanwhile
    setInput("");
    onTurnStarted();
    void send(root, conversationId, message, settings?.defaultTier);
  };

  const allowed = catalog?.allowed ?? [];
  const locked = catalog?.locked ?? [];
  const selected = allowed.find((t) => t.id === settings?.defaultTier);
  const fallbackTiers = ["fast", "balanced", "strong"];

  return (
    <footer className="shrink-0 border-t border-neutral-800 p-3">
      <div className="mx-auto max-w-3xl">
        <div className="relative mb-2 flex items-center gap-3 text-xs text-neutral-500">
          <label className="flex items-center gap-1">
            model
            <select
              value={settings?.defaultTier ?? "fast"}
              onChange={(e) =>
                void patchSettings({ defaultTier: e.target.value })
              }
              className="rounded border border-neutral-700 bg-neutral-900 px-1.5 py-0.5 text-xs text-neutral-200"
            >
              {(allowed.length > 0
                ? allowed.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.displayName ?? t.id}
                    </option>
                  ))
                : fallbackTiers.map((t) => <option key={t}>{t}</option>)
              ).concat(
                // keep an unknown/current selection visible
                allowed.some((t) => t.id === settings?.defaultTier) ||
                  fallbackTiers.includes(settings?.defaultTier ?? "")
                  ? []
                  : [
                      <option key="__current" value={settings?.defaultTier}>
                        {settings?.defaultTier}
                      </option>,
                    ],
              )}
              {locked.map((t) => (
                <option key={t.id} value={t.id} disabled title={t.reason}>
                  🔒 {t.id}
                </option>
              ))}
            </select>
          </label>
          {selected && (
            <button
              type="button"
              onClick={() =>
                setTierDetails(tierDetails === selected.id ? null : selected.id)
              }
              className="text-[10px] text-neutral-500 underline hover:text-sky-400"
            >
              details
            </button>
          )}
          <span className="ml-auto text-[10px]">
            {enterToSend
              ? "Enter to send · Shift+Enter for a new line"
              : "Ctrl+Enter to send · Enter for a new line"}
          </span>
          {tierDetails && selected && (
            <div className="absolute bottom-full left-0 z-40 mb-1 w-64 rounded-lg border border-neutral-700 bg-neutral-900 p-2 text-[11px] shadow-xl">
              <div className="font-medium text-neutral-200">
                {selected.displayName ?? selected.id}
              </div>
              <dl className="mt-1 space-y-0.5 text-neutral-400">
                <div className="flex justify-between gap-2">
                  <dt>upstream</dt>
                  <dd className="truncate font-mono">
                    {selected.upstreamProvider ?? "?"}
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>model</dt>
                  <dd className="truncate font-mono">
                    {selected.upstreamModel ?? "?"}
                  </dd>
                </div>
                {selected.contextWindow !== undefined && (
                  <div className="flex justify-between gap-2">
                    <dt>context</dt>
                    <dd>{selected.contextWindow.toLocaleString()} tokens</dd>
                  </div>
                )}
                {selected.maxOutputTokens !== undefined && (
                  <div className="flex justify-between gap-2">
                    <dt>max output</dt>
                    <dd>{selected.maxOutputTokens.toLocaleString()} tokens</dd>
                  </div>
                )}
              </dl>
            </div>
          )}
        </div>
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                const plain =
                  !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey;
                const wantsSend = enterToSend
                  ? plain
                  : e.ctrlKey && !e.shiftKey;
                if (wantsSend) {
                  e.preventDefault();
                  submit();
                }
              }
            }}
            placeholder={
              running && queuedCount > 0
                ? `Type to queue after ${queuedCount} message${queuedCount > 1 ? "s" : ""}…`
                : root === CHAT_ROOT_ID
                  ? "Ask Ufuk anything…"
                  : "Ask Ufuk to work on this project…"
            }
            rows={2}
            className="w-full resize-none rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 placeholder-neutral-600 outline-none focus:border-sky-600"
          />
          <button
            type="button"
            onClick={submit}
            disabled={input.trim().length === 0}
            className="shrink-0 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Send
          </button>
          {(running || queuedCount > 0) && (
            <button
              type="button"
              onClick={() => stop(conversationId)}
              className="shrink-0 rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300 hover:bg-red-900/50"
              title="Stop (Esc) — also cancels queued messages"
            >
              ■ Stop
            </button>
          )}
        </div>
        {!running && hasError && (turn?.userText ?? lastMessage) && (
          <div className="mt-2 flex items-center gap-2 text-xs text-neutral-500">
            <span>The last message failed.</span>
            <button
              type="button"
              onClick={() => {
                onTurnStarted();
                void retry(root, conversationId, settings?.defaultTier);
              }}
              className="rounded border border-neutral-700 px-2 py-0.5 text-neutral-300 hover:bg-neutral-800"
            >
              ↻ Retry
            </button>
          </div>
        )}
      </div>
    </footer>
  );
}
