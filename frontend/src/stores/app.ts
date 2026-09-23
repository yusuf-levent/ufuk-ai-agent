/** App state (Zustand): settings + session + top-level mode, loaded through the IPC bridge. */
import { create } from "zustand";
import { api } from "../ipc/client";
import type {
  LoginRequest,
  RegisterRequest,
  SessionInfo,
  Settings,
} from "@shared/ipc";

export type AppMode = "chat" | "projects";

export interface AppStore {
  ready: boolean;
  settings: Settings | null;
  session: SessionInfo | null;
  sessionChecked: boolean;
  /** Why a session restore attempt ended logged-out (expired/unreachable). */
  sessionExpired: boolean;
  sessionUnreachable: boolean;
  /** Top-level mode: chat (tool-less) vs projects (folder + agent flow). */
  mode: AppMode;
  init: () => Promise<void>;
  refreshSession: () => Promise<void>;
  patchSettings: (patch: Partial<Settings>) => Promise<void>;
  setSession: (s: SessionInfo | null) => void;
  setMode: (mode: AppMode) => Promise<void>;
  login: (req: LoginRequest) => Promise<void>;
  register: (req: RegisterRequest) => Promise<void>;
  logout: () => Promise<void>;
}

export const useAppStore = create<AppStore>((set, get) => ({
  ready: false,
  settings: null,
  session: null,
  sessionChecked: false,
  sessionExpired: false,
  sessionUnreachable: false,
  mode: "chat",
  init: async () => {
    if (get().ready) return;
    const settings = await api.getSettings();
    set({
      settings,
      ready: true,
      mode: settings.activeMode ?? "chat",
    });
    document.documentElement.classList.toggle(
      "dark",
      settings.theme === "dark",
    );
    await get().refreshSession();
  },
  refreshSession: async () => {
    set({ sessionExpired: false, sessionUnreachable: false });
    try {
      const snapshot = await api.session();
      set({
        session: snapshot.info,
        sessionChecked: true,
        sessionExpired: snapshot.reason === "expired",
        sessionUnreachable: snapshot.reason === "unreachable",
      });
    } catch {
      set({
        session: null,
        sessionChecked: true,
        sessionExpired: false,
        sessionUnreachable: false,
      });
    }
  },
  patchSettings: async (patch) => {
    const settings = await api.setSettings(patch);
    set({ settings, mode: settings.activeMode ?? get().mode });
    document.documentElement.classList.toggle(
      "dark",
      settings.theme === "dark",
    );
  },
  setSession: (session) => set({ session }),
  setMode: async (mode) => {
    // optimistic: both mode slices stay alive in the stores, so switching
    // never loses state; the choice persists across restarts via settings
    set({ mode });
    try {
      await get().patchSettings({ activeMode: mode });
    } catch {
      // keep the in-memory switch even if persisting fails
    }
  },
  login: async (req) => {
    await api.login(req);
    set({ sessionExpired: false });
    await get().refreshSession();
  },
  register: async (req) => {
    await api.register(req);
    set({ sessionExpired: false });
    await get().refreshSession();
  },
  logout: async () => {
    try {
      await api.logout();
    } catch {
      // the main process clears local tokens first; a failed revoke call
      // must not keep the (now stale) session in the renderer
    }
    set({ session: null, sessionExpired: false });
  },
}));
