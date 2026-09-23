/**
 * Left sidebar: projects (with add/remove, git-repo warning) and the active
 * project's conversations (select to resume, rename inline, delete with
 * confirm). Antigravity-style: everything the agent manager needs, nothing
 * it does not (no scheduled tasks/MCP/plugins — out of scope by design).
 */
import { useState } from "react";
import { useProjectsStore } from "../stores/projects";

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

export function Sidebar() {
  const {
    projects,
    activeRoot,
    conversations,
    activeConversationId,
    error,
    addProjectWithPicker,
    removeProject,
    selectProject,
    newConversation,
    openConversation,
    renameConversation,
    deleteConversation,
  } = useProjectsStore();
  const [confirmDeleteProject, setConfirmDeleteProject] = useState<
    string | null
  >(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [confirmDeleteConv, setConfirmDeleteConv] = useState<string | null>(
    null,
  );

  const submitRename = (id: string): void => {
    const title = renameValue.trim();
    if (title.length > 0) void renameConversation(id, title);
    setRenamingId(null);
  };

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-neutral-800 bg-neutral-900/50 text-sm">
      {/* projects */}
      <div className="flex items-center justify-between px-3 pb-1 pt-3">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Projects
        </span>
        <button
          type="button"
          onClick={() => void addProjectWithPicker()}
          title="Add project folder"
          className="rounded border border-neutral-700 px-1.5 text-xs text-neutral-400 hover:bg-neutral-800"
        >
          + Add
        </button>
      </div>
      <div className="max-h-56 space-y-0.5 overflow-y-auto px-2 pb-2">
        {projects.map((p) => (
          <div
            key={p.root}
            className="group flex items-center gap-1 rounded px-1.5 py-1 hover:bg-neutral-800/70"
          >
            <button
              type="button"
              onClick={() => void selectProject(p.root)}
              className={
                "min-w-0 flex-1 text-left " +
                (activeRoot === p.root ? "text-sky-300" : "text-neutral-300")
              }
              title={p.root}
            >
              <span className="block truncate">{p.name}</span>
              <span className="flex items-center gap-1 text-[10px] text-neutral-500">
                {!p.isGitRepo && <span title="Not a git repository">⚠</span>}
                {relativeTime(p.lastOpenedAt)}
              </span>
            </button>
            {confirmDeleteProject === p.root ? (
              <span
                className="flex gap-1"
                role="group"
                aria-label="Confirm removal"
              >
                <button
                  type="button"
                  onClick={() => {
                    void removeProject(p.root);
                    setConfirmDeleteProject(null);
                  }}
                  className="rounded bg-red-700 px-1 text-[10px] text-white"
                >
                  remove
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmDeleteProject(null)}
                  className="rounded border border-neutral-700 px-1 text-[10px] text-neutral-400"
                >
                  no
                </button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmDeleteProject(p.root)}
                title="Remove from list"
                className="hidden rounded px-1 text-xs text-neutral-600 hover:text-red-400 group-hover:block"
              >
                ✕
              </button>
            )}
          </div>
        ))}
        {projects.length === 0 && (
          <p className="px-1.5 py-2 text-xs text-neutral-600">
            No projects yet — add a folder to start.
          </p>
        )}
      </div>

      {/* conversations of the active project */}
      <div className="mt-1 flex items-center justify-between border-t border-neutral-800 px-3 pb-1 pt-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Conversations
        </span>
        {activeRoot && (
          <button
            type="button"
            onClick={() => void newConversation()}
            title="New conversation"
            className="rounded border border-neutral-700 px-1.5 text-xs text-neutral-400 hover:bg-neutral-800"
          >
            + New
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        {!activeRoot && (
          <p className="px-1.5 py-2 text-xs text-neutral-600">
            Select a project.
          </p>
        )}
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
                className="w-full rounded border border-sky-600 bg-neutral-950 px-1.5 py-0.5 text-xs text-neutral-100 outline-none"
              />
            ) : (
              <button
                type="button"
                onClick={() => void openConversation(c.id)}
                onDoubleClick={() => {
                  setRenamingId(c.id);
                  setRenameValue(c.title);
                }}
                className={
                  "min-w-0 flex-1 text-left " +
                  (activeConversationId === c.id
                    ? "text-sky-300"
                    : "text-neutral-300")
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
                        void deleteConversation(c.id);
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
        {activeRoot && conversations.length === 0 && (
          <p className="px-1.5 py-2 text-xs text-neutral-600">
            No conversations yet.
          </p>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="m-2 rounded border border-red-900 bg-red-950/50 px-2 py-1 text-[11px] text-red-300"
        >
          {error}
        </div>
      )}
    </aside>
  );
}
