/**
 * Conversation list shared by both sidebar modes (Chat + Projects):
 * select to resume, inline rename (double-click or ✎), delete with
 * confirm. Pure presentational — state lives in the caller's store slice.
 */
import { useState } from "react";
import type { ConversationSummary } from "@shared/ipc";

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(then).toLocaleDateString();
}

export function ConversationList({
  conversations,
  activeId,
  onOpen,
  onRename,
  onDelete,
  emptyHint,
  showNew,
  onNew,
  newTitle,
}: {
  conversations: ConversationSummary[];
  activeId: string | null;
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  emptyHint: string;
  showNew: boolean;
  onNew: () => void;
  newTitle: string;
}) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [confirmDeleteConv, setConfirmDeleteConv] = useState<string | null>(
    null,
  );

  const submitRename = (id: string): void => {
    const title = renameValue.trim();
    if (title.length > 0) onRename(id, title);
    setRenamingId(null);
  };

  return (
    <>
      <div className="flex items-center justify-between px-3 pb-1 pt-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Conversations
        </span>
        {showNew && (
          <button
            type="button"
            onClick={onNew}
            title={newTitle}
            className="rounded border border-neutral-700 px-1.5 text-xs text-neutral-400 hover:bg-neutral-800"
          >
            + New
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        {conversations.map((c) => (
          <div
            key={c.id}
            className="group flex items-center gap-1 rounded px-1.5 py-1 hover:bg-neutral-800/70"
          >
            {renamingId === c.id ? (
              <input
                autoFocus
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onBlur={() => submitRename(c.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") submitRename(c.id);
                  if (e.key === "Escape") setRenamingId(null);
                }}
                maxLength={200}
                aria-label="Rename conversation"
                className="w-full rounded border border-sky-600 bg-neutral-950 px-1.5 py-0.5 text-xs text-neutral-100 outline-none"
              />
            ) : (
              <button
                type="button"
                onClick={() => onOpen(c.id)}
                onDoubleClick={() => {
                  setRenamingId(c.id);
                  setRenameValue(c.title);
                }}
                className={
                  "min-w-0 flex-1 text-left " +
                  (activeId === c.id ? "text-sky-300" : "text-neutral-300")
                }
                title={`${c.title}\n(double-click to rename)`}
              >
                <span className="block truncate text-xs">{c.title}</span>
                <span className="text-[10px] text-neutral-500">
                  {relativeTime(c.updatedAt)}
                  {c.model ? ` · ${c.model}` : ""}
                </span>
              </button>
            )}
            {renamingId !== c.id && (
              <>
                <button
                  type="button"
                  onClick={() => {
                    setRenamingId(c.id);
                    setRenameValue(c.title);
                  }}
                  title="Rename"
                  className="hidden rounded px-1 text-[10px] text-neutral-600 hover:text-sky-400 group-hover:block"
                >
                  ✎
                </button>
                {confirmDeleteConv === c.id ? (
                  <span
                    className="flex gap-1"
                    role="group"
                    aria-label="Confirm delete"
                  >
                    <button
                      type="button"
                      onClick={() => {
                        onDelete(c.id);
                        setConfirmDeleteConv(null);
                      }}
                      className="rounded bg-red-700 px-1 text-[10px] text-white"
                    >
                      delete
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmDeleteConv(null)}
                      className="rounded border border-neutral-700 px-1 text-[10px] text-neutral-400"
                    >
                      no
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirmDeleteConv(c.id)}
                    title="Delete conversation"
                    className="hidden rounded px-1 text-xs text-neutral-600 hover:text-red-400 group-hover:block"
                  >
                    ✕
                  </button>
                )}
              </>
            )}
          </div>
        ))}
        {conversations.length === 0 && (
          <p className="px-1.5 py-2 text-xs text-neutral-600">{emptyHint}</p>
        )}
      </div>
    </>
  );
}
