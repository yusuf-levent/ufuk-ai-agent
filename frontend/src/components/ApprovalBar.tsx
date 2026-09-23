/**
 * Pending approval bar (M6 scope: Allow once / Always allow / Deny for the
 * current request). Milestone 7 replaces this with the full modal (exact
 * command/path, cwd, risk category, model reason, pattern preview).
 */
import { useChatStore } from "../stores/chat";

export function ApprovalBar({ conversationId }: { conversationId: string }) {
  const approval = useChatStore(
    (s) => s.turns[conversationId]?.approval ?? null,
  );
  const respond = useChatStore((s) => s.respondApproval);
  if (!approval) return null;

  const input = approval.input as Record<string, unknown> | null;
  const detail =
    input && typeof input === "object"
      ? Object.entries(input)
          .slice(0, 4)
          .map(([k, v]) => `${k}: ${String(v).slice(0, 120)}`)
          .join(" · ")
      : "";

  return (
    <div
      role="alertdialog"
      aria-label="Permission request"
      className="mx-auto mb-2 w-full max-w-3xl rounded-lg border border-amber-700 bg-amber-950/40 px-3 py-2 text-xs text-amber-200"
    >
      <div className="font-medium">
        Permission needed: <span className="font-mono">{approval.tool}</span>
      </div>
      {detail && <div className="mt-0.5 break-all opacity-80">{detail}</div>}
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          onClick={() =>
            respond(conversationId, approval.id, true, false)
          }
          className="rounded bg-amber-600 px-2 py-1 font-medium text-white hover:bg-amber-500"
        >
          Allow once
        </button>
        <button
          type="button"
          onClick={() =>
            respond(conversationId, approval.id, true, true)
          }
          className="rounded border border-amber-700 px-2 py-1 hover:bg-amber-900/50"
        >
          Always allow (this project)
        </button>
        <button
          type="button"
          onClick={() =>
            respond(conversationId, approval.id, false, false)
          }
          className="rounded border border-neutral-700 px-2 py-1 text-neutral-300 hover:bg-neutral-800"
        >
          Deny
        </button>
      </div>
    </div>
  );
}
