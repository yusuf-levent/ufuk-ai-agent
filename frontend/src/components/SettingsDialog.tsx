/**
 * Advanced settings (tabbed): General (theme, default tier from the live
 * catalog, permission mode, Enter-to-send), Agent (max steps per run,
 * empty-response auto-retry), Connection (backend URL + live health
 * check), Data & Privacy (account, user-data folder, log out) and About
 * (app versions). All changes go through the settings:set IPC (validated
 * in main); a backend URL change rebuilds the gateway session there.
 */
import { useEffect, useState } from "react";
import { api } from "../ipc/client";
import type { AppVersionResponse, SettingsPatch } from "@shared/ipc";
import { useAppStore } from "../stores/app";
import { useModelsStore } from "../stores/models";

const TABS = ["general", "agent", "connection", "data", "about"] as const;
type Tab = (typeof TABS)[number];

const TAB_LABELS: Record<Tab, string> = {
  general: "General",
  agent: "Agent",
  connection: "Connection",
  data: "Data & Privacy",
  about: "About",
};

const PERMISSION_MODES = [
  {
    value: "ask",
    label: "Ask every time",
    hint: "Approve every file edit and command before it runs.",
  },
  {
    value: "auto-edits",
    label: "Auto-accept edits inside the workspace",
    hint: "File edits in the project folder run without asking; commands still ask.",
  },
] as const;

/** Small accessible switch used by the boolean settings. */
function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="flex w-full items-center justify-between gap-4 rounded-md px-1 py-1.5 text-left hover:bg-neutral-800/60 disabled:opacity-50"
    >
      <span>
        <span className="block text-sm text-neutral-200">{label}</span>
        {hint && (
          <span className="block text-[11px] text-neutral-500">{hint}</span>
        )}
      </span>
      <span
        className={
          "relative h-5 w-9 shrink-0 rounded-full transition-colors " +
          (checked ? "bg-sky-600" : "bg-neutral-700")
        }
      >
        <span
          className={
            "absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all " +
            (checked ? "left-[18px]" : "left-0.5")
          }
        />
      </span>
    </button>
  );
}

export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const { settings, patchSettings, session, logout } = useAppStore();
  const catalog = useModelsStore((s) => s.catalog);
  const usage = useModelsStore((s) => s.usage);
  const [tab, setTab] = useState<Tab>("general");
  const [backendUrl, setBackendUrl] = useState(settings?.backendUrl ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** Result of the gateway health check (Connection tab). */
  const [health, setHealth] = useState<{ ok: boolean; detail: string } | null>(
    null,
  );
  const [testing, setTesting] = useState(false);
  const [versions, setVersions] = useState<AppVersionResponse | null>(null);
  const [openedFolder, setOpenedFolder] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // version info is fetched lazily, only when the About tab opens
  useEffect(() => {
    if (tab === "about" && versions === null) {
      api
        .getVersion()
        .then((v) => setVersions(v))
        .catch(() => setVersions(null));
    }
  }, [tab, versions]);

  if (!settings) return null;

  const apply = async (patch: SettingsPatch): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await patchSettings(patch);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const saveBackendUrl = async (): Promise<void> => {
    const trimmed = backendUrl.trim().replace(/\/+$/, "");
    if (trimmed === settings.backendUrl) return;
    if (!/^https?:\/\/.+/i.test(trimmed)) {
      setError("Backend URL must start with http:// or https://");
      return;
    }
    await apply({ backendUrl: trimmed });
    setHealth(null); // re-test against the new URL
  };

  const testConnection = async (): Promise<void> => {
    setTesting(true);
    setHealth(null);
    try {
      setHealth(await api.testGateway());
    } catch (err) {
      setHealth({
        ok: false,
        detail: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setTesting(false);
    }
  };

  const openFolder = async (): Promise<void> => {
    setOpenedFolder(await api.openUserData());
  };

  const row = "flex items-center justify-between gap-4 py-2";
  const sectionTitle = "mb-1.5 text-sm font-medium";
  const hint = "text-[11px] text-neutral-500";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-label="Settings"
        className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl border border-neutral-800 bg-neutral-900 text-neutral-100 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-neutral-800 px-5 py-3">
          <h2 className="text-base font-semibold">Settings</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close settings"
            className="rounded-md border border-neutral-700 px-2 py-0.5 text-xs text-neutral-400 hover:bg-neutral-800"
          >
            ✕
          </button>
        </div>

        <div
          role="tablist"
          aria-label="Settings sections"
          className="flex gap-1 border-b border-neutral-800 px-3 pt-2"
        >
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={
                "rounded-t-md px-3 py-1.5 text-xs font-medium " +
                (tab === t
                  ? "bg-neutral-800 text-white"
                  : "text-neutral-400 hover:text-neutral-200")
              }
            >
              {TAB_LABELS[t]}
            </button>
          ))}
        </div>

        <div className="overflow-y-auto px-5 py-4">
          {tab === "general" && (
            <div className="divide-y divide-neutral-800">
              <div className={row}>
                <div>
                  <div className="text-sm">Theme</div>
                  <div className="text-[11px] text-neutral-500">
                    dark is the default
                  </div>
                </div>
                <div className="flex overflow-hidden rounded-md border border-neutral-700 text-xs">
                  {(["dark", "light"] as const).map((t) => (
                    <button
                      key={t}
                      type="button"
                      disabled={busy}
                      onClick={() => void apply({ theme: t })}
                      className={
                        "px-3 py-1 " +
                        (settings.theme === t
                          ? "bg-sky-600 text-white"
                          : "text-neutral-400 hover:bg-neutral-800")
                      }
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>

              <div className="py-3">
                <div className={sectionTitle}>Default tier</div>
                <div className="space-y-1">
                  {(catalog?.allowed ?? []).map((tier) => (
                    <label
                      key={tier.id}
                      className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 text-xs hover:bg-neutral-800/60"
                    >
                      <input
                        type="radio"
                        name="tier"
                        checked={settings.defaultTier === tier.id}
                        disabled={busy}
                        onChange={() => void apply({ defaultTier: tier.id })}
                        className="accent-sky-500"
                      />
                      <span className="font-medium text-neutral-200">
                        {tier.displayName ?? tier.id}
                      </span>
                      <span className="truncate font-mono text-[10px] text-neutral-500">
                        {tier.upstreamModel ?? ""}
                      </span>
                    </label>
                  ))}
                  {(catalog?.locked ?? []).map((tier) => (
                    <label
                      key={tier.id}
                      className="flex cursor-not-allowed items-center gap-2 rounded-md px-1 py-1 text-xs opacity-50"
                      title={tier.reason}
                    >
                      <input type="radio" name="tier" disabled />
                      <span className="font-medium text-neutral-200">
                        🔒 {tier.id}
                      </span>
                      <span className="text-neutral-500">{tier.reason}</span>
                    </label>
                  ))}
                  {!catalog && (
                    <p className={hint}>
                      Tier catalog unavailable (gateway offline or logged out).
                    </p>
                  )}
                </div>
              </div>

              <div className="py-3">
                <div className={sectionTitle}>Permission mode</div>
                <div className="space-y-1">
                  {PERMISSION_MODES.map((mode) => (
                    <label
                      key={mode.value}
                      className="flex cursor-pointer items-start gap-2 rounded-md px-1 py-1 text-xs hover:bg-neutral-800/60"
                    >
                      <input
                        type="radio"
                        name="perm"
                        checked={settings.permissionMode === mode.value}
                        disabled={busy}
                        onChange={() =>
                          void apply({ permissionMode: mode.value })
                        }
                        className="mt-0.5 accent-sky-500"
                      />
                      <span>
                        <span className="block font-medium text-neutral-200">
                          {mode.label}
                        </span>
                        <span className="text-neutral-500">{mode.hint}</span>
                      </span>
                    </label>
                  ))}
                </div>
                <p className={`mt-1 ${hint}`}>
                  There is no &quot;allow everything&quot; mode.
                </p>
              </div>

              <div className="py-3">
                <Toggle
                  checked={settings.enterToSend}
                  onChange={(next) => void apply({ enterToSend: next })}
                  disabled={busy}
                  label="Enter sends the message"
                  hint="Off: Enter inserts a newline, Ctrl+Enter sends."
                />
              </div>
            </div>
          )}

          {tab === "agent" && (
            <div className="divide-y divide-neutral-800">
              <div className="py-3">
                <div className={sectionTitle}>Max steps per run</div>
                <p className={`mb-2 ${hint}`}>
                  How many LLM rounds with tool calls a single reply may take
                  before it stops and summarizes (5–50).
                </p>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={5}
                    max={50}
                    step={1}
                    value={settings.maxSteps}
                    disabled={busy}
                    onChange={(e) =>
                      void apply({ maxSteps: Number(e.target.value) })
                    }
                    className="w-full accent-sky-500"
                    aria-label="Max steps per run"
                  />
                  <span className="w-8 shrink-0 text-center text-sm tabular-nums text-neutral-200">
                    {settings.maxSteps}
                  </span>
                </div>
              </div>
              <div className="py-3">
                <Toggle
                  checked={settings.autoRetryEmptyResponses}
                  onChange={(next) =>
                    void apply({ autoRetryEmptyResponses: next })
                  }
                  disabled={busy}
                  label="Auto-retry empty responses"
                  hint="When the model returns no content at all, send the same message once more automatically."
                />
              </div>
            </div>
          )}

          {tab === "connection" && (
            <div className="divide-y divide-neutral-800">
              <div className="py-3">
                <label className="mb-1 block text-xs font-medium text-neutral-400">
                  Backend URL (gateway)
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={backendUrl}
                    onChange={(e) => setBackendUrl(e.target.value)}
                    placeholder="http://localhost:8000"
                    spellCheck={false}
                    className="w-full rounded-md border border-neutral-700 bg-neutral-950 px-2 py-1.5 font-mono text-xs text-neutral-200 outline-none focus:border-sky-500"
                  />
                  <button
                    type="button"
                    onClick={() => void saveBackendUrl()}
                    disabled={busy}
                    className="shrink-0 rounded-md bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-50"
                  >
                    Save
                  </button>
                </div>
                <p className={`mt-1 ${hint}`}>
                  Changing this rebuilds the gateway session (fresh login state
                  per backend).
                </p>
              </div>
              <div className="py-3">
                <div className={sectionTitle}>Connectivity</div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void testConnection()}
                    disabled={testing}
                    className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
                  >
                    {testing ? "Testing…" : "Test connection"}
                  </button>
                  {health && (
                    <span
                      className={
                        "text-xs " +
                        (health.ok ? "text-green-400" : "text-red-400")
                      }
                      role="status"
                    >
                      {health.ok ? "✓ Connected" : "✕ Failed"} — {health.detail}
                    </span>
                  )}
                </div>
                <p className={`mt-1 ${hint}`}>
                  Checks GET {settings.backendUrl}/health through the main
                  process (the renderer never fetches the gateway directly).
                </p>
              </div>
            </div>
          )}

          {tab === "data" && (
            <div className="divide-y divide-neutral-800">
              <div className="py-3">
                <div className={sectionTitle}>Account</div>
                {session ? (
                  <dl className="space-y-1 text-xs">
                    <div className="flex justify-between gap-4">
                      <dt className="text-neutral-500">Email</dt>
                      <dd className="text-neutral-200">{session.email}</dd>
                    </div>
                    {session.displayName && (
                      <div className="flex justify-between gap-4">
                        <dt className="text-neutral-500">Name</dt>
                        <dd className="text-neutral-200">
                          {session.displayName}
                        </dd>
                      </div>
                    )}
                    {usage && (
                      <div className="flex justify-between gap-4">
                        <dt className="text-neutral-500">Plan</dt>
                        <dd className="text-neutral-200">
                          {usage.planName} — {usage.creditsRemaining}/
                          {usage.creditLimit} credits left
                        </dd>
                      </div>
                    )}
                    <div className="flex justify-between gap-4">
                      <dt className="text-neutral-500">Token storage</dt>
                      <dd className="text-neutral-200">
                        {session.usingPlainTokenStore
                          ? "plain file (OS encryption unavailable)"
                          : "OS-encrypted (safeStorage)"}
                      </dd>
                    </div>
                  </dl>
                ) : (
                  <p className={hint}>Not logged in.</p>
                )}
                <button
                  type="button"
                  onClick={() => void logout()}
                  className="mt-3 rounded-md border border-red-900 bg-red-950/40 px-3 py-1.5 text-xs text-red-300 hover:bg-red-900/40"
                >
                  Log out
                </button>
              </div>
              <div className="py-3">
                <div className={sectionTitle}>App data</div>
                <p className={`mb-2 ${hint}`}>
                  Conversations, checkpoints, settings and encrypted gateway
                  tokens live in the Ufuk user-data folder.
                </p>
                <button
                  type="button"
                  onClick={() => void openFolder()}
                  className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-200 hover:bg-neutral-800"
                >
                  Open data folder
                </button>
                {openedFolder && (
                  <span className="ml-2 text-xs text-green-400" role="status">
                    ✓ opened
                  </span>
                )}
                <p className={`mt-3 ${hint}`}>
                  Prompts are proxied through your gateway; only usage metadata
                  is stored there. Account deletion is available from the
                  gateway.
                </p>
              </div>
            </div>
          )}

          {tab === "about" && (
            <div className="divide-y divide-neutral-800">
              <div className="py-3">
                <div className={sectionTitle}>Ufuk</div>
                <dl className="space-y-1 text-xs">
                  <div className="flex justify-between gap-4">
                    <dt className="text-neutral-500">App version</dt>
                    <dd className="font-mono text-neutral-200">
                      {versions ? versions.version : "…"}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-neutral-500">Electron</dt>
                    <dd className="font-mono text-neutral-200">
                      {versions ? versions.electron : "…"}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-neutral-500">Node</dt>
                    <dd className="font-mono text-neutral-200">
                      {versions ? versions.node : "…"}
                    </dd>
                  </div>
                </dl>
                <p className={`mt-3 ${hint}`}>
                  A local-first desktop coding agent. The agent runtime
                  (evren-agent) runs in the app&apos;s main process and talks to
                  a self-hosted LLM gateway.
                </p>
              </div>
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="mt-3 rounded-md border border-red-900 bg-red-950/50 px-3 py-2 text-xs text-red-300"
            >
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
