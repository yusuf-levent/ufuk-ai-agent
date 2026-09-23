/**
 * Main shell (logged in): Antigravity-inspired layout — left sidebar
 * (projects + conversations), main chat area, model selector and input at
 * the bottom. M6: streaming chat with tool timeline, reasoning, stop/
 * retry, per-turn usage, keyboard shortcuts (Enter/Shift+Enter in the
 * composer; Esc stops; Ctrl+N new conversation).
 */
import { useEffect, useRef, useState } from "react";
import { useAppStore } from "../stores/app";
import { useProjectsStore } from "../stores/projects";
import { useChatStore } from "../stores/chat";
import { useModelsStore } from "../stores/models";
import { Sidebar } from "../components/Sidebar";
import { Transcript } from "../components/Transcript";
import { Composer } from "../components/Composer";
import { ApprovalModal } from "../components/ApprovalModal";
import { ChangesPanel } from "../components/ChangesPanel";

function CreditIndicator() {
  const usage = useModelsStore((s) => s.usage);
  const usageError = useModelsStore((s) => s.usageError);
  const usageErrorCode = useModelsStore((s) => s.usageErrorCode);
  if (usage) {
    const pct =
      usage.creditLimit > 0
        ? Math.min(100, (usage.creditsUsed / usage.creditLimit) * 100)
        : 0;
    return (
      <span
        className="flex items-center gap-1.5 text-neutral-400"
        title={`${usage.planName} · period ends ${
          usage.periodEnd
            ? new Date(usage.periodEnd).toLocaleDateString()
            : "—"
        } · ${usage.requestsPerMinute} req/min`}
      >
        <span className="h-1.5 w-14 overflow-hidden rounded-full bg-neutral-800">
          <span
            className={
              "block h-full " +
              (pct > 90 ? "bg-red-500" : pct > 70 ? "bg-amber-500" : "bg-sky-500")
            }
            style={{ width: `${pct}%` }}
          />
        </span>
        <span className="tabular-nums text-[10px]">
          {usage.creditsRemaining.toLocaleString(undefined, {
            maximumFractionDigits: 1,
          })}{" "}
          / {usage.creditLimit.toLocaleString(undefined, { maximumFractionDigits: 0 })}
        </span>
      </span>
    );
  }
  if (usageErrorCode === "subscription_inactive") {
    return (
      <span
        className="rounded bg-amber-900/40 px-1.5 py-0.5 text-[10px] text-amber-300"
        title={usageError ?? undefined}
      >
        no active subscription
      </span>
    );
  }
  return null;
}

export function MainShell({
  onOpenSettings,
}: {
  onOpenSettings: () => void;
}) {
  const { session, logout } = useAppStore();
  const {
    activeConversation,
    activeConversationId,
    activeRoot,
    loadProjects,
    projects,
    newConversation,
    reloadActive,
  } = useProjectsStore();
  const subscribe = useChatStore((s) => s.subscribe);
  const turns = useChatStore((s) => s.turns);
  const stop = useChatStore((s) => s.stop);
  const refreshModels = useModelsStore((s) => s.refresh);
  const [loggingOut, setLoggingOut] = useState(false);
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    void loadProjects();
    subscribe();
    void refreshModels();
  }, [loadProjects, subscribe, refreshModels]);

  // when the active run finishes (running -> false with content), reload
  // the persisted conversation so history stays the single source of truth
  const turn = activeConversationId ? turns[activeConversationId] : undefined;
  const runningRef = useRef(false);
  useEffect(() => {
    const wasRunning = runningRef.current;
    runningRef.current = turn?.running ?? false;
    if (wasRunning && !runningRef.current) {
      void reloadActive();
      void refreshModels(); // credits changed
    }
  }, [turn?.running, reloadActive, refreshModels]);

  // global shortcuts: Esc stops the active run, Ctrl+N new conversation
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape" && activeConversationId) {
        stop(activeConversationId);
      }
      if (e.key === "n" && e.ctrlKey && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        void newConversation();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [activeConversationId, stop, newConversation]);

  const activeProject = projects.find((p) => p.root === activeRoot);
  const title =
    activeConversation?.summary.title ??
    (activeConversationId ? "Conversation" : activeProject?.name ?? "Ufuk");

  const doLogout = async (): Promise<void> => {
    setLoggingOut(true);
    try {
      await logout();
    } finally {
      setLoggingOut(false);
    }
  };

  const lastAssistant = [...(activeConversation?.messages ?? [])]
    .reverse()
    .find((m) => m.role === "assistant" && m.content);
  const copyLast = (): void => {
    if (!lastAssistant || lastAssistant.role !== "assistant") return;
    void navigator.clipboard
      .writeText(lastAssistant.content ?? "")
      .then(() => {
        setCopied(true);
        if (copyTimer.current) clearTimeout(copyTimer.current);
        copyTimer.current = setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => {
        // clipboard unavailable — ignore
      });
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
          {turn?.running && (
            <span className="animate-pulse text-[10px] text-sky-400">
              working…
            </span>
          )}
          <div className="ml-auto flex items-center gap-2 text-xs">
            <CreditIndicator />
            {lastAssistant && (
              <button
                type="button"
                onClick={copyLast}
                className="rounded border border-neutral-700 px-2 py-1 text-neutral-400 hover:bg-neutral-800"
                title="Copy last reply"
              >
                {copied ? "✓ copied" : "⧉ copy"}
              </button>
            )}
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
        {activeConversation || activeConversationId ? (
          <Transcript
            messages={activeConversation?.messages ?? []}
            liveTurn={turn}
          />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-sky-500 to-indigo-600 text-2xl font-bold text-white shadow-lg">
              U
            </div>
            <h2 className="text-lg font-semibold">Ufuk</h2>
            <p className="max-w-sm text-sm text-neutral-500">
              {activeRoot
                ? "Pick a conversation on the left, or start a new one (Ctrl+N)."
                : "Add a project folder to begin — pick any local folder containing your code."}
            </p>
          </div>
        )}

        {/* composer */}
        {activeRoot && activeConversationId ? (
          <Composer
            root={activeRoot}
            conversationId={activeConversationId}
            onTurnStarted={() => {
              /* the transcript re-renders from store updates */
            }}
          />
        ) : (
          <footer className="shrink-0 border-t border-neutral-800 p-3">
            <div className="mx-auto max-w-3xl text-center text-xs text-neutral-600">
              Select or create a conversation to start chatting.
            </div>
          </footer>
        )}
      </div>

      {/* right panel: changed files + checkpoints (M7) */}
      {activeProject && (
        <ChangesPanel
          project={activeProject}
          conversationId={activeConversationId}
          liveSteps={turn?.steps ?? []}
          onConversationDeleted={() => void reloadActive()}
        />
      )}

      {/* approval modal (M7) */}
      {activeRoot && activeConversationId && (
        <ApprovalModal
          conversationId={activeConversationId}
          workspaceRoot={activeRoot}
          modelReason={turn?.text ?? ""}
        />
      )}
    </div>
  );
}
