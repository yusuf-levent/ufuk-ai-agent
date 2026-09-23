/**
 * Nav rework — MainShell wiring: chat mode drives the composer on the
 * chat sentinel root, projects mode keeps the project flow, and the
 * mode switch never loses the active conversation state.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { installBridge, defaultSettings } from "./helpers/mock-bridge";
import { MainShell } from "../../src/screens/MainShell";
import { useAppStore } from "../../src/stores/app";
import { useProjectsStore } from "../../src/stores/projects";
import { useChatStore } from "../../src/stores/chat";
import type { ConversationSummary, ProjectInfo } from "@shared/ipc";

(globalThis as Record<string, unknown>)["IS_REACT_ACT_ENVIRONMENT"] = true;

let container: HTMLDivElement;
let root: Root | null = null;
let invoke: ReturnType<typeof vi.fn>;

const chatConversation: ConversationSummary = {
  id: "ch_1",
  title: "hello",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-02T00:00:00Z",
  model: "fast",
};

const project: ProjectInfo = {
  root: "C:\\code\\app",
  name: "app",
  addedAt: "2026-01-01T00:00:00Z",
  lastOpenedAt: "2026-01-02T00:00:00Z",
  isGitRepo: true,
};

const projectConversation: ConversationSummary = {
  id: "c_1",
  title: "fix the test",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-02T00:00:00Z",
  model: "fast",
};

const render = async (): Promise<void> => {
  root = createRoot(container);
  await act(async () => {
    root?.render(<MainShell onOpenSettings={() => {}} />);
  });
};

const type = async (el: Element | null, value: string): Promise<void> => {
  if (!el) return;
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  await act(async () => {
    setter?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
};

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  const bridge = installBridge({
    "conversations:list": (payload) => ({
      ok: true,
      value:
        (payload as { root: string }).root === "ufuk:chat"
          ? [chatConversation]
          : [projectConversation],
    }),
    "conversations:load": (payload) => ({
      ok: true,
      value: {
        summary:
          (payload as { id: string }).id === "ch_1"
            ? chatConversation
            : projectConversation,
        messages: [{ role: "user", content: "hi" }],
      },
    }),
  });
  invoke = bridge.invoke;
  useChatStore.setState({ turns: {}, lastMessage: {} });
  useAppStore.setState({
    ready: true,
    sessionChecked: true,
    settings: { ...defaultSettings, privacyAcknowledged: true },
    mode: "chat",
    session: {
      userId: "u1",
      email: "u@example.com",
      displayName: null,
      usingPlainTokenStore: false,
    },
  });
  useProjectsStore.setState({
    projects: [project],
    activeRoot: "C:\\code\\app",
    conversations: [projectConversation],
    activeConversationId: "c_1",
    activeConversation: {
      summary: projectConversation,
      messages: [{ role: "user", content: "hi" }],
    },
    chatConversations: [chatConversation],
    activeChatConversationId: "ch_1",
    activeChatConversation: {
      summary: chatConversation,
      messages: [{ role: "user", content: "hi" }],
    },
    error: null,
  });
});

afterEach(() => {
  if (root) {
    act(() => root?.unmount());
    root = null;
  }
  container.remove();
  useAppStore.setState({ mode: "chat", session: null });
  useChatStore.setState({ turns: {}, lastMessage: {} });
  useProjectsStore.setState({
    projects: [],
    activeRoot: null,
    conversations: [],
    activeConversationId: null,
    activeConversation: null,
    chatConversations: [],
    activeChatConversationId: null,
    activeChatConversation: null,
    error: null,
  });
});

describe("MainShell mode wiring", () => {
  it("chat mode: composer sends on the chat sentinel root, no changes panel", async () => {
    await render();
    const textarea = container.querySelector("textarea");
    expect(textarea).toBeTruthy();
    await type(textarea, "hello there");
    await act(async () => {
      textarea?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    });
    const calls = invoke.mock.calls.filter(([c]) => c === "chat:send");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.[1]).toMatchObject({
      root: "ufuk:chat",
      conversationId: "ch_1",
      message: "hello there",
    });
    // the projects right panel (changed files) only exists in projects mode
    expect(container.textContent).not.toContain("Changed files");
    expect(container.textContent).not.toContain("Permission mode");
  });

  it("projects mode: composer uses the project root and shows the changes panel", async () => {
    useAppStore.setState({ mode: "projects" });
    await render();
    const textarea = container.querySelector("textarea");
    expect(textarea).toBeTruthy();
    await type(textarea, "fix it");
    await act(async () => {
      textarea?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    });
    const calls = invoke.mock.calls.filter(([c]) => c === "chat:send");
    expect(calls[0]?.[1]).toMatchObject({
      root: "C:\\code\\app",
      conversationId: "c_1",
    });
    // right panel present in projects mode
    expect(container.textContent).toContain("Changed files");
    expect(container.textContent).toContain("Permission mode");
  });

  it("chat mode with no conversation shows the no-folder-needed welcome", async () => {
    // fresh install: no chats yet — the mount reload must also see none
    installBridge({
      "conversations:list": () => ({ ok: true, value: [] }),
      "conversations:load": () => ({ ok: true, value: null }),
    });
    useProjectsStore.setState({
      activeChatConversationId: null,
      activeChatConversation: null,
      chatConversations: [],
    });
    await render();
    expect(container.textContent).toContain("no project folder needed");
    // no composer until a conversation exists
    expect(container.querySelector("textarea")).toBeFalsy();
  });

  it("switching modes keeps the transcript state of both conversations", async () => {
    useAppStore.setState({ mode: "chat" });
    await render();
    expect(container.textContent).toContain("hello");
    // switch to projects: the project conversation shows
    await act(async () => {
      (
        [...container.querySelectorAll('[role="tab"]')].find(
          (t) => t.textContent === "Projects",
        ) as HTMLElement | undefined
      )?.click();
    });
    expect(useAppStore.getState().mode).toBe("projects");
    expect(container.textContent).toContain("fix the test");
    // back to chat: chat conversation still selected (state kept)
    await act(async () => {
      (
        [...container.querySelectorAll('[role="tab"]')].find(
          (t) => t.textContent === "Chat",
        ) as HTMLElement | undefined
      )?.click();
    });
    expect(useAppStore.getState().mode).toBe("chat");
    expect(container.textContent).toContain("hello");
    expect(useProjectsStore.getState().activeChatConversationId).toBe("ch_1");
    expect(useProjectsStore.getState().activeConversationId).toBe("c_1");
  });
});
