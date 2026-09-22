/**
 * App shell routing (M4): loading → privacy gate (once) → login → main.
 * The main shell keeps the M3 skeleton cards until M5 brings projects and
 * conversations. Auth state lives in the Zustand store; every screen
 * renders friendly, coded errors from the main process.
 */
import { useEffect, useState } from "react";
import { useAppStore } from "./stores/app";
import { api } from "./ipc/client";
import { LoginScreen } from "./screens/LoginScreen";
import { PrivacyGate } from "./screens/PrivacyGate";
import { SettingsDialog } from "./components/SettingsDialog";

function Version() {
  const [version, setVersion] = useState<string>("…");
  useEffect(() => {
    api
      .getVersion()
      .then((v) => setVersion(`v${v.version} · Electron ${v.electron}`))
      .catch(() => setVersion("version unavailable"));
  }, []);
  return <span className="text-neutral-500">{version}</span>;
}

export function App() {
  const { ready, settings, session, sessionChecked, init, logout } =
    useAppStore();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    void init();
  }, [init]);

  if (!ready || !settings || !sessionChecked) {
    return (
      <div className="flex h-full items-center justify-center bg-neutral-950 text-neutral-400">
        <div className="animate-pulse text-lg">Ufuk başlatılıyor…</div>
      </div>
    );
  }

  const doLogout = async (): Promise<void> => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await logout();
    } finally {
      setLoggingOut(false);
    }
  };

  let screen: React.ReactNode;
  if (!settings.privacyAcknowledged) {
    screen = <PrivacyGate onOpenSettings={() => setSettingsOpen(true)} />;
  } else if (!session) {
    screen = <LoginScreen onOpenSettings={() => setSettingsOpen(true)} />;
  } else {
    const dark = settings.theme === "dark";
    screen = (
      <div
        className={
          dark
            ? "h-full bg-neutral-950 text-neutral-100"
            : "h-full bg-white text-neutral-900"
        }
      >
        <div className="flex h-full flex-col items-center justify-center gap-6 p-10">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-sky-500 to-indigo-600 text-2xl font-bold text-white shadow-lg">
              U
            </div>
            <div>
              <h1 className="text-3xl font-semibold tracking-tight">Ufuk</h1>
              <p className="text-sm text-neutral-500">
                yerel kodlama ajanı — oturum açık
              </p>
            </div>
          </div>

          <div className="w-full max-w-md rounded-xl border border-neutral-800 bg-neutral-900/60 p-5 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-neutral-400">Signed in</span>
              <span>{session.email}</span>
            </div>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-neutral-400">Arka uç</span>
              <code className="rounded bg-neutral-800 px-2 py-0.5 text-xs">
                {settings.backendUrl}
              </code>
            </div>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-neutral-400">Varsayılan tier</span>
              <span>{settings.defaultTier}</span>
            </div>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-neutral-400">İzin modu</span>
              <span>
                {settings.permissionMode === "ask"
                  ? "her seferinde sor"
                  : "workspace içi düzenlemeler otomatik"}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setSettingsOpen(true)}
              className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs hover:bg-neutral-800"
            >
              ⚙ Settings
            </button>
            <button
              type="button"
              onClick={() => void doLogout()}
              disabled={loggingOut}
              className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-red-300 hover:bg-neutral-800 disabled:opacity-50"
            >
              {loggingOut ? "…" : "Log out"}
            </button>
          </div>

          <Version />
        </div>
      </div>
    );
  }

  return (
    <>
      {screen}
      {settingsOpen && (
        <SettingsDialog onClose={() => setSettingsOpen(false)} />
      )}
    </>
  );
}
