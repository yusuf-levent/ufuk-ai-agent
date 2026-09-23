/**
 * App shell routing (M4+M5): loading → privacy gate (once) → login → main
 * shell (projects sidebar + chat area). Auth state lives in the Zustand
 * store; every screen renders friendly, coded errors from the main process.
 */
import { useEffect, useState } from "react";
import { useAppStore } from "./stores/app";
import { LoginScreen } from "./screens/LoginScreen";
import { PrivacyGate } from "./screens/PrivacyGate";
import { MainShell } from "./screens/MainShell";
import { SettingsDialog } from "./components/SettingsDialog";

export function App() {
  const { ready, settings, session, sessionChecked, init } = useAppStore();
  const [settingsOpen, setSettingsOpen] = useState(false);

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

  let screen: React.ReactNode;
  if (!settings.privacyAcknowledged) {
    screen = <PrivacyGate onOpenSettings={() => setSettingsOpen(true)} />;
  } else if (!session) {
    screen = <LoginScreen onOpenSettings={() => setSettingsOpen(true)} />;
  } else {
    screen = <MainShell onOpenSettings={() => setSettingsOpen(true)} />;
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
