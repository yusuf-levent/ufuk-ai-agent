/**
 * M6 chat: the chat store folds agent events into live turns; the
 * transcript renders streaming text, reasoning (collapsed), the tool-step
 * timeline (name, args, result, duration) and the usage bar; the approval
 * bar answers approval_requests through the bridge; the composer sends on
 * Enter (not Shift+Enter).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { installBridge } from "./helpers/mock-bridge";
import { useChatStore } from "../../src/stores/chat";
import {
  Transcript,
  LiveTurnView,
  historyCoversRun,
  historyCoversAssistant,
} from "../../src/components/Transcript";
import { ApprovalModal } from "../../src/components/ApprovalModal";
import { Composer } from "../../src/components/Composer";

(globalThis as Record<string, unknown>)["IS_REACT_ACT_ENVIRONMENT"] = true;

let container: HTMLDivElement;
let root: Root | null = null;
let invoke: ReturnType<typeof vi.fn>;

const render = async (el: React.ReactNode): Promise<void> => {
  root = createRoot(container);
  await act(async () => {
    root?.render(el);
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

const key = async (
  el: Element,
  k: string,
  mods: Record<string, boolean> = {},
): Promise<void> => {
  await act(async () => {
    el.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: k,
        bubbles: true,
        shiftKey: mods.shift ?? false,
        ctrlKey: mods.ctrl ?? false,
      }),
    );
  });
};

const emit = (event: unknown, errorInfo?: unknown): void => {
  act(() => {
    useChatStore.getState().handleEvent({
      conversationId: "c_1",
      event,
      ...(errorInfo ? { errorInfo } : {}),
    } as never);
  });
};

/** Push a run-queue lifecycle payload (queued/started/cleared). */
const emitQueue = (payload: Record<string, unknown>): void => {
  act(() => {
    useChatStore.getState().handleEvent({
      conversationId: "c_1",
      ...payload,
    } as never);
  });
};

const setProjectsRoot = (root: string): void => {
  // Composer takes root as a prop; nothing global needed
  void root;
};

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  const bridge = installBridge();
  invoke = bridge.invoke;
  useChatStore.setState({
    turns: {},
    lastMessage: {},
    pending: {},
    drafts: {},
  });
});

afterEach(() => {
  if (root) {
    act(() => root?.unmount());
    root = null;
  }
  container.remove();
  useChatStore.setState({
    turns: {},
    lastMessage: {},
    pending: {},
    drafts: {},
  });
});

describe("chat store event folding", () => {
  it("accumulates message and reasoning deltas", () => {
    emit({ type: "message_delta", text: "Hello " });
    emit({ type: "message_delta", text: "world" });
    emit({ type: "reasoning_delta", text: "thinkingâ€¦" });
    const turn = useChatStore.getState().turns["c_1"]!;
    expect(turn.text).toBe("Hello world");
    expect(turn.reasoning).toBe("thinkingâ€¦");
    expect(turn.running).toBe(true);
  });

  it("pairs tool_call and tool_result into steps with duration and output", () => {
    emit({
      type: "tool_call",
      id: "t1",
      name: "read_file",
      arguments: '{"path":"src/a.ts"}',
    });
    emit({
      type: "tool_result",
      id: "t1",
      name: "read_file",
      ok: true,
      output: "file body",
      durationMs: 42,
    });
    const turn = useChatStore.getState().turns["c_1"]!;
    expect(turn.steps).toHaveLength(1);
    expect(turn.steps[0]).toMatchObject({
      name: "read_file",
      argsSummary: "path: src/a.ts",
      output: "file body",
      ok: true,
      durationMs: 42,
      status: "done",
    });
  });

  it("marks the last running step denied when an approval is denied", () => {
    emit({
      type: "tool_call",
      id: "t1",
      name: "write_file",
      arguments: '{"path":"a.ts"}',
    });
    emit({
      type: "approval_request",
      id: "ap_1",
      tool: "write_file",
      input: { path: "a.ts" },
    });
    expect(useChatStore.getState().turns["c_1"]!.approval?.id).toBe("ap_1");
    emit({ type: "approval_resolved", id: "ap_1", approved: false });
    const turn = useChatStore.getState().turns["c_1"]!;
    expect(turn.approval).toBeNull();
    expect(turn.steps[0]?.status).toBe("denied");
  });

  it("tracks usage and ends the run on done", () => {
    emit({ type: "usage", usage: { promptTokens: 10, completionTokens: 5 } });
    emit({
      type: "done",
      reason: "final",
      steps: 1,
      usage: { promptTokens: 10, completionTokens: 5, totalTokens: 15 },
    });
    const turn = useChatStore.getState().turns["c_1"]!;
    expect(turn.running).toBe(false);
    expect(turn.usage).toEqual({
      promptTokens: 10,
      completionTokens: 5,
      totalTokens: 15,
    });
  });

  it("stores the last message for retry (send wiring)", async () => {
    await act(async () => {
      await useChatStore.getState().send("/tmp/proj", "c_1", "fix the test");
    });
    expect(useChatStore.getState().lastMessage["c_1"]).toBe("fix the test");
    const calls = invoke.mock.calls.filter(([c]) => c === "chat:send");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.[1]).toMatchObject({
      root: "/tmp/proj",
      conversationId: "c_1",
      message: "fix the test",
    });
  });
});

describe("LiveTurnView rendering", () => {
  it("renders streaming text through SafeMarkdown and the step timeline", async () => {
    emit({ type: "message_delta", text: "**bold** reply" });
    emit({
      type: "tool_call",
      id: "t1",
      name: "run_command",
      arguments: '{"command":"npm test"}',
    });
    emit({
      type: "tool_result",
      id: "t1",
      name: "run_command",
      ok: true,
      output: "1 passed",
      durationMs: 1200,
    });
    await render(<LiveTurnView turn={useChatStore.getState().turns["c_1"]!} />);
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.textContent).toContain("run_command");
    expect(container.textContent).toContain("npm test");
    expect(container.textContent).toContain("1200ms");
    // step is collapsed by default (result hidden)
    expect(container.textContent).not.toContain("1 passed");
    // expand
    await act(async () => {
      container.querySelector("button")?.click();
    });
    expect(container.textContent).toContain("1 passed");
  });

  it("shows reasoning collapsed and dimmed until opened", async () => {
    emit({ type: "reasoning_delta", text: "the test fails becauseâ€¦" });
    await render(<LiveTurnView turn={useChatStore.getState().turns["c_1"]!} />);
    expect(container.textContent).toContain("reasoning");
    expect(container.textContent).not.toContain("the test fails");
    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((b) => b.textContent?.includes("reasoning"))
        ?.click();
    });
    expect(container.textContent).toContain("the test fails becauseâ€¦");
  });

  it("renders the per-turn token counter", async () => {
    emit({
      type: "usage",
      usage: { promptTokens: 1234, completionTokens: 56, totalTokens: 1290 },
    });
    await render(<LiveTurnView turn={useChatStore.getState().turns["c_1"]!} />);
    // number formatting is locale-dependent (1,234 or 1.234)
    expect(container.textContent).toMatch(/tokens: 1[.,]234 in \+ 56 out/);
    expect(container.textContent).toMatch(/1[.,]290 total/);
  });

  it("shows the error state for failed turns", async () => {
    emit({
      type: "error",
      message: "Credit quota exhausted for this billing period.",
      fatal: true,
    });
    await render(<LiveTurnView turn={useChatStore.getState().turns["c_1"]!} />);
    expect(container.querySelector("[role=alert]")?.textContent).toContain(
      "Credit quota exhausted",
    );
  });

  it("truncates very long streamed text instead of rendering all of it", async () => {
    const huge = "x".repeat(20_000);
    emit({ type: "message_delta", text: huge });
    await render(
      <Transcript
        messages={[]}
        liveTurn={useChatStore.getState().turns["c_1"]!}
      />,
    );
    // CappedMarkdown caps the rendered markdown and offers the full text
    expect(container.textContent).toContain("show all");
    expect(container.textContent?.length ?? 0).toBeLessThan(21_000);
  });
});

describe("final answer renders exactly once (bug-1 regression)", () => {
  const ANSWER = "The final answer is 42.";

  /** A finished turn (reasoning + streamed answer + usage) for c_1. */
  const finishedTurnWithReasoning = async (): Promise<void> => {
    await act(async () => {
      await useChatStore.getState().send("/tmp/proj", "c_1", "what is it?");
    });
    emit({ type: "reasoning_delta", text: "thinking it through…" });
    emit({ type: "message_delta", text: ANSWER });
    emit({
      type: "usage",
      usage: { promptTokens: 100, completionTokens: 20, totalTokens: 120 },
    });
    emit({
      type: "done",
      reason: "final",
      steps: 0,
      usage: { promptTokens: 100, completionTokens: 20, totalTokens: 120 },
    });
  };

  it("counts the final answer text node ONCE when the history covers the turn", async () => {
    await finishedTurnWithReasoning();
    // the reloaded persisted conversation (what lands after 'done'):
    // user message + final assistant message
    await render(
      <Transcript
        conversationId="c_1"
        messages={[
          { role: "user", content: "what is it?" },
          { role: "assistant", content: ANSWER },
        ]}
        liveTurn={useChatStore.getState().turns["c_1"]!}
      />,
    );
    const occurrences = (container.textContent ?? "").split(ANSWER).length - 1;
    expect(occurrences).toBe(1);
    // the reasoning toggle and the token usage line stay
    expect(container.textContent).toContain("reasoning");
    expect(container.textContent).toMatch(/tokens: 100 in \+ 20 out/);
  });

  it("still shows the streamed answer while the history has not reloaded yet", async () => {
    await finishedTurnWithReasoning();
    // reload in flight: persisted history does not contain the turn yet
    await render(
      <Transcript
        conversationId="c_1"
        messages={[]}
        liveTurn={useChatStore.getState().turns["c_1"]!}
      />,
    );
    const occurrences = (container.textContent ?? "").split(ANSWER).length - 1;
    expect(occurrences).toBe(1); // the live copy — not zero (no flash), not two
    expect(container.textContent).toContain("reasoning");
  });

  it("an errored run keeps its streamed text when nothing was persisted", async () => {
    await act(async () => {
      await useChatStore.getState().send("/tmp/proj", "c_1", "what is it?");
    });
    emit({ type: "reasoning_delta", text: "thinking…" });
    emit({ type: "message_delta", text: ANSWER });
    emit({ type: "error", fatal: true, message: "Cannot reach the backend." });
    // reload landed WITHOUT the turn (fatal errors persist nothing)
    await render(
      <Transcript
        conversationId="c_1"
        messages={[]}
        liveTurn={useChatStore.getState().turns["c_1"]!}
      />,
    );
    expect((container.textContent ?? "").split(ANSWER).length - 1).toBe(1);
    expect(container.textContent).toContain("Cannot reach the backend.");
  });
});

describe("historyCoversRun (coverage rule)", () => {
  it("matches the run's user text against the LAST user message in history", () => {
    const history = [
      { role: "user" as const, content: "older question" },
      { role: "assistant" as const, content: "older answer" },
      { role: "user" as const, content: "what is it?" },
      { role: "assistant" as const, content: "answer" },
    ];
    expect(historyCoversRun(history, "what is it?")).toBe(true);
    expect(historyCoversRun(history, "something else")).toBe(false);
  });

  it("an empty history (or one without user messages) never covers a run", () => {
    expect(historyCoversRun([], "what is it?")).toBe(false);
    expect(
      historyCoversRun([{ role: "assistant", content: "hi" }], "what is it?"),
    ).toBe(false);
  });
});

describe("ApprovalModal (M7)", () => {
  it("shows the exact command, cwd, risk and reason; answers through the bridge", async () => {
    emit({ type: "message_delta", text: "I will run the tests to verify." });
    emit({
      type: "approval_request",
      id: "ap_9",
      tool: "run_command",
      input: { command: "npm test" },
    });
    await render(
      <ApprovalModal
        conversationId="c_1"
        workspaceRoot="/tmp/proj"
        modelReason="I will run the tests to verify."
      />,
    );
    // exact command, working directory, risk category, model reason
    expect(container.textContent).toContain("npm test");
    expect(container.textContent).toContain("/tmp/proj");
    expect(container.textContent).toContain("Command execution");
    expect(container.textContent).toContain("I will run the tests to verify.");
    // always-allow pattern preview is fetched from main
    await act(async () => {});
    expect(
      invoke.mock.calls.filter(([c]) => c === "approvals:preview").length,
    ).toBeGreaterThanOrEqual(1);

    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((b) => b.textContent === "Allow once")
        ?.click();
    });
    let calls = invoke.mock.calls.filter(([c]) => c === "approvals:respond");
    expect(calls.at(-1)?.[1]).toEqual({
      conversationId: "c_1",
      approvalId: "ap_9",
      approved: true,
      remember: false,
    });
    expect(useChatStore.getState().turns["c_1"]?.approval).toBeNull();

    emit({
      type: "approval_request",
      id: "ap_10",
      tool: "write_file",
      input: { path: "src/a.ts", content: "x" },
    });
    await act(async () => {});
    // file edits show the path and the file-edit risk category
    expect(container.textContent).toContain("src/a.ts");
    expect(container.textContent).toContain("File edit");
    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((b) => b.textContent === "Always allow (this project)")
        ?.click();
    });
    calls = invoke.mock.calls.filter(([c]) => c === "approvals:respond");
    expect(calls.at(-1)?.[1]).toMatchObject({
      approvalId: "ap_10",
      remember: true,
    });

    emit({
      type: "approval_request",
      id: "ap_11",
      tool: "run_command",
      input: { command: "del /s" },
    });
    await act(async () => {});
    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((b) => b.textContent === "Deny")
        ?.click();
    });
    calls = invoke.mock.calls.filter(([c]) => c === "approvals:respond");
    expect(calls.at(-1)?.[1]).toMatchObject({
      approvalId: "ap_11",
      approved: false,
    });
  });

  it("keeps denied actions marked denied when the failure result arrives", () => {
    emit({
      type: "tool_call",
      id: "t1",
      name: "run_command",
      arguments: '{"command":"npm test"}',
    });
    emit({
      type: "approval_request",
      id: "ap_1",
      tool: "run_command",
      input: { command: "npm test" },
    });
    emit({ type: "approval_resolved", id: "ap_1", approved: false });
    emit({
      type: "tool_result",
      id: "t1",
      name: "run_command",
      ok: false,
      output:
        "Permission denied for 'run_command': denied by user. Ask the user for an alternative.",
      durationMs: 3,
    });
    const step = useChatStore.getState().turns["c_1"]!.steps[0]!;
    expect(step.status).toBe("denied");
    expect(step.ok).toBe(false);
  });
});

describe("Composer", () => {
  it("sends on Enter with the model from settings; Shift+Enter keeps editing", async () => {
    setProjectsRoot("/tmp/proj");
    await render(
      <Composer
        root="/tmp/proj"
        conversationId="c_1"
        onTurnStarted={() => {}}
      />,
    );
    const textarea = container.querySelector("textarea");
    await type(textarea, "fix the failing test");
    await key(textarea as Element, "Enter", { shift: true });
    expect(invoke.mock.calls.filter(([c]) => c === "chat:send")).toHaveLength(
      0,
    );
    await key(textarea as Element, "Enter");
    const calls = invoke.mock.calls.filter(([c]) => c === "chat:send");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.[1]).toMatchObject({
      root: "/tmp/proj",
      conversationId: "c_1",
      message: "fix the failing test",
    });
    // input cleared after send
    expect((textarea as HTMLTextAreaElement).value).toBe("");
  });

  it("keeps the input ENABLED while a run is active and offers Stop", async () => {
    emit({ type: "message_delta", text: "..." });
    await render(
      <Composer
        root="/tmp/proj"
        conversationId="c_1"
        onTurnStarted={() => {}}
      />,
    );
    // the input never blocks — messages sent mid-run are queued in main
    expect(container.querySelector("textarea")?.disabled).toBe(false);
    const stopBtn = [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Stop"),
    );
    expect(stopBtn).toBeTruthy();
    await act(async () => {
      stopBtn?.click();
    });
    const calls = invoke.mock.calls.filter(([c]) => c === "chat:stop");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.[1]).toEqual({ conversationId: "c_1" });
  });

  it("sends mid-run instead of bouncing (queue, not block)", async () => {
    emit({ type: "message_delta", text: "streaming…" });
    await render(
      <Composer
        root="/tmp/proj"
        conversationId="c_1"
        onTurnStarted={() => {}}
      />,
    );
    const textarea = container.querySelector("textarea");
    await type(textarea, "and one more thing");
    await key(textarea as Element, "Enter");
    const calls = invoke.mock.calls.filter(([c]) => c === "chat:send");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.[1]).toMatchObject({ message: "and one more thing" });
    // the streaming turn is untouched (no reset mid-run)
    expect(useChatStore.getState().turns["c_1"]?.text).toBe("streaming…");
    expect(useChatStore.getState().turns["c_1"]?.running).toBe(true);
  });
});

describe("optimistic bubbles & run queue (send-time UX)", () => {
  it("shows the sent message IMMEDIATELY as a bubble above the live turn", async () => {
    await act(async () => {
      await useChatStore.getState().send("/tmp/proj", "c_1", "hello there");
    });
    await render(
      <Transcript
        messages={[]}
        conversationId="c_1"
        liveTurn={useChatStore.getState().turns["c_1"]}
      />,
    );
    expect(container.textContent).toContain("hello there");
    expect(useChatStore.getState().pending["c_1"]).toHaveLength(1);
  });

  it("marks the bubble queued, then running with the authoritative index", () => {
    void useChatStore.getState().send("/tmp/proj", "c_1", "first");
    emitQueue({ queueEvent: "queued", message: "first", position: 1 });
    let pending = useChatStore.getState().pending["c_1"]!;
    expect(pending[0]?.state).toBe("queued");

    emitQueue({ queueEvent: "started", message: "first", userIndex: 0 });
    pending = useChatStore.getState().pending["c_1"]!;
    expect(pending[0]?.state).toBe("running");
    expect(pending[0]?.userIndex).toBe(0);
    const turn = useChatStore.getState().turns["c_1"]!;
    expect(turn.running).toBe(true);
    expect(turn.userText).toBe("first");
    expect(turn.userIndex).toBe(0);
  });

  it("drops a bubble whose message landed in the reloaded history (positional)", async () => {
    await act(async () => {
      await useChatStore.getState().send("/tmp/proj", "c_1", "hello");
    });
    emitQueue({ queueEvent: "started", message: "hello", userIndex: 0 });
    // the reload after 'done' now contains the persisted user message
    await render(
      <Transcript
        conversationId="c_1"
        messages={[{ role: "user", content: "hello" }]}
        liveTurn={useChatStore.getState().turns["c_1"]}
      />,
    );
    expect(useChatStore.getState().pending["c_1"]).toHaveLength(0);
    // exactly one copy renders (from history — not the optimistic bubble)
    expect((container.textContent ?? "").split("hello").length - 1).toBe(1);
  });

  it("queued bubbles survive a reload that does not contain them yet", async () => {
    await act(async () => {
      await useChatStore.getState().send("/tmp/proj", "c_1", "second");
    });
    emitQueue({ queueEvent: "queued", message: "second", position: 1 });
    await render(
      <Transcript
        conversationId="c_1"
        messages={[{ role: "user", content: "first" }]}
        liveTurn={useChatStore.getState().turns["c_1"]}
      />,
    );
    // userIndex is still unknown (never started) — the bubble must stay
    expect(useChatStore.getState().pending["c_1"]).toHaveLength(1);
    expect(container.textContent).toContain("second");
    expect(container.textContent).toContain("queued");
  });

  it("stop() restores cleared queue texts as a composer draft", async () => {
    await act(async () => {
      await useChatStore.getState().send("/tmp/proj", "c_1", "typed text");
    });
    emitQueue({ queueEvent: "queued", message: "typed text", position: 1 });
    emitQueue({
      queueEvent: "cleared",
      messages: ["typed text"],
    });
    expect(useChatStore.getState().pending["c_1"]).toHaveLength(0);
    expect(useChatStore.getState().drafts["c_1"]).toBe("typed text");
    await render(
      <Composer
        root="/tmp/proj"
        conversationId="c_1"
        onTurnStarted={() => {}}
      />,
    );
    expect(
      (container.querySelector("textarea") as HTMLTextAreaElement).value,
    ).toBe("typed text");
    expect(useChatStore.getState().drafts["c_1"]).toBeNull();
  });
});

describe("activity indicator (thinking state)", () => {
  it("shows thinking dots and the activity line before the first output", async () => {
    await act(async () => {
      await useChatStore.getState().send("/tmp/proj", "c_1", "hi");
    });
    await render(<LiveTurnView turn={useChatStore.getState().turns["c_1"]!} />);
    expect(container.querySelector('[role="status"]')).toBeTruthy();
    expect(container.textContent).toContain("thinking");
  });

  it("switches to writing while text streams", async () => {
    emit({ type: "message_delta", text: "partial answer" });
    await render(<LiveTurnView turn={useChatStore.getState().turns["c_1"]!} />);
    expect(container.textContent).toContain("writing");
    expect(container.textContent).toContain("partial answer");
  });
});

describe("historyCoversAssistant (positional coverage)", () => {
  it("requires a non-empty assistant reply AFTER the run's user message", () => {
    const history = [
      { role: "user" as const, content: "one" },
      { role: "assistant" as const, content: "answer one" },
      { role: "user" as const, content: "two" },
    ];
    // the second run streams: its user message persisted at run START, so
    // the history already contains it — that alone must NOT cover the turn
    expect(historyCoversAssistant(history, 1)).toBe(false);
    const finished = [
      ...history,
      { role: "assistant" as const, content: "answer two" },
    ];
    expect(historyCoversAssistant(finished, 1)).toBe(true);
    // the first run stays covered (its reply is in the history)
    expect(historyCoversAssistant(finished, 0)).toBe(true);
    // an empty assistant turn does not count
    expect(
      historyCoversAssistant(
        [...history, { role: "assistant" as const, content: null }],
        1,
      ),
    ).toBe(false);
  });
});

describe("empty response (bug: silent no-reply turns)", () => {
  it("surfaces an actionable error view with a retryable code", async () => {
    await act(async () => {
      await useChatStore.getState().send("/tmp/proj", "c_1", "i dont know");
    });
    emit({ type: "done", reason: "final", steps: 0, usage: {} });
    // main reports the empty result right after done (non-fatal)
    emit(
      {
        type: "error",
        fatal: false,
        message: "The model returned an empty response.",
      },
      { code: "empty_response" },
    );
    const turn = useChatStore.getState().turns["c_1"]!;
    expect(turn.running).toBe(false);
    expect(turn.errorCode).toBe("empty_response");
    await render(<LiveTurnView turn={turn} />);
    expect(container.querySelector("[role=alert]")?.textContent).toContain(
      "empty response",
    );
  });
});
