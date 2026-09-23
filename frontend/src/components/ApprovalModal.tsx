/**
 * Approval modal (Milestone 7): shows the exact command or file path, the
 * working directory, a risk category, the model's stated reason (the
 * assistant text streamed before the request) and the "always allow"
 * pattern (fetched from the main process — the same rule the engine would
 * persist). Buttons: Allow once / Always allow (this project) / Deny.
 */
import { useEffect, useState } from "react";
import { useChatStore } from "../stores/chat";
import { api } from "../ipc/client";

/** Display-only categorization; the permission engine remains the enforcer. */
function riskCategory(tool: string, input: Record<string, unknown>): {
  label: string;
  detail?: string;
} {
  switch (tool) {
    case "run_command":
      return {
        label: "Command execution",
        detail:
          "Runs a shell command in the project folder. Commands touching paths outside the workspace or matching dangerous patterns are blocked regardless of this decision.",
      };
    case "write_file":
    case "edit_file": {
      const path = typeof input["path"] === "string" ? input["path"] : "";
      return {
        label: "File edit",
        detail: path
          ? `Writes to ${path} inside the workspace. Denylisted files (e.g. .env, *.pem) are blocked regardless of this decision.`
          : "Writes a file inside the workspace.",
      };
    }
    case "git_commit":
      return { label: "Git", detail: "Creates a commit in this repository." };
    case "git_branch":
      return { label: "Git", detail: "Creates or switches a branch." };
    default:
      return { label: tool, detail: "Tool execution." };
  }
}

function exactAction(tool: string, input: Record<string, unknown>): string {
  if (tool === "run_command" && typeof input["command"] === "string") {
    return input["command"];
  }
  if (typeof input["path"] === "string") {
    return input["path"];
  }
  return JSON.stringify(input, null, 2);
}

export function ApprovalModal({
  conversationId,
  workspaceRoot,
  modelReason,
}: {
  conversationId: string;
  workspaceRoot: string;
  /** Assistant text streamed before the request (the model's stated reason). */
  modelReason: string;
}) {
  const approval = useChatStore(
    (s) => s.turns[conversationId]?.approval ?? null,
  );
  const respond = useChatStore((s) => s.respondApproval);
  const [pattern, setPattern] = useState<string | null>(null);
  const approvalId = approval?.id ?? null;

  useEffect(() => {
    setPattern(null);
    if (!approvalId) return;
    let cancelled = false;
    api
      .approvalPreview({ conversationId, approvalId })
      .then((preview) => {
        if (!cancelled) setPattern(preview?.pattern ?? preview?.tool ?? null);
      })
      .catch(() => {
        if (!cancelled) setPattern(null);
      });
    return () => {
      cancelled = true;
    };
  }, [approvalId, conversationId]);

  if (!approval) return null;
  const input = (approval.input ?? {}) as Record<string, unknown>;
  const risk = riskCategory(approval.tool, input);
  const reasonExcerpt = modelReason.trim().slice(-600);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6">
      <div
        role="dialog"
        aria-label="Permission request"
        className="w-full max-w-xl rounded-xl border border-amber-700 bg-neutral-900 shadow-2xl"
      >
        <div className="border-b border-neutral-800 px-5 py-3">
          <h2 className="text-sm font-semibold text-amber-300">
            Permission needed — {risk.label}
          </h2>
        </div>
        <div className="space-y-3 px-5 py-4 text-xs">
          <div>
            <div className="mb-1 text-neutral-500">
              {approval.tool === "run_command" ? "Command" : "File"}
            </div>
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-md border border-neutral-800 bg-neutral-950 px-3 py-2 font-mono text-neutral-200">
              {exactAction(approval.tool, input)}
            </pre>
          </div>
          <div className="flex gap-4">
            <div className="min-w-0 flex-1">
              <div className="text-neutral-500">Working directory</div>
              <div className="truncate font-mono text-neutral-300">
                {workspaceRoot}
              </div>
            </div>
          </div>
          <div>
            <div className="text-neutral-500">Risk</div>
            <p className="text-neutral-300">{risk.detail}</p>
          </div>
          {reasonExcerpt && (
            <div>
              <div className="text-neutral-500">The model says</div>
              <p className="max-h-24 overflow-auto rounded-md border border-neutral-800 bg-neutral-950/60 px-3 py-2 text-neutral-300">
                {reasonExcerpt}
              </p>
            </div>
          )}
          <p className="text-[11px] text-neutral-500">
            {pattern !== null
              ? `"Always allow" will remember: ${approval.tool}${
                  pattern && pattern !== approval.tool
                    ? ` — ${pattern}`
                    : " (every input)"
                } for this project.`
              : "…"}
          </p>
        </div>
        <div className="flex justify-end gap-2 border-t border-neutral-800 px-5 py-3">
          <button
            type="button"
            onClick={() => respond(conversationId, approval.id, false, false)}
            className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:bg-neutral-800"
          >
            Deny
          </button>
          <button
            type="button"
            onClick={() => respond(conversationId, approval.id, true, true)}
            className="rounded-md border border-amber-700 px-3 py-1.5 text-xs text-amber-200 hover:bg-amber-900/40"
          >
            Always allow (this project)
          </button>
          <button
            type="button"
            onClick={() => respond(conversationId, approval.id, true, false)}
            className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-500"
          >
            Allow once
          </button>
        </div>
      </div>
    </div>
  );
}
