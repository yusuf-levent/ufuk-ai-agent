/**
 * Sidebar (M5 + nav rework): top-level Chat/Projects switcher; project
 * list with git warning, conversation list with rename/delete, selection
 * wiring through the mocked bridge — for BOTH modes.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { installBridge } from "./helpers/mock-bridge";
import { Sidebar } from "../../src/components/Sidebar";
import { useProjectsStore } from "../../src/stores/projects";
import { useAppStore } from "../../src/stores/app";
import type { ConversationSummary, ProjectInfo } from "@shared/ipc";

(globalThis as Record<string, unknown>)["IS_REACT_ACT_ENVIRONMENT"] = true;

let container: HTMLDivElement;
let root: Root | null = null;
let invoke: ReturnType<typeof vi.fn>;

const project = (root: string, name: string, git: boolean): ProjectInfo => ({
  root,
  name,
  addedAt: "2026-01-01T00:00:00Z",
  lastOpenedAt: "2026-01-02T00:00:00Z",
  isGitRepo: git,
});

const conversation = (id: string, title: string): ConversationSummary => ({
  id,
  title,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-02T00:00:00Z",
  model: "fast",
});

const conversationsByRoot: Record<string, ConversationSummary[]> = {};
const projectsList: ProjectInfo[] = [];

const render = async (): Promise<void> => {
  root = createRoot(container);
  await act(async () => {
    root?.render(<Sidebar onOpenSettings={() => {}} />);
  });
};

const clickTitle = async (title: string): Promise<void> => {
  await act(async () => {
    container
      .querySelector(`button[title="${title}"]`)
      ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
};

const clickText = async (text: string): Promise<void> => {
  await act(async () => {
    [...container.querySelectorAll("button")]
      .find((b) => b.textContent?.includes(text))
      ?.click();
  });
};

const clickRole = async (name: string): Promise<void> => {
  await act(async () => {
    [...container.querySelectorAll("button")]
      .find((b) => b.textContent?.trim() === name)
      ?.click();
  });
};

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  const bridge = installBridge({
    "projects:list": () => ({ ok: true, value: projectsList }),
    "conversations:list": (payload) => ({
      ok: true,
      value: conversationsByRoot[(payload as { root: string }).root] ?? [],
    }),
  });
  invoke = bridge.invoke;
  // seed the store directly (load wiring is covered by e2e); the sidebar
  // tests for the projects section run in projects mode
  useAppStore.setState({ mode: "projects" });
  useProjectsStore.setState({
    projects: projectsList,
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

afterEach(() => {
  if (root) {
    act(() => root?.unmount());
    root = null;
  }
  container.remove();
  useAppStore.setState({ mode: "chat" });
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

describe("Sidebar", () => {
  it("renders projects with a warning marker for non-git folders", async () => {
    projectsList.push(project("C:\\code\\app", "app", false));
    projectsList.push(project("C:\\code\\lib", "lib", true));
    useProjectsStore.setState({ projects: [...projectsList] });
    await render();
    expect(container.textContent).toContain("app");
    expect(container.textContent).toContain("lib");
    const warn = container.querySelector("[title='Not a git repository']");
    expect(warn).toBeTruthy();
  });

  it("selecting a project loads its conversations through the bridge", async () => {
    projectsList.push(project("C:\\code\\app", "app", true));
    conversationsByRoot["C:\\code\\app"] = [
      conversation("c_1", "fix the test"),
      conversation("c_2", "refactor auth"),
    ];
    useProjectsStore.setState({ projects: [...projectsList] });
    await render();
    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((b) => b.textContent?.includes("app"))
        ?.click();
    });
    expect(
      invoke.mock.calls.filter(([c]) => c === "conversations:list"),
    ).toHaveLength(1);
    expect(container.textContent).toContain("fix the test");
    expect(container.textContent).toContain("refactor auth");
  });

  it("renaming a conversation calls the rename channel with the trimmed title", async () => {
    projectsList.push(project("C:\\code\\app", "app", true));
    useProjectsStore.setState({
      projects: [...projectsList],
      activeRoot: "C:\\code\\app",
      conversations: [conversation("c_1", "fix the test")],
    });
    await render();
    await clickTitle("Rename");
    const input = container.querySelector("input");
    expect(input).toBeTruthy();
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(input, "  new title  ");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      input?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    });
    const calls = invoke.mock.calls.filter(
      ([c]) => c === "conversations:rename",
    );
    expect(calls).toHaveLength(1);
    expect(calls[0]?.[1]).toEqual({
      root: "C:\\code\\app",
      id: "c_1",
      title: "new title",
    });
  });

  it("deleting a conversation asks for confirmation first", async () => {
    projectsList.push(project("C:\\code\\app", "app", true));
    useProjectsStore.setState({
      projects: [...projectsList],
      activeRoot: "C:\\code\\app",
      conversations: [conversation("c_1", "fix the test")],
    });
    await render();
    // first click arms confirmation, nothing sent yet
    await clickTitle("Delete conversation");
    expect(
      invoke.mock.calls.filter(([c]) => c === "conversations:delete"),
    ).toHaveLength(0);
    await clickText("delete");
    const calls = invoke.mock.calls.filter(
      ([c]) => c === "conversations:delete",
    );
    expect(calls).toHaveLength(1);
    expect(calls[0]?.[1]).toEqual({ root: "C:\\code\\app", id: "c_1" });
  });

  it("opening a conversation loads it through the bridge", async () => {
    projectsList.push(project("C:\\code\\app", "app", true));
    useProjectsStore.setState({
      projects: [...projectsList],
      activeRoot: "C:\\code\\app",
      conversations: [conversation("c_1", "fix the test")],
    });
    await render();
    await clickText("fix the test");
    const calls = invoke.mock.calls.filter(([c]) => c === "conversations:load");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.[1]).toEqual({ root: "C:\\code\\app", id: "c_1" });
  });
});

describe("Sidebar mode switcher (nav rework)", () => {
  it("bottom-left account area shows the user and opens settings via the gear", async () => {
    useAppStore.setState({
      mode: "chat",
      session: {
        userId: "u1",
        email: "ada@example.com",
        displayName: null,
        usingPlainTokenStore: false,
      },
    });
    let settingsOpened = 0;
    root = createRoot(container);
    await act(async () => {
      root?.render(<Sidebar onOpenSettings={() => (settingsOpened += 1)} />);
    });
    // avatar initial + email in the account row
    expect(container.textContent).toContain("ada@example.com");
    const avatar = container.querySelector(".bg-gradient-to-br");
    expect(avatar?.textContent?.trim()).toBe("A");
    // the gear opens settings (the only ⚙ entry point in the shell)
    const gear = container.querySelector(
      'button[aria-label="Settings"]',
    ) as HTMLButtonElement | null;
    expect(gear).toBeTruthy();
    await act(async () => {
      gear?.click();
    });
    expect(settingsOpened).toBe(1);
    useAppStore.setState({ session: null });
  });

  it("prefers the display name over the email in the account area", async () => {
    useAppStore.setState({
      mode: "chat",
      session: {
        userId: "u1",
        email: "ada@example.com",
        displayName: "Ada Lovelace",
        usingPlainTokenStore: false,
      },
    });
    await render();
    expect(container.textContent).toContain("Ada Lovelace");
    useAppStore.setState({ session: null });
  });

  it("renders the Chat/Projects segmented control with the active mode highlighted", async () => {
    useAppStore.setState({ mode: "chat" });
    await render();
    const tabs = [...container.querySelectorAll('[role="tab"]')];
    expect(tabs.map((t) => t.textContent)).toEqual(["Chat", "Projects"]);
    expect(
      tabs.find((t) => t.textContent === "Chat")?.getAttribute("aria-selected"),
    ).toBe("true");
    expect(
      tabs
        .find((t) => t.textContent === "Projects")
        ?.getAttribute("aria-selected"),
    ).toBe("false");
  });

  it("chat mode lists chat conversations and creates new ones on the chat root", async () => {
    useAppStore.setState({ mode: "chat" });
    useProjectsStore.setState({
      chatConversations: [conversation("ch_1", "hello world")],
    });
    await render();
    expect(container.textContent).toContain("hello world");
    // projects section is hidden in chat mode
    expect([
      ...container.querySelectorAll("button[title='Add project folder']"),
    ]).toHaveLength(0);
    // new chat goes through the chat sentinel root
    await clickTitle("New chat");
    const calls = invoke.mock.calls.filter(
      ([c]) => c === "conversations:create",
    );
    expect(calls).toHaveLength(1);
    expect(calls[0]?.[1]).toEqual({ root: "ufuk:chat" });
  });

  it("switching to projects and back keeps both lists (no state loss)", async () => {
    useAppStore.setState({ mode: "chat" });
    useProjectsStore.setState({
      chatConversations: [conversation("ch_1", "chat stays")],
      projects: [project("C:\\code\\app", "app", true)],
      activeRoot: "C:\\code\\app",
      conversations: [conversation("c_1", "project stays")],
    });
    await render();
    expect(container.textContent).toContain("chat stays");

    // switch to projects
    await clickRole("Projects");
    expect(useAppStore.getState().mode).toBe("projects");
    expect(container.textContent).toContain("project stays");
    expect(container.textContent).not.toContain("chat stays");

    // switch back: the chat list is still there (kept in memory)
    await clickRole("Chat");
    expect(useAppStore.getState().mode).toBe("chat");
    expect(container.textContent).toContain("chat stays");
    expect(container.textContent).not.toContain("project stays");
  });

  it("chat conversations open and rename through the chat root", async () => {
    useAppStore.setState({ mode: "chat" });
    useProjectsStore.setState({
      chatConversations: [conversation("ch_1", "rename me")],
    });
    await render();
    await clickText("rename me");
    const openCalls = invoke.mock.calls.filter(
      ([c]) => c === "conversations:load",
    );
    expect(openCalls).toHaveLength(1);
    expect(openCalls[0]?.[1]).toEqual({ root: "ufuk:chat", id: "ch_1" });

    await clickTitle("Rename");
    const input = container.querySelector("input");
    expect(input).toBeTruthy();
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(input, "renamed chat");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      input?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    });
    const renameCalls = invoke.mock.calls.filter(
      ([c]) => c === "conversations:rename",
    );
    expect(renameCalls).toHaveLength(1);
    expect(renameCalls[0]?.[1]).toEqual({
      root: "ufuk:chat",
      id: "ch_1",
      title: "renamed chat",
    });
  });
});
