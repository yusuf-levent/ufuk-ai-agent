/**
 * Conversation transcript (M6): persisted history (read-only) + the live
 * agent turn — streaming text, collapsed dimmed reasoning, collapsible
 * tool-step timeline (name, args summary, result summary, duration), the
 * pending approval bar and per-turn usage. Long outputs are truncated with
 * a reveal toggle so the DOM never freezes.
 */
import { memo, useState } from "react";
import type { ChatMessage } from "@shared/ipc";
import { SafeMarkdown } from "./SafeMarkdown";
import { FriendlyErrorView } from "./FriendlyErrorView";
import { useChatStore, type LiveTurn, type ToolStep } from "../stores/chat";

const MAX_INLINE = 6_000;

function Reveal({
  text,
  limit = MAX_INLINE,
}: {
  text: string;
  limit?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  if (text.length <= limit) {
    return <span className="whitespace-pre-wrap break-words">{text}</span>;
  }
  return (
    <span>
      <span className="whitespace-pre-wrap break-words">
        {expanded ? text : `${text.slice(0, limit)}…`}
      </span>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="ml-1 text-xs text-sky-400 hover:underline"
      >
        {expanded
          ? "show less"
          : `show all (${text.length.toLocaleString()} chars)`}
      </button>
    </span>
  );
}

/**
 * Markdown with a hard cap: long UNTRUSTED outputs render truncated with a
 * reveal toggle, so a huge reply never freezes the DOM.
 */
function CappedMarkdown({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const capped = text.length > MAX_MARKDOWN;
  return (
    <div>
      <SafeMarkdown text={expanded ? text : text.slice(0, MAX_MARKDOWN)} />
      {capped && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="mt-1 text-xs text-sky-400 hover:underline"
        >
          {expanded
            ? "show less"
            : `show all (${text.length.toLocaleString()} chars)`}
        </button>
      )}
    </div>
  );
}

const MAX_MARKDOWN = 12_000;

function Reasoning({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <div className="text-xs text-neutral-600">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="italic hover:text-neutral-400"
      >
        {open ? "▾ hide reasoning" : "▸ reasoning"}
      </button>
      {open && (
        <p className="mt-1 whitespace-pre-wrap border-l border-neutral-800 pl-2 leading-relaxed opacity-70">
          <Reveal text={text} />
        </p>
      )}
    </div>
  );
}

function Step({ step }: { step: ToolStep }) {
  const [open, setOpen] = useState(false);
  const statusIcon =
    step.status === "running"
      ? "⟳"
      : step.status === "denied"
        ? "⊘"
        : step.ok
          ? "✓"
          : "✗";
  const statusColor =
    step.status === "denied"
      ? "text-amber-500"
      : step.status === "running"
        ? "text-sky-400"
        : step.ok
          ? "text-neutral-500"
          : "text-red-400";
  return (
    <div className="rounded-md border border-neutral-800 bg-neutral-900/60 text-xs">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-neutral-800/50"
      >
        <span className={statusColor}>{statusIcon}</span>
        <span className="font-mono text-neutral-300">{step.name}</span>
        <span className="min-w-0 flex-1 truncate text-neutral-500">
          {step.argsSummary}
        </span>
        {step.durationMs !== null && (
          <span className="shrink-0 text-neutral-600">{step.durationMs}ms</span>
        )}
        <span className="shrink-0 text-neutral-600">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="space-y-1 border-t border-neutral-800 px-2 py-1.5">
          {step.output && (
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-neutral-400">
              {step.output.length > 4_000
                ? `${step.output.slice(0, 4_000)}…`
                : step.output}
            </pre>
          )}
          {step.status === "running" && (
            <p className="text-[11px] text-sky-400">running…</p>
          )}
          {step.status === "denied" && (
            <p className="text-[11px] text-amber-500">
              denied — the request was blocked
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function ToolRow({ message }: { message: ChatMessage & { role: "tool" } }) {
  const output = message.content;
  return (
    <div className="mx-auto max-w-3xl rounded-md border border-neutral-800 bg-neutral-900/60 px-3 py-1.5 text-xs text-neutral-400">
      <span className="font-mono text-neutral-500">tool:{message.name}</span>
      <span className="ml-2 whitespace-pre-wrap break-all">
        {output.length > 200 ? `${output.slice(0, 200)}…` : output}
      </span>
    </div>
  );
}

function UsageBar({ turn }: { turn: LiveTurn }) {
  const usage = turn.usage;
  if (!usage) return null;
  return (
    <div className="flex items-center gap-3 text-[10px] text-neutral-600">
      <span>
        tokens: {(usage.promptTokens ?? 0).toLocaleString()} in +{" "}
        {(usage.completionTokens ?? 0).toLocaleString()} out
      </span>
      {usage.totalTokens !== undefined && (
        <span>({usage.totalTokens.toLocaleString()} total)</span>
      )}
    </div>
  );
}

export const LiveTurnView = memo(function LiveTurnView({
  turn,
  covered = false,
}: {
  turn: LiveTurn;
  /**
   * True once the persisted conversation history already contains this
   * run's messages (user + assistant + tool rows). The live text/steps
   * are a preview of exactly that persisted content, so they are hidden
   * when covered — otherwise the final answer would render twice (once
   * as the normal message bubble, once more under the reasoning
   * section). Reasoning, usage and errors are never persisted and always
   * stay. While the run is active the history cannot contain it yet, so
   * streaming output always shows.
   */
  covered?: boolean;
}) {
  const showOutput = turn.running || !covered;
  const hasContent =
    (showOutput && (turn.text || turn.steps.length > 0)) ||
    turn.reasoning ||
    turn.fileChanges.length > 0 ||
    turn.usage ||
    turn.error ||
    turn.running;
  if (!hasContent) return null;
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-3">
      <Reasoning text={turn.reasoning} />
      {showOutput && turn.steps.length > 0 && (
        <div className="space-y-1">
          {turn.steps.map((s) => (
            <Step key={s.id} step={s} />
          ))}
        </div>
      )}
      {showOutput && turn.text && (
        <div className="self-start text-sm text-neutral-100">
          <CappedMarkdown text={turn.text} />
        </div>
      )}
      <UsageBar turn={turn} />
      {turn.error && <FriendlyErrorView turn={turn} />}
    </div>
  );
});

/**
 * True when the persisted history already contains the run triggered by
 * `userText`: the run's user message and its output (assistant text,
 * tool rows) are persisted together, so matching the run's user text
 * against the LAST user message in history means the whole turn has
 * landed. (A re-sent identical message whose run failed without
 * persisting can false-positive; the cost is hiding the partial streamed
 * text of that failed run — the error view still shows.)
 */
export function historyCoversRun(
  messages: ChatMessage[],
  userText: string,
): boolean {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m && m.role === "user") return m.content === userText;
  }
  return false;
}

export const Transcript = memo(function Transcript({
  messages,
  liveTurn,
  conversationId,
}: {
  messages: ChatMessage[];
  liveTurn?: LiveTurn;
  /** Active conversation — resolves the live turn's triggering message. */
  conversationId?: string;
}) {
  // the run's user message: set on send, kept for retry
  const runUserText = useChatStore((s) =>
    conversationId ? s.lastMessage[conversationId] : undefined,
  );
  const covered =
    liveTurn && runUserText ? historyCoversRun(messages, runUserText) : false;
  const empty = messages.length === 0 && !liveTurn;
  if (empty) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-sm text-neutral-600">
        This conversation is empty — send a message below to start.
      </div>
    );
  }
  return (
    <div className="flex-1 overflow-y-auto px-4 py-6">
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        {messages
          .filter((m) => m.role !== "system")
          .map((m, i) => {
            if (m.role === "tool") return <ToolRow key={i} message={m} />;
            if (m.role === "assistant") {
              if (!m.content) return null; // pure tool-call turn
              return (
                <div key={i} className="self-start text-sm text-neutral-100">
                  <CappedMarkdown text={m.content} />
                </div>
              );
            }
            return (
              <div
                key={i}
                className="self-end rounded-xl bg-sky-600/90 px-4 py-2 text-sm text-white"
              >
                <Reveal text={m.content} />
              </div>
            );
          })}
        {liveTurn && <LiveTurnView turn={liveTurn} covered={covered} />}
      </div>
    </div>
  );
});
