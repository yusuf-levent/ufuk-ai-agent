/**
 * ChangesPanel (M7): permission mode switch, changed files with diff,
 * checkpoint history with undo/revert — through the mocked bridge.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { installBridge, defaultProjects } from "./helpers/mock-bridge";
import { ChangesPanel } from "../../src/components/ChangesPanel";
import type { ProjectInfo } from "@shared/ipc";

(globalThis as Record<string, unknown>)["IS_REACT_ACT_ENVIRONMENT"] = true;

let container: HTMLDivElement;
let root: Root | null = null;
let invoke: ReturnType<typeof vi.fn>;

const project: ProjectInfo = {
  ...defaultProjects[0]!,
  permissionMode: "ask",
};

const render = async (): Promise<void> => {
  root = createRoot(container);
  await act(async () => {
    root?.render(
      <ChangesPanel
        project={project}
        conversationId="c_1"
        liveSteps={[]}
        turnActive={false}
      />,
    );
  });
};

const findButton = (text: string): HTMLButtonElement | undefined =>
  [...container.querySelectorAll("button")].find((b) =>
    b.textContent?.includes(text),
  ) as HTMLButtonElement | undefined;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  const bridge = installBridge({
    "conversations:changed-files": () => ({
      ok: true,
      value: [
        { path: "src/a.ts", tool: "edit_file", ok: true, at: "" },
        { path: "src/b.ts", tool: "write_file", ok: true, at: "" },
      ],
    }),
    "checkpoints:list": () => ({
      ok: true,
      value: [
        {
          id: "cp1",
          createdAt: "2026-01-02T00:00:00Z",
          tool: "edit_file",
          files: [{ path: "src/a.ts", existedBefore: true }],
        },
      ],
    }),
  });
  invoke = bridge.invoke;
});

afterEach(() => {
  if (root) {
    act(() => root?.unmount());
    root = null;
  }
  container.remove();
});

describe("ChangesPanel", () => {
  it("lists the conversation's changed files and opens the diff on click", async () => {
    await render();
    expect(container.textContent).toContain("src/a.ts");
    expect(container.textContent).toContain("src/b.ts");
    await act(async () => {
      findButton("src/a.ts")?.click();
    });
    const calls = invoke.mock.calls.filter(([c]) => c === "checkpoints:diff");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.[1]).toMatchObject({
      root: project.root,
      path: "src/a.ts",
    });
    // diff viewer renders (inline mode) with add/del lines
    expect(container.textContent).toContain("−old");
    expect(container.textContent).toContain("+new");
    // side-by-side toggle
    await act(async () => {
      findButton("side-by-side")?.click();
    });
    expect(container.querySelector("table")).toBeTruthy();
  });

  it("switches the per-project permission mode (no allow-everything)", async () => {
    await render();
    const radios = [
      ...container.querySelectorAll('input[name="proj-mode"]'),
    ] as HTMLInputElement[];
    const labels = radios.map((r) => r.closest("label")?.textContent ?? "");
    expect(labels.some((t) => t.includes("Ask every time"))).toBe(true);
    expect(
      labels.some((t) => t.includes("Auto-accept edits inside the workspace")),
    ).toBe(true);
    expect(labels.some((t) => /allow\s+everything/i.test(t))).toBe(false);

    const auto = radios.find((r) =>
      r.closest("label")?.textContent.includes("Auto-accept"),
    );
    await act(async () => {
      auto?.click();
    });
    const calls = invoke.mock.calls.filter(
      ([c]) => c === "projects:set-permission-mode",
    );
    expect(calls.at(-1)?.[1]).toEqual({
      root: project.root,
      mode: "auto-edits",
    });
    expect(container.textContent).toContain("Commands still ask");
  });

  it("history tab: undo calls the bridge and reports the result", async () => {
    await render();
    await act(async () => {
      findButton("History")?.click();
    });
    expect(container.textContent).toContain("edit_file");
    await act(async () => {
      findButton("Undo last change")?.click();
    });
    const calls = invoke.mock.calls.filter(([c]) => c === "checkpoints:undo");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.[1]).toEqual({ root: project.root });
  });

  it("history tab: revert asks for confirmation first", async () => {
    await render();
    await act(async () => {
      findButton("History")?.click();
    });
    await act(async () => {
      findButton("revert to checkpoint")?.click();
    });
    expect(
      invoke.mock.calls.filter(([c]) => c === "checkpoints:revert"),
    ).toHaveLength(0);
    await act(async () => {
      findButton("revert here")?.click();
    });
    const calls = invoke.mock.calls.filter(([c]) => c === "checkpoints:revert");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.[1]).toEqual({ root: project.root, id: "cp1" });
  });

  it("shows live changes from the current run immediately", async () => {
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ChangesPanel
          project={project}
          conversationId="c_1"
          turnActive={false}
          liveSteps={[
            {
              id: "t9",
              name: "write_file",
              argsSummary: "path: src/live.ts, content: …",
              output: "",
              ok: true,
              durationMs: 5,
              status: "done",
            },
          ]}
        />,
      );
    });
    expect(container.textContent).toContain("src/live.ts");
  });
});
