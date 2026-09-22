/**
 * M3 skeleton shell: proves the full stack (window -> preload -> IPC ->
 * main -> settings/session) works and carries the security baseline.
 * Login/settings/privacy UIs land in Milestone 4.
 */
import { useEffect, useState } from "react";
import { useAppStore } from "./stores/app";
import { api } from "./ipc/client";

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
  const { ready, settings, session, init, patchSettings } = useAppStore();

  useEffect(() => {
    void init();
  }, [init]);

  if (!ready || !settings) {
    return (
      <div className="flex h-full items-center justify-center bg-neutral-950 text-neutral-400">
        <div className="animate-pulse text-lg">Ufuk başlatılıyor…</div>
      </div>
    );
  }

  const dark = settings.theme === "dark";

  return (
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
              yerel kodlama ajanı — iskelet (M3)
            </p>
          </div>
        </div>

        <div className="w-full max-w-md rounded-xl border border-neutral-800 bg-neutral-900/60 p-5 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-neutral-400">Arka uç</span>
            <code className="rounded bg-neutral-800 px-2 py-0.5 text-xs">
              {settings.backendUrl}
            </code>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <span className="text-neutral-400">Oturum</span>
            <span>{session ? session.email : "giriş yapılmadı"}</span>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <span className="text-neutral-400">Varsayılan tier</span>
            <span>{settings.defaultTier}</span>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <span className="text-neutral-400">Tema</span>
            <button
              type="button"
              onClick={() =>
                void patchSettings({ theme: dark ? "light" : "dark" })
              }
              className="rounded-md border border-neutral-700 px-3 py-1 text-xs hover:bg-neutral-800"
            >
              {dark ? "açık temaya geç" : "koyu temaya geç"}
            </button>
          </div>
        </div>

        <Version />
      </div>
    </div>
  );
}
