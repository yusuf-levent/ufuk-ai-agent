/** App state (Zustand): settings + session, loaded through the IPC bridge. */
import { create } from "zustand";
import { api } from "../ipc/client";
import type { SessionInfo, Settings } from "@shared/ipc";

export interface AppStore {
  ready: boolean;
  settings: Settings | null;
  session: SessionInfo | null;
  sessionChecked: boolean;
  init: () => Promise<void>;
  refreshSession: () => Promise<void>;
  patchSettings: (patch: Partial<Settings>) => Promise<void>;
  setSession: (s: SessionInfo | null) => void;
}

export const useAppStore = create<AppStore>((set, get) => ({
  ready: false,
  settings: null,
  session: null,
  sessionChecked: false,
  init: async () => {
    if (get().ready) return;
    const settings = await api.getSettings();
    set({ settings, ready: true });
    document.documentElement.classList.toggle(
      "dark",
      settings.theme === "dark",
    );
    await get().refreshSession();
  },
  refreshSession: async () => {
    try {
      const session = await api.session();
      set({ session, sessionChecked: true });
    } catch {
      set({ session: null, sessionChecked: true });
    }
  },
  patchSettings: async (patch) => {
    const settings = await api.setSettings(patch);
    set({ settings });
    document.documentElement.classList.toggle(
      "dark",
      settings.theme === "dark",
    );
  },
  setSession: (session) => set({ session }),
}));
