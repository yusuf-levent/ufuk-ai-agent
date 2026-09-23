/**
 * Sidebar (M5): project list with git warning, conversation list with
 * rename/delete, selection wiring through the mocked bridge.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { installBridge } from "./helpers/mock-bridge";
import { Sidebar } from "../../src/components/Sidebar";
import { useProjectsStore } from "../../src/stores/projects";
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
    root?.render(<Sidebar />);
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
  // seed the store directly (load wiring is covered by e2e)
  useProjectsStore.setState({
    projects: projectsList,
    activeRoot: null,
    conversations: [],
    activeConversationId: null,
    activeConversation: null,
    error: null,
  });
});

afterEach(() => {
  if (root) {
    act(() => root?.unmount());
    root = null;
  }
  container.remove();
  useProjectsStore.setState({
    projects: [],
    activeRoot: null,
    conversations: [],
    activeConversationId: null,
    activeConversation: null,
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
