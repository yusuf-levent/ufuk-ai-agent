/**
 * Installs a fake preload bridge (window.ufuk) for DOM tests. Handlers are
 * plain functions per channel so each test can override behavior; payloads
 * can be asserted on the returned invoke mock.
 */
import { vi } from "vitest";
import type { Settings } from "@shared/ipc";

export const defaultSettings: Settings = {
  backendUrl: "http://localhost:8000",
  theme: "dark",
  defaultTier: "fast",
  permissionMode: "ask",
  privacyAcknowledged: false,
};

export const defaultPrivacyInfo = {
  providers: ["ExampleAI"],
  upstreamHost: "gw.example.com",
  dataHandling: "Prompts are proxied upstream; only usage metadata is kept.",
  accountDeletion: "Deleting your account removes profile and sessions.",
};

export const defaultProjects = [
  {
    root: "C:\\code\\app",
    name: "app",
    addedAt: "2026-01-01T00:00:00Z",
    lastOpenedAt: "2026-01-02T00:00:00Z",
    isGitRepo: true,
  },
];

export const defaultConversations = [
  {
    id: "c_1",
    title: "fix the test",
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-02T00:00:00Z",
    model: "fast",
  },
];

export interface BridgeOverrides {
  [channel: string]: (payload?: unknown) => unknown;
}

export function installBridge(overrides: BridgeOverrides = {}): {
  invoke: ReturnType<typeof vi.fn>;
} {
  const invoke = vi.fn(
    async (channel: string, payload?: unknown): Promise<unknown> => {
      const handler = overrides[channel];
      if (handler) return handler(payload);
      switch (channel) {
        case "settings:get":
          return { ok: true, value: defaultSettings };
        case "settings:set":
          return {
            ok: true,
            value: {
              ...defaultSettings,
              ...(payload as Partial<Settings> | undefined),
            },
          };
        case "privacy:info":
          return { ok: true, value: defaultPrivacyInfo };
        case "auth:session":
          return { ok: true, value: null };
        case "auth:login":
        case "auth:register":
        case "auth:logout":
          return { ok: true, value: null };
        case "app:version":
          return {
            ok: true,
            value: { version: "0.1.0", electron: "44.4.3", node: "22" },
          };
        case "projects:list":
          return { ok: true, value: defaultProjects };
        case "projects:pick-folder":
          return { ok: true, value: null };
        case "conversations:list":
          return { ok: true, value: defaultConversations };
        case "conversations:create":
          return { ok: true, value: defaultConversations[0] };
        case "conversations:load":
          return {
            ok: true,
            value: {
              summary: defaultConversations[0],
              messages: [
                { role: "user", content: "fix the test" },
                { role: "assistant", content: "done" },
              ],
            },
          };
        case "conversations:rename":
        case "conversations:delete":
          return { ok: true, value: true };
        case "approvals:preview":
          return { ok: true, value: { tool: "run_command", pattern: "npm test" } };
        case "projects:set-permission-mode":
          return { ok: true, value: defaultProjects[0] };
        case "checkpoints:list":
          return { ok: true, value: [] };
        case "checkpoints:undo":
        case "checkpoints:revert":
          return { ok: true, value: null };
        case "checkpoints:diff":
          return {
            ok: true,
            value: {
              path: "a.ts",
              snapshotMissing: false,
              identical: false,
              oldLines: 2,
              newLines: 2,
              hunks: [
                {
                  oldStart: 1,
                  newStart: 1,
                  lines: [
                    { kind: "ctx", text: "hello", oldLine: 1, newLine: 1 },
                    { kind: "del", text: "old", oldLine: 2, newLine: null },
                    { kind: "add", text: "new", oldLine: null, newLine: 2 },
                  ],
                },
              ],
            },
          };
        case "conversations:changed-files":
          return { ok: true, value: [] };
        default:
          return { ok: false, error: { message: `no handler for ${channel}` } };
      }
    },
  );
  (window as unknown as Record<string, unknown>)["ufuk"] = {
    invoke,
    subscribe: vi.fn(),
  };
  return { invoke };
}
