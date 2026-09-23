/**
 * Right panel (Milestone 7): per-conversation changed files (from recorded
 * tool calls) with the diff viewer, plus the project's checkpoint history
 * with undo-last / revert-to-checkpoint and the per-project permission
 * mode switch (ask every time / auto-accept edits inside the workspace —
 * there is intentionally NO allow-everything mode).
 */
import { useEffect, useRef, useState } from "react";
import { api } from "../ipc/client";
import type { CheckpointInfo, DiffResponse, ProjectInfo } from "@shared/ipc";
import type { ToolStep } from "../stores/chat";
import { DiffViewer } from "./DiffViewer";

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.floor((Date.now() - then) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(then).toLocaleDateString();
}

export function ChangesPanel({
  project,
  conversationId,
  liveSteps,
  turnActive,
  onConversationDeleted,
}: {
  project: ProjectInfo;
  conversationId: string | null;
  liveSteps: ToolStep[];
  /** True while the conversation's agent run is active (refresh on end). */
  turnActive: boolean;
  onConversationDeleted?: () => void;
}) {
  const [tab, setTab] = useState<"files" | "history">("files");
  const [changedFiles, setChangedFiles] = useState<
    { path: string; tool: string; ok: boolean; at: string }[]
  >([]);
  const [checkpoints, setCheckpoints] = useState<CheckpointInfo[]>([]);
  const [diff, setDiff] = useState<DiffResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmRevert, setConfirmRevert] = useState<string | null>(null);
  const [mode, setMode] = useState<"ask" | "auto-edits">(
    project.permissionMode ?? "ask",
  );
  const [note, setNote] = useState<string | null>(null);

  const refresh = async (): Promise<void> => {
    if (!conversationId) {
      setChangedFiles([]);
    } else {
      try {
        setChangedFiles(await api.changedFiles(project.root, conversationId));
      } catch {
        setChangedFiles([]);
      }
    }
    try {
      setCheckpoints(await api.listCheckpoints(project.root));
    } catch {
      setCheckpoints([]);
    }
  };

  useEffect(() => {
    setMode(project.permissionMode ?? "ask");
  }, [project.root, project.permissionMode]);

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.root, conversationId]);

  // re-fetch when a run finishes (changed files / checkpoints are new
  // then). The main process persists tool calls just AFTER the done event,
  // so a delayed second fetch closes the race.
  const wasActive = useRef(false);
  useEffect(() => {
    if (wasActive.current && !turnActive) {
      void refresh();
      const timer = setTimeout(() => void refresh(), 1500);
      return () => clearTimeout(timer);
    }
    wasActive.current = turnActive;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turnActive]);

  // live file changes from the current run appear immediately
  const livePaths = liveSteps
    .filter((s) => (s.name === "write_file" || s.name === "edit_file") && s.ok)
    .map(
      (s) =>
        s.argsSummary
          .replace(/^path:\s*/, "")
          .split(",")[0]
          ?.trim() ?? "",
    )
    .filter((p) => p.length > 0 && !changedFiles.some((c) => c.path === p));

  const openDiff = async (path: string): Promise<void> => {
    setBusy(true);
    try {
      setDiff(await api.diffFile({ root: project.root, path }));
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const undoLast = async (): Promise<void> => {
    setBusy(true);
    setNote(null);
    try {
      const undone = await api.undoCheckpoint(project.root);
      setNote(
        undone
          ? `Undid ${undone.tool} (${undone.files.map((f) => f.path).join(", ")})`
          : "Nothing left to undo.",
      );
      await refresh();
      onConversationDeleted?.();
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const revert = async (id: string): Promise<void> => {
    setBusy(true);
    setNote(null);
    try {
      const done = await api.revertCheckpoint(project.root, id);
      setNote(done ? "Reverted to checkpoint." : "Checkpoint not found.");
      setConfirmRevert(null);
      await refresh();
      onConversationDeleted?.();
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const applyMode = async (next: "ask" | "auto-edits"): Promise<void> => {
    setMode(next);
    try {
      await api.setPermissionMode(project.root, next);
      setNote(
        next === "auto-edits"
          ? "Edits inside the workspace now run without asking. Commands still ask."
          : "Every edit and command asks for approval again.",
      );
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-l border-neutral-800 bg-neutral-900/50 text-xs">
      {/* permission mode */}
      <div className="border-b border-neutral-800 px-3 py-2.5">
        <div className="mb-1.5 font-semibold uppercase tracking-wider text-neutral-500">
          Permission mode
        </div>
        <div className="space-y-1">
          {(
            [
              { value: "ask", label: "Ask every time" },
              {
                value: "auto-edits",
                label: "Auto-accept edits inside the workspace",
              },
            ] as const
          ).map((m) => (
            <label
              key={m.value}
              className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-neutral-800/60"
            >
              <input
                type="radio"
                name="proj-mode"
                checked={mode === m.value}
                onChange={() => void applyMode(m.value)}
                className="accent-sky-500"
              />
              <span className="text-neutral-300">{m.label}</span>
            </label>
          ))}
        </div>
      </div>

      {/* tabs */}
      <div className="flex border-b border-neutral-800">
        {(
          [
            ["files", "Changed files"],
            ["history", "History"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={
              "flex-1 px-3 py-2 " +
              (tab === key
                ? "border-b-2 border-sky-500 text-sky-300"
                : "text-neutral-500 hover:text-neutral-300")
            }
          >
            {label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {tab === "files" && (
          <div className="space-y-0.5">
            {!conversationId && (
              <p className="px-1.5 py-2 text-neutral-600">
                Select a conversation.
              </p>
            )}
            {conversationId &&
              changedFiles.length === 0 &&
              livePaths.length === 0 && (
                <p className="px-1.5 py-2 text-neutral-600">
                  No file changes in this conversation yet.
                </p>
              )}
            {livePaths.map((p) => (
              <div
                key={`live-${p}`}
                className="flex items-center gap-1 rounded px-1.5 py-1 text-sky-300"
              >
                <span title="changed in the current run">●</span>
                <span className="truncate font-mono">{p}</span>
              </div>
            ))}
            {changedFiles.map((f) => (
              <button
                key={f.path}
                type="button"
                disabled={busy}
                onClick={() => void openDiff(f.path)}
                className="flex w-full items-center gap-1 rounded px-1.5 py-1 text-left hover:bg-neutral-800/70 disabled:opacity-50"
                title="Show diff against the pre-change snapshot"
              >
                <span className={f.ok ? "text-neutral-500" : "text-red-400"}>
                  {f.ok ? "✎" : "✗"}
                </span>
                <span className="truncate font-mono text-neutral-300">
                  {f.path}
                </span>
                <span className="ml-auto shrink-0 text-[10px] text-neutral-600">
                  {f.tool}
                </span>
              </button>
            ))}
          </div>
        )}

        {tab === "history" && (
          <div className="space-y-1">
            <button
              type="button"
              disabled={busy || checkpoints.length === 0}
              onClick={() => void undoLast()}
              className="w-full rounded border border-neutral-700 px-2 py-1 text-neutral-300 hover:bg-neutral-800 disabled:opacity-40"
            >
              ↩ Undo last change
            </button>
            {checkpoints.length === 0 && (
              <p className="px-1.5 py-2 text-neutral-600">
                No checkpoints yet.
              </p>
            )}
            {checkpoints.map((c) => (
              <div
                key={c.id}
                className="rounded border border-neutral-800 px-2 py-1.5"
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-neutral-400">{c.tool}</span>
                  <span className="text-[10px] text-neutral-600">
                    {relativeTime(c.createdAt)}
                  </span>
                  {confirmRevert === c.id ? (
                    <span className="ml-auto flex gap-1">
                      <button
                        type="button"
                        onClick={() => void revert(c.id)}
                        className="rounded bg-red-700 px-1.5 py-0.5 text-[10px] text-white"
                      >
                        revert here
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmRevert(null)}
                        className="rounded border border-neutral-700 px-1.5 py-0.5 text-[10px]"
                      >
                        no
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmRevert(c.id)}
                      className="ml-auto text-[10px] text-neutral-500 hover:text-red-400"
                    >
                      revert to checkpoint
                    </button>
                  )}
                </div>
                <div className="mt-0.5 space-y-0.5">
                  {c.files.map((f) => (
                    <button
                      key={f.path}
                      type="button"
                      disabled={busy}
                      onClick={() => void openDiff(f.path)}
                      className="block w-full truncate text-left font-mono text-[10px] text-neutral-500 hover:text-neutral-300 disabled:opacity-50"
                    >
                      {f.existedBefore ? "✎" : "+"} {f.path}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {note && (
        <div className="m-2 rounded border border-neutral-800 bg-neutral-950/60 px-2 py-1 text-[11px] text-neutral-400">
          {note}
        </div>
      )}

      {diff && <DiffViewer diff={diff} onClose={() => setDiff(null)} />}
    </aside>
  );
}
