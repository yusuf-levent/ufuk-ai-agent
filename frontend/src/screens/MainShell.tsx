/**
 * Main shell (logged in): Antigravity-inspired layout — left sidebar
 * (projects + conversations), main chat area, model selector and input at
 * the bottom. Chat sending lands in Milestone 6; the composer is present
 * but disabled so the layout is final.
 */
import { useEffect, useState } from "react";
import { useAppStore } from "../stores/app";
import { useProjectsStore } from "../stores/projects";
import { Sidebar } from "../components/Sidebar";
import { Transcript } from "../components/Transcript";

const TIERS = ["fast", "balanced", "strong"] as const;

export function MainShell({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { settings, session, logout, patchSettings } = useAppStore();
  const {
    activeConversation,
    activeConversationId,
    activeRoot,
    loadProjects,
    projects,
  } = useProjectsStore();
  const [input, setInput] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  const activeProject = projects.find((p) => p.root === activeRoot);
  const title =
    activeConversation?.summary.title ??
    (activeConversationId ? "Conversation" : (activeProject?.name ?? "Ufuk"));

  const doLogout = async (): Promise<void> => {
    setLoggingOut(true);
    try {
      await logout();
    } finally {
      setLoggingOut(false);
    }
  };

  return (
    <div className="flex h-full bg-neutral-950 text-neutral-100">
      <Sidebar />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* header */}
        <header className="flex h-11 shrink-0 items-center gap-3 border-b border-neutral-800 px-4">
          <span className="truncate text-sm font-medium">{title}</span>
          {activeProject && !activeProject.isGitRepo && (
            <span
              className="rounded bg-amber-900/40 px-1.5 py-0.5 text-[10px] text-amber-300"
              title="Changes cannot be committed; consider running git init"
            >
              not a git repo
            </span>
          )}
          <div className="ml-auto flex items-center gap-2 text-xs">
            <span className="text-neutral-500">{session?.email}</span>
            <button
              type="button"
              onClick={onOpenSettings}
              title="Settings"
              aria-label="Settings"
              className="rounded border border-neutral-700 px-2 py-1 text-neutral-400 hover:bg-neutral-800"
            >
              ⚙
            </button>
            <button
              type="button"
              onClick={() => void doLogout()}
              disabled={loggingOut}
              className="rounded border border-neutral-700 px-2 py-1 text-red-300 hover:bg-neutral-800 disabled:opacity-50"
            >
              {loggingOut ? "…" : "Log out"}
            </button>
          </div>
        </header>

        {/* transcript */}
        {activeConversation ? (
          <Transcript messages={activeConversation.messages} />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-sky-500 to-indigo-600 text-2xl font-bold text-white shadow-lg">
              U
            </div>
            <h2 className="text-lg font-semibold">Ufuk</h2>
            <p className="max-w-sm text-sm text-neutral-500">
              {activeRoot
                ? "Pick a conversation on the left, or start a new one."
                : "Add a project folder to begin — pick any local folder containing your code."}
            </p>
          </div>
        )}

        {/* composer: model selector + input (sending lands in M6) */}
        <footer className="shrink-0 border-t border-neutral-800 p-3">
          <div className="mx-auto max-w-3xl">
            <div className="mb-2 flex items-center gap-2 text-xs text-neutral-500">
              <label className="flex items-center gap-1">
                model
                <select
                  value={settings?.defaultTier ?? "fast"}
                  onChange={(e) =>
                    void patchSettings({ defaultTier: e.target.value })
                  }
                  className="rounded border border-neutral-700 bg-neutral-900 px-1.5 py-0.5 text-xs text-neutral-200"
                >
                  {TIERS.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask Ufuk to work on this project… (chat arrives in the next milestone)"
              disabled
              rows={2}
              className="w-full resize-none rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 placeholder-neutral-600 outline-none focus:border-sky-600"
            />
          </div>
        </footer>
      </div>
    </div>
  );
}
