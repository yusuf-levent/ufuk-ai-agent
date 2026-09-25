// @vitest-environment node
/**
 * Run-queue behavior (UX rework): messages sent while a run is active are
 * QUEUED (never bounced with "already running"), run in order after the
 * current reply; the user message persists at run START (optimistic UI +
 * crash safety); stop() drops queued messages and pushes their texts back
 * ('cleared'); an empty final response surfaces as a non-fatal
 * empty_response error; the optional auto-retry re-sends once.
 */
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterAll, describe, expect, it, vi, type Mock } from "vitest";
import {
  CHAT_ROOT_ID,
  type ChatEventPayload,
  type ChatQueueEventPayload,
} from "@shared/ipc";
import { AgentRuntime } from "../../electron/main/agent-runtime";
import { ProjectManager } from "../../electron/main/projects";
import { SettingsStore } from "../../electron/main/settings";
import { buildGatewaySession } from "../../electron/main/gateway";
import { fakeSafe } from "./helpers/fake-safe-storage";
import type { OpenedStore } from "@evren/local-runner";

const dirs: string[] = [];
const tmp = (): string => {
  const d = mkdtempSync(path.join(tmpdir(), "ufuk-queue-"));
  dirs.push(d);
  return d;
};
afterAll(() => {
  for (const d of dirs) {
    try {
      rmSync(d, {
        recursive: true,
        force: true,
        maxRetries: 3,
        retryDelay: 100,
      });
    } catch {
      // ignore (sqlite WAL files on Windows)
    }
  }
});

/** SSE response carrying the given data chunks. */
function sseResponse(chunks: string[]): Response {
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        const enc = new TextEncoder();
        for (const c of chunks) controller.enqueue(enc.encode(c));
        controller.close();
      },
    }),
    { status: 200, headers: { "content-type": "text/event-stream" } },
  );
}

const answer = (text: string): string[] => [
  `data: ${JSON.stringify({ choices: [{ delta: { content: text } }] })}\n\n`,
  `data: ${JSON.stringify({
    choices: [{ delta: {}, finish_reason: "stop" }],
    usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
  })}\n\n`,
  "data: [DONE]\n\n",
];

const EMPTY_REPLY: string[] = [
  `data: ${JSON.stringify({
    choices: [{ delta: {}, finish_reason: "stop" }],
  })}\n\n`,
  "data: [DONE]\n\n",
];

/** A stream whose chunks arrive only once resolve() is called. */
function deferredStream(): {
  resolve: (chunks: string[]) => void;
  response: () => Response;
} {
  let release!: (chunks: string[]) => void;
  const gate = new Promise<string[]>((r) => {
    release = r;
  });
  return {
    resolve: release,
    response: () =>
      new Response(
        new ReadableStream<Uint8Array>({
          async start(controller) {
            const enc = new TextEncoder();
            for (const c of await gate) controller.enqueue(enc.encode(c));
            controller.close();
          },
        }),
        { status: 200, headers: { "content-type": "text/event-stream" } },
      ),
  };
}

interface Harness {
  runtime: AgentRuntime;
  events: ChatEventPayload[];
  fetchCalls: Mock;
  opened: OpenedStore;
  conversationId: string;
}

/** Chat-mode runtime wired to a scripted fetch and a capturing window. */
async function harness(
  replies: (() => Response)[],
  settingsPatch: { autoRetryEmptyResponses?: boolean } = {},
): Promise<Harness> {
  const userData = tmp();
  const settings = new SettingsStore(userData);
  if (Object.keys(settingsPatch).length > 0) {
    settings.patch(settingsPatch);
  }
  const projects = new ProjectManager(userData);
  mkdirSync(path.join(userData, "chat-workspace"), { recursive: true });

  const fetchCalls = vi.fn(async (): Promise<Response> => {
    const next = replies.shift();
    return next ? next() : sseResponse(answer("fallback"));
  }) as unknown as Mock;

  const session = buildGatewaySession(
    settings.load(),
    userData,
    fakeSafe(),
    fetchCalls as unknown as typeof fetch,
  );
  await session.tokenStore.store.save({
    accessToken: "test-access-token",
    refreshToken: "test-refresh-token",
    expiresAt: Date.now() + 3_600_000,
  });

  const opened = await projects.store(CHAT_ROOT_ID);
  const conversationId = await opened.store.createConversation(
    projects.chatRootPath(),
    "fast",
  );

  const events: ChatEventPayload[] = [];
  const fakeWin = {
    isDestroyed: () => false,
    webContents: {
      send: (_channel: string, payload: ChatEventPayload) => {
        events.push(payload);
      },
    },
  };
  const runtime = new AgentRuntime({
    win: () => fakeWin as never,
    settings,
    session: () => session,
    projects,
  });
  return { runtime, events, fetchCalls, opened, conversationId };
}

const queueEvents = (h: Harness): ChatQueueEventPayload[] =>
  h.events.filter((e): e is ChatQueueEventPayload => "queueEvent" in e);

describe("AgentRuntime run queue", () => {
  it("queues a mid-run message and runs it after the current reply", async () => {
    const first = deferredStream();
    const h = await harness([
      first.response,
      () => sseResponse(answer("second reply")),
    ]);

    // first run starts and stays active (stream not resolved yet)
    const run1 = h.runtime.send(CHAT_ROOT_ID, h.conversationId, "first");
    await vi.waitFor(() =>
      expect(queueEvents(h).some((e) => e.queueEvent === "started")).toBe(true),
    );

    // the user message is persisted at run START (optimistic UI + crashes)
    const early = await h.opened.store.loadConversation(h.conversationId);
    expect(early?.messages).toEqual([{ role: "user", content: "first" }]);

    // a second message while the run is active: queued, never bounced
    const run2 = h.runtime.send(CHAT_ROOT_ID, h.conversationId, "second");
    await vi.waitFor(() =>
      expect(queueEvents(h).some((e) => e.queueEvent === "queued")).toBe(true),
    );
    // no fatal "already running" bounce exists anymore
    expect(
      h.events.some(
        (e) =>
          "event" in e &&
          e.event.type === "error" &&
          e.event.message.includes("already running"),
      ),
    ).toBe(false);

    // finish the first reply: the queue drains and the second runs
    first.resolve(answer("first reply"));
    await run1;
    await run2;

    expect(h.fetchCalls.mock.calls.length).toBeGreaterThanOrEqual(2);
    const starts = queueEvents(h).filter((e) => e.queueEvent === "started");
    expect(starts.map((e) => [e.message, e.userIndex])).toEqual([
      ["first", 0],
      ["second", 1],
    ]);

    const detail = await h.opened.store.loadConversation(h.conversationId);
    expect(detail?.messages).toEqual([
      { role: "user", content: "first" },
      { role: "assistant", content: "first reply" },
      { role: "user", content: "second" },
      { role: "assistant", content: "second reply" },
    ]);
  });

  it("stop() aborts the run AND drops queued messages, reporting their texts", async () => {
    const first = deferredStream();
    const h = await harness([first.response]);

    const run1 = h.runtime.send(CHAT_ROOT_ID, h.conversationId, "first");
    await vi.waitFor(() =>
      expect(queueEvents(h).some((e) => e.queueEvent === "started")).toBe(true),
    );
    h.runtime.send(CHAT_ROOT_ID, h.conversationId, "queued-one");
    h.runtime.send(CHAT_ROOT_ID, h.conversationId, "queued-two");
    await vi.waitFor(() =>
      expect(
        queueEvents(h).filter((e) => e.queueEvent === "queued"),
      ).toHaveLength(2),
    );

    expect(h.runtime.stop(h.conversationId)).toBe(true);
    const cleared = queueEvents(h).find((e) => e.queueEvent === "cleared");
    expect(cleared?.messages).toEqual(["queued-one", "queued-two"]);

    first.resolve(answer("aborted reply"));
    await run1;

    // the queue is gone: a new send starts immediately (fetch #2, not #3+)
    await h.runtime.send(CHAT_ROOT_ID, h.conversationId, "fresh");
    expect(h.fetchCalls.mock.calls.length).toBe(2);
    const detail = await h.opened.store.loadConversation(h.conversationId);
    // queued-one/queued-two were never persisted (cancelled before running)
    expect(
      detail?.messages.some(
        (m) => m.role === "user" && m.content === "queued-one",
      ),
    ).toBe(false);
  });

  it("an empty final response surfaces as an empty_response error", async () => {
    const h = await harness([() => sseResponse(EMPTY_REPLY)]);
    await h.runtime.send(CHAT_ROOT_ID, h.conversationId, "i dont know");

    const emptyError = h.events.find(
      (e) =>
        "event" in e &&
        e.event.type === "error" &&
        e.errorInfo?.code === "empty_response",
    );
    expect(emptyError).toBeTruthy();
    if (!("event" in emptyError!) || emptyError.event.type !== "error") {
      throw new Error("unreachable");
    }
    expect(emptyError.event.fatal).toBe(false);

    // the turn still persisted (user message + empty assistant), matching
    // the old silent-loss symptom — but now it is EXPLAINED
    const detail = await h.opened.store.loadConversation(h.conversationId);
    expect(detail?.messages).toEqual([
      { role: "user", content: "i dont know" },
      { role: "assistant", content: null },
    ]);
  });

  it("auto-retries an empty response once when the setting is on", async () => {
    const h = await harness(
      [() => sseResponse(EMPTY_REPLY), () => sseResponse(answer("recovered"))],
      { autoRetryEmptyResponses: true },
    );
    await h.runtime.send(CHAT_ROOT_ID, h.conversationId, "try again");

    expect(h.fetchCalls.mock.calls.length).toBe(2);
    // the retry produced content: no empty_response error at all
    expect(
      h.events.some(
        (e) => "event" in e && e.errorInfo?.code === "empty_response",
      ),
    ).toBe(false);

    const detail = await h.opened.store.loadConversation(h.conversationId);
    expect(detail?.messages).toEqual([
      { role: "user", content: "try again" },
      { role: "assistant", content: null }, // attempt 1 (empty, persisted)
      { role: "assistant", content: "recovered" }, // attempt 2
    ]);
  });
});
