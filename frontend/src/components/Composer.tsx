/**
 * Composer (bottom bar): model selector (tier alias) + message input.
 * Enter sends, Shift+Enter inserts a newline; the Stop button aborts the
 * active run; Retry re-sends the last message after a failure. Esc (global)
 * and Ctrl+N (global) are handled in MainShell. Approval prompts render as
 * the modal hosted by MainShell (Milestone 7).
 */
import { useState } from "react";
import { useAppStore } from "../stores/app";
import { useChatStore } from "../stores/chat";

const TIERS = ["fast", "balanced", "strong"] as const;

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
  const running = useChatStore(
    (s) => s.turns[conversationId]?.running ?? false,
  );
  const hasError = useChatStore(
    (s) => s.turns[conversationId]?.error ?? null,
  );
  const lastMessage = useChatStore(
    (s) => s.lastMessage[conversationId] ?? null,
  );
  const send = useChatStore((s) => s.send);
  const stop = useChatStore((s) => s.stop);
  const retry = useChatStore((s) => s.retry);
  const [input, setInput] = useState("");

  const submit = (): void => {
    const message = input.trim();
    if (!message || running) return;
    setInput("");
    onTurnStarted();
    void send(root, conversationId, message, settings?.defaultTier);
  };

  return (
    <footer className="shrink-0 border-t border-neutral-800 p-3">
      <div className="mx-auto max-w-3xl">
        <div className="mb-2 flex items-center gap-3 text-xs text-neutral-500">
          <label className="flex items-center gap-1">
            model
            <select
              value={settings?.defaultTier ?? "fast"}
              onChange={(e) =>
                void patchSettings({ defaultTier: e.target.value })
              }
              disabled={running}
              className="rounded border border-neutral-700 bg-neutral-900 px-1.5 py-0.5 text-xs text-neutral-200"
            >
              {TIERS.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <span className="ml-auto text-[10px]">
            Enter to send · Shift+Enter for a new line
          </span>
        </div>
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="Ask Ufuk to work on this project…"
            rows={2}
            disabled={running}
            className="w-full resize-none rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 placeholder-neutral-600 outline-none focus:border-sky-600 disabled:opacity-60"
          />
          {running ? (
            <button
              type="button"
              onClick={() => stop(conversationId)}
              className="shrink-0 rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300 hover:bg-red-900/50"
              title="Stop (Esc)"
            >
              ■ Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={input.trim().length === 0}
              className="shrink-0 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Send
            </button>
          )}
        </div>
        {!running && hasError && lastMessage && (
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
