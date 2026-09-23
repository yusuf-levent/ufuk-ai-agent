/**
 * Read-only conversation transcript (M5). Assistant/user text renders
 * through SafeMarkdown (untrusted output); tool messages show as compact
 * system rows. Live streaming, the tool-step timeline and the composer
 * arrive in Milestone 6 — this component renders persisted history.
 */
import { memo } from "react";
import type { ChatMessage } from "@shared/ipc";
import { SafeMarkdown } from "./SafeMarkdown";

function ToolRow({ message }: { message: ChatMessage & { role: "tool" } }) {
  const output = message.content;
  const preview = output.length > 200 ? `${output.slice(0, 200)}…` : output;
  return (
    <div className="mx-auto max-w-3xl rounded-md border border-neutral-800 bg-neutral-900/60 px-3 py-1.5 text-xs text-neutral-400">
      <span className="font-mono text-neutral-500">tool:{message.name}</span>
      <span className="ml-2 whitespace-pre-wrap break-all">{preview}</span>
    </div>
  );
}

export const Transcript = memo(function Transcript({
  messages,
}: {
  messages: ChatMessage[];
}) {
  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-sm text-neutral-600">
        This conversation is empty — send a message to start (chat arrives in
        the next milestone).
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
                  <SafeMarkdown text={m.content} />
                </div>
              );
            }
            return (
              <div
                key={i}
                className="self-end rounded-xl bg-sky-600/90 px-4 py-2 text-sm text-white"
              >
                <div className="whitespace-pre-wrap break-words">
                  {m.content}
                </div>
              </div>
            );
          })}
      </div>
    </div>
  );
});
