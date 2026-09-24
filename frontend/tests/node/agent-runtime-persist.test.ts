// @vitest-environment node
/**
 * Bug-1 regression (assistant answer rendered twice): the runtime must
 * persist the finished turn BEFORE the renderer receives the done event.
 * The renderer reloads the conversation when it observes running->false;
 * if persistence raced ahead of that reload, the final answer could
 * arrive twice (persisted bubble + live copy) or vanish for a moment.
 * This test pins the ordering end to end against a fake SSE gateway.
 */
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { CHAT_ROOT_ID, type ChatEventPayload } from "@shared/ipc";
import { AgentRuntime } from "../../electron/main/agent-runtime";
import { ProjectManager } from "../../electron/main/projects";
import { SettingsStore } from "../../electron/main/settings";
import { buildGatewaySession } from "../../electron/main/gateway";
import { fakeSafe } from "./helpers/fake-safe-storage";
import type { OpenedStore } from "@evren/local-runner";

const dirs: string[] = [];
const tmp = (): string => {
  const d = mkdtempSync(path.join(tmpdir(), "ufuk-persist-"));
  dirs.push(d);
  return d;
};
afterAll(() => {
  for (const d of dirs) {
    try {
      rmSync(d, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
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

/** A fake gateway: one plain streamed answer with usage. */
function fakeGatewayFetch(): typeof fetch {
  return (async () =>
    sseResponse([
      `data: ${JSON.stringify({ choices: [{ delta: { content: "Hello " } }] })}\n\n`,
      `data: ${JSON.stringify({ choices: [{ delta: { content: "world" } }] })}\n\n`,
      `data: ${JSON.stringify({
        choices: [{ delta: {}, finish_reason: "stop" }],
        usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
      })}\n\n`,
      "data: [DONE]\n\n",
    ])) as unknown as typeof fetch;
}

describe("AgentRuntime persists before emitting done (bug-1 regression)", () => {
  it("appendMessages completes before the done event reaches the renderer", async () => {
    const userData = tmp();
    const settings = new SettingsStore(userData);
    const projects = new ProjectManager(userData);
    // app-owned chat workspace (tool-less — no approvals in the loop)
    mkdirSync(path.join(userData, "chat-workspace"), { recursive: true });

    const session = buildGatewaySession(
      settings.load(),
      userData,
      fakeSafe(),
      fakeGatewayFetch(),
    );
    // pre-seed a valid (unexpired) access token so the provider never
    // needs a network refresh
    await session.tokenStore.store.save({
      accessToken: "test-access-token",
      refreshToken: "test-refresh-token",
      expiresAt: Date.now() + 3_600_000,
    });

    // conversation in the chat workspace
    const opened = await projects.store(CHAT_ROOT_ID);
    const conversationId = await opened.store.createConversation(
      projects.chatRootPath(),
      "fast",
    );

    // ordering log: appendMessages vs the done event crossing the bridge
    const order: string[] = [];
    const events: ChatEventPayload[] = [];
    const origAppend = opened.store.appendMessages.bind(opened.store);
    opened.store.appendMessages = async (...args: Parameters<
      typeof origAppend
    >) => {
      await origAppend(...args);
      order.push("append");
    };
    const patchedOpened: OpenedStore = opened;

    const fakeWin = {
      isDestroyed: () => false,
      webContents: {
        send: (_channel: string, payload: ChatEventPayload) => {
          events.push(payload);
          if (payload.event.type === "done") order.push("done");
        },
      },
    };

    // route projects.store() to the patched instance (cache override)
    const projectsWithPatch = Object.create(projects) as ProjectManager;
    (projectsWithPatch as unknown as { store: (r: string) => Promise<OpenedStore> }).store =
      (root: string) =>
        root === CHAT_ROOT_ID
          ? Promise.resolve(patchedOpened)
          : projects.store(root);

    const runtime = new AgentRuntime({
      win: () => fakeWin as never,
      settings,
      session: () => session,
      projects: projectsWithPatch,
    });

    await runtime.send(CHAT_ROOT_ID, conversationId, "hi there");

    // the run streamed its answer and finished
    const types = events.map((e) => e.event.type);
    expect(types).toContain("message_delta");
    expect(types[types.length - 1]).toBe("done");

    // THE regression: persistence completed before done was emitted
    expect(order.indexOf("append")).toBeGreaterThanOrEqual(0);
    expect(order.lastIndexOf("append")).toBeLessThan(order.lastIndexOf("done"));

    // and the persisted conversation holds the full turn exactly once
    const detail = await patchedOpened.store.loadConversation(conversationId);
    expect(detail?.messages).toEqual([
      { role: "user", content: "hi there" },
      { role: "assistant", content: "Hello world" },
    ]);
  });
});
