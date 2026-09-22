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
          return { ok: true, value: null };
        case "app:version":
          return {
            ok: true,
            value: { version: "0.1.0", electron: "44.4.3", node: "22" },
          };
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
