/**
 * Left sidebar: top-level mode switcher (Chat | Projects) + the active
 * mode's content. Chat mode lists tool-less conversations (no folder
 * needed — works immediately). Projects mode keeps the existing flow:
 * projects (add/remove, git-repo warning) + the selected project's
 * conversations. Switching modes never resets either slice — both live
 * in the same Zustand store.
 *
 * Bottom-left account area (Codex/Claude-style): avatar + email + gear
 * opening the settings dialog; the header keeps only title/credits/
 * copy/logout.
 */
import { useState } from "react";
import { useAppStore } from "../stores/app";
import { useProjectsStore } from "../stores/projects";
import { ConversationList } from "./ConversationList";

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

export function Sidebar({ onOpenSettings }: { onOpenSettings: () => void }) {
  const mode = useAppStore((s) => s.mode);
  const setMode = useAppStore((s) => s.setMode);
  const session = useAppStore((s) => s.session);
  const {
    projects,
    activeRoot,
    conversations,
    activeConversationId,
    chatConversations,
    activeChatConversationId,
    error,
    addProjectWithPicker,
    removeProject,
    selectProject,
    newConversation,
    openConversation,
    renameConversation,
    deleteConversation,
    newChatConversation,
    openChatConversation,
    renameChatConversation,
    deleteChatConversation,
  } = useProjectsStore();
  const [confirmDeleteProject, setConfirmDeleteProject] = useState<
    string | null
  >(null);

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-neutral-800 bg-neutral-900/50 text-sm">
      {/* top-level mode switcher: Chat vs Projects */}
      <div
        role="tablist"
        aria-label="Mode"
        className="m-3 mb-2 grid grid-cols-2 overflow-hidden rounded-lg border border-neutral-700 text-xs"
      >
        {(["chat", "projects"] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            onClick={() => void setMode(m)}
            className={
              "px-3 py-1.5 font-medium capitalize transition-colors " +
              (mode === m
                ? "bg-sky-600 text-white"
                : "text-neutral-400 hover:bg-neutral-800")
            }
          >
            {m === "chat" ? "Chat" : "Projects"}
          </button>
        ))}
      </div>

      {mode === "chat" ? (
        <ConversationList
          conversations={chatConversations}
          activeId={activeChatConversationId}
          onOpen={(id) => void openChatConversation(id)}
          onRename={(id, title) => void renameChatConversation(id, title)}
          onDelete={(id) => void deleteChatConversation(id)}
          emptyHint="No chats yet — start one (Ctrl+N)."
          showNew
          onNew={() => void newChatConversation()}
          newTitle="New chat"
        />
      ) : (
        <>
          {/* projects */}
          <div className="flex items-center justify-between px-3 pb-1 pt-1">
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
                    (activeRoot === p.root
                      ? "text-sky-300"
                      : "text-neutral-300")
                  }
                  title={p.root}
                >
                  <span className="block truncate">{p.name}</span>
                  <span className="flex items-center gap-1 text-[10px] text-neutral-500">
                    {!p.isGitRepo && (
                      <span title="Not a git repository">⚠</span>
                    )}
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
          {activeRoot ? (
            <ConversationList
              conversations={conversations}
              activeId={activeConversationId}
              onOpen={(id) => void openConversation(id)}
              onRename={(id, title) => void renameConversation(id, title)}
              onDelete={(id) => void deleteConversation(id)}
              emptyHint="No conversations yet."
              showNew
              onNew={() => void newConversation()}
              newTitle="New conversation"
            />
          ) : (
            <p className="px-3 py-2 text-xs text-neutral-600">
              Select a project.
            </p>
          )}
        </>
      )}

      {error && (
        <div
          role="alert"
          className="m-2 rounded border border-red-900 bg-red-950/50 px-2 py-1 text-[11px] text-red-300"
        >
          {error}
        </div>
      )}

      {/* bottom-left account area (Codex-style): avatar + email + gear */}
      <div className="mt-auto flex items-center gap-2 border-t border-neutral-800 px-3 py-2.5">
        <div
          className="flex h-7 w-7 shrink-0 select-none items-center justify-center rounded-full bg-gradient-to-br from-sky-500 to-indigo-600 text-xs font-bold text-white"
          aria-hidden="true"
        >
          {(session?.displayName ?? session?.email ?? "?")
            .slice(0, 1)
            .toUpperCase()}
        </div>
        <span
          className="min-w-0 flex-1 truncate text-xs text-neutral-400"
          title={session?.email ?? ""}
        >
          {session?.displayName ?? session?.email ?? "not logged in"}
        </span>
        <button
          type="button"
          onClick={onOpenSettings}
          title="Settings"
          aria-label="Settings"
          className="shrink-0 rounded-md border border-neutral-700 px-2 py-1 text-xs text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200"
        >
          ⚙
        </button>
      </div>
    </aside>
  );
}
