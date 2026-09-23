/** Projects + conversations state (Zustand), all through the IPC bridge. */
import { create } from "zustand";
import { api } from "../ipc/client";
import { CHAT_ROOT_ID } from "@shared/ipc";
import type {
  ConversationDetail,
  ConversationSummary,
  ProjectInfo,
} from "@shared/ipc";

export interface ProjectsStore {
  projects: ProjectInfo[];
  projectsLoading: boolean;
  activeRoot: string | null;
  conversations: ConversationSummary[];
  conversationsLoading: boolean;
  activeConversationId: string | null;
  activeConversation: ConversationDetail | null;
  /** Chat-mode slice (tool-less conversations, app-owned workspace). */
  chatConversations: ConversationSummary[];
  chatLoading: boolean;
  activeChatConversationId: string | null;
  activeChatConversation: ConversationDetail | null;
  /** Set when the last operation failed (cleared on next action). */
  error: string | null;
  loadProjects: () => Promise<void>;
  addProjectWithPicker: () => Promise<void>;
  removeProject: (root: string) => Promise<void>;
  selectProject: (root: string) => Promise<void>;
  loadConversations: (root: string) => Promise<void>;
  newConversation: () => Promise<void>;
  openConversation: (id: string) => Promise<void>;
  /** Re-fetch the active conversation detail (e.g. after a run finished). */
  reloadActive: () => Promise<void>;
  renameConversation: (id: string, title: string) => Promise<void>;
  deleteConversation: (id: string) => Promise<void>;
  loadChatConversations: () => Promise<void>;
  newChatConversation: () => Promise<void>;
  openChatConversation: (id: string) => Promise<void>;
  reloadActiveChat: () => Promise<void>;
  renameChatConversation: (id: string, title: string) => Promise<void>;
  deleteChatConversation: (id: string) => Promise<void>;
  clearError: () => void;
}

export const useProjectsStore = create<ProjectsStore>((set, get) => ({
  projects: [],
  projectsLoading: false,
  activeRoot: null,
  conversations: [],
  conversationsLoading: false,
  activeConversationId: null,
  activeConversation: null,
  chatConversations: [],
  chatLoading: false,
  activeChatConversationId: null,
  activeChatConversation: null,
  error: null,

  loadProjects: async () => {
    set({ projectsLoading: true });
    try {
      const projects = await api.listProjects();
      set({ projects });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      set({ projectsLoading: false });
    }
  },
  addProjectWithPicker: async () => {
    set({ error: null });
    try {
      const folder = await api.pickFolder();
      if (!folder) return; // cancelled
      await api.addProject(folder);
      await get().loadProjects();
      // select the newly added project (first by lastOpenedAt)
      const next = await api.listProjects();
      const first = next[0];
      if (first) await get().selectProject(first.root);
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  removeProject: async (root) => {
    set({ error: null });
    try {
      await api.removeProject(root);
      const wasActive = get().activeRoot === root;
      await get().loadProjects();
      if (wasActive) {
        set({
          activeRoot: null,
          conversations: [],
          activeConversationId: null,
          activeConversation: null,
        });
      }
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  selectProject: async (root) => {
    set({
      error: null,
      activeRoot: root,
      activeConversationId: null,
      activeConversation: null,
    });
    await get().loadConversations(root);
  },

  loadConversations: async (root) => {
    set({ conversationsLoading: true });
    try {
      const conversations = await api.listConversations(root);
      set({ conversations });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      set({ conversationsLoading: false });
    }
  },

  newConversation: async () => {
    const root = get().activeRoot;
    if (!root) return;
    set({ error: null });
    try {
      const summary = await api.createConversation(root);
      set({
        activeConversationId: summary.id,
        activeConversation: { summary, messages: [] },
        conversations: [summary, ...get().conversations],
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  openConversation: async (id) => {
    const root = get().activeRoot;
    if (!root) return;
    set({ error: null, activeConversationId: id, activeConversation: null });
    try {
      const detail = await api.loadConversation(root, id);
      if (!detail) {
        set({ error: "Conversation not found." });
        return;
      }
      // ignore stale responses after switching conversations mid-flight
      if (get().activeConversationId !== id) return;
      set({ activeConversation: detail });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  reloadActive: async () => {
    const { activeRoot, activeConversationId } = get();
    if (!activeRoot || !activeConversationId) return;
    try {
      const detail = await api.loadConversation(
        activeRoot,
        activeConversationId,
      );
      if (!detail) return;
      if (get().activeConversationId !== activeConversationId) return;
      set({
        activeConversation: detail,
        conversations: refreshSummary(get(), detail),
      });
    } catch {
      // keep the old detail on refresh failure
    }
  },

  renameConversation: async (id, title) => {
    const root = get().activeRoot;
    if (!root) return;
    set({ error: null });
    try {
      const ok = await api.renameConversation(root, id, title.trim());
      if (!ok) {
        set({ error: "Conversation not found." });
        return;
      }
      set({
        conversations: get().conversations.map((c) =>
          c.id === id ? { ...c, title: title.trim() } : c,
        ),
        activeConversation:
          get().activeConversation?.summary.id === id
            ? {
                ...get().activeConversation!,
                summary: {
                  ...get().activeConversation!.summary,
                  title: title.trim(),
                },
              }
            : get().activeConversation,
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  deleteConversation: async (id) => {
    const root = get().activeRoot;
    if (!root) return;
    set({ error: null });
    try {
      const ok = await api.deleteConversation(root, id);
      if (!ok) {
        set({ error: "Conversation not found." });
        return;
      }
      set({
        conversations: get().conversations.filter((c) => c.id !== id),
        ...(get().activeConversationId === id
          ? { activeConversationId: null, activeConversation: null }
          : {}),
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  // -------------------------------------------------------------------------
  // chat mode (tool-less conversations on the app-owned workspace)
  // -------------------------------------------------------------------------

  loadChatConversations: async () => {
    set({ chatLoading: true });
    try {
      const conversations = await api.listConversations(CHAT_ROOT_ID);
      set({ chatConversations: conversations });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      set({ chatLoading: false });
    }
  },

  newChatConversation: async () => {
    set({ error: null });
    try {
      const summary = await api.createConversation(CHAT_ROOT_ID);
      set({
        activeChatConversationId: summary.id,
        activeChatConversation: { summary, messages: [] },
        chatConversations: [summary, ...get().chatConversations],
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  openChatConversation: async (id) => {
    set({
      error: null,
      activeChatConversationId: id,
      activeChatConversation: null,
    });
    try {
      const detail = await api.loadConversation(CHAT_ROOT_ID, id);
      if (!detail) {
        set({ error: "Conversation not found." });
        return;
      }
      // ignore stale responses after switching conversations mid-flight
      if (get().activeChatConversationId !== id) return;
      set({ activeChatConversation: detail });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  reloadActiveChat: async () => {
    const { activeChatConversationId } = get();
    if (!activeChatConversationId) return;
    try {
      const detail = await api.loadConversation(
        CHAT_ROOT_ID,
        activeChatConversationId,
      );
      if (!detail) return;
      if (get().activeChatConversationId !== activeChatConversationId) return;
      set({
        activeChatConversation: detail,
        chatConversations: refreshChatSummary(get(), detail),
      });
    } catch {
      // keep the old detail on refresh failure
    }
  },

  renameChatConversation: async (id, title) => {
    set({ error: null });
    try {
      const ok = await api.renameConversation(CHAT_ROOT_ID, id, title.trim());
      if (!ok) {
        set({ error: "Conversation not found." });
        return;
      }
      set({
        chatConversations: get().chatConversations.map((c) =>
          c.id === id ? { ...c, title: title.trim() } : c,
        ),
        activeChatConversation:
          get().activeChatConversation?.summary.id === id
            ? {
                ...get().activeChatConversation!,
                summary: {
                  ...get().activeChatConversation!.summary,
                  title: title.trim(),
                },
              }
            : get().activeChatConversation,
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  deleteChatConversation: async (id) => {
    set({ error: null });
    try {
      const ok = await api.deleteConversation(CHAT_ROOT_ID, id);
      if (!ok) {
        set({ error: "Conversation not found." });
        return;
      }
      set({
        chatConversations: get().chatConversations.filter((c) => c.id !== id),
        ...(get().activeChatConversationId === id
          ? { activeChatConversationId: null, activeChatConversation: null }
          : {}),
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) });
    }
  },

  clearError: () => set({ error: null }),
}));

/** Keep the chat sidebar summary in sync with a reloaded conversation detail. */
function refreshChatSummary(
  state: ProjectsStore,
  detail: { summary: ConversationSummary; messages: unknown[] },
): ConversationSummary[] {
  return state.chatConversations.some((c) => c.id === detail.summary.id)
    ? state.chatConversations.map((c) =>
        c.id === detail.summary.id ? detail.summary : c,
      )
    : [detail.summary, ...state.chatConversations];
}

/** Keep the sidebar summary in sync with a reloaded conversation detail. */
function refreshSummary(
  state: ProjectsStore,
  detail: { summary: ConversationSummary; messages: unknown[] },
): ConversationSummary[] {
  return state.conversations.some((c) => c.id === detail.summary.id)
    ? state.conversations.map((c) =>
        c.id === detail.summary.id ? detail.summary : c,
      )
    : [detail.summary, ...state.conversations];
}
