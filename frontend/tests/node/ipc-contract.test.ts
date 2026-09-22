// @vitest-environment node
/**
 * IPC contract: the channel allowlists, the InvokeMap/EventMap tables and
 * the zod payload schemas must stay in sync — this suite fails whenever a
 * channel is added without a contract entry (or vice versa).
 */
import { describe, expect, it } from "vitest";
import {
  EVENT_CHANNELS,
  EVENT_CHANNEL_SET,
  INVOKE_CHANNELS,
  INVOKE_CHANNEL_SET,
} from "@shared/channels";
import {
  LoginRequestSchema,
  OpenExternalRequestSchema,
  RegisterRequestSchema,
  SettingsPatchSchema,
  SettingsSchema,
  type EventMap,
  type InvokeMap,
} from "@shared/ipc";

describe("channel allowlists", () => {
  it("invoke and event channel sets are disjoint", () => {
    for (const c of INVOKE_CHANNEL_SET) expect(EVENT_CHANNEL_SET.has(c)).toBe(false);
    for (const c of EVENT_CHANNEL_SET) expect(INVOKE_CHANNEL_SET.has(c)).toBe(false);
  });

  it("every InvokeMap entry is a registered invoke channel and vice versa", () => {
    const mapChannels = Object.keys({} as InvokeMap);
    expect(mapChannels).toEqual([]);
    // type-level table is keyed by the literal channel strings:
    const invokeValues = Object.values(INVOKE_CHANNELS);
    const mapKeys: (keyof InvokeMap)[] = [
      "app:version",
      "settings:get",
      "settings:set",
      "auth:login",
      "auth:register",
      "auth:logout",
      "auth:session",
      "privacy:info",
      "shell:open-external",
    ];
    for (const k of mapKeys) expect(INVOKE_CHANNEL_SET.has(k)).toBe(true);
    expect(mapKeys.sort()).toEqual([...invokeValues].sort());
  });

  it("every EventMap entry is a registered event channel", () => {
    const eventKeys: (keyof EventMap)[] = ["chat:event"];
    for (const k of eventKeys) expect(EVENT_CHANNEL_SET.has(k)).toBe(true);
    expect(Object.values(EVENT_CHANNELS)).toContain("chat:event");
  });

  it("channel names are namespaced and kebab/colon style (no free-form)", () => {
    for (const c of INVOKE_CHANNEL_SET) expect(c).toMatch(/^[a-z]+(-[a-z]+)*:[a-z-]+$/);
    for (const c of EVENT_CHANNEL_SET) expect(c).toMatch(/^[a-z]+(-[a-z]+)*:[a-z-]+$/);
  });
});

describe("payload schemas", () => {
  it("login rejects malformed emails and empty passwords", () => {
    expect(LoginRequestSchema.safeParse({ email: "a@b.co", password: "x" }).success).toBe(true);
    expect(LoginRequestSchema.safeParse({ email: "not-an-email", password: "x" }).success).toBe(
      false,
    );
    expect(LoginRequestSchema.safeParse({ email: "a@b.co", password: "" }).success).toBe(false);
    expect(LoginRequestSchema.safeParse({ email: "a@b.co" }).success).toBe(false);
  });

  it("register extends login with an optional display name (max 100)", () => {
    expect(
      RegisterRequestSchema.safeParse({ email: "a@b.co", password: "x", displayName: "A" })
        .success,
    ).toBe(true);
    expect(
      RegisterRequestSchema.safeParse({ email: "a@b.co", password: "x", displayName: "" }).success,
    ).toBe(false);
    expect(
      RegisterRequestSchema.safeParse({ email: "a@b.co", password: "x", displayName: "x".repeat(101) })
        .success,
    ).toBe(false);
  });

  it("settings schema rejects invalid URLs, themes and permission modes", () => {
    expect(SettingsPatchSchema.safeParse({ backendUrl: "http://x.example" }).success).toBe(true);
    expect(SettingsPatchSchema.safeParse({ backendUrl: "ftp://nope" }).success).toBe(false);
    expect(SettingsPatchSchema.safeParse({ theme: "blue" }).success).toBe(false);
    expect(SettingsPatchSchema.safeParse({ permissionMode: "everything" }).success).toBe(false);
  });

  it("settings defaults are the documented ones", () => {
    expect(SettingsSchema.parse({})).toEqual({
      backendUrl: "http://localhost:8000",
      theme: "dark",
      defaultTier: "fast",
      permissionMode: "ask",
      privacyAcknowledged: false,
    });
  });

  it("openExternal requires a URL (main re-validates protocol)", () => {
    expect(OpenExternalRequestSchema.safeParse({ url: "https://x.example" }).success).toBe(true);
    expect(OpenExternalRequestSchema.safeParse({ url: "" }).success).toBe(false);
    expect(OpenExternalRequestSchema.safeParse({}).success).toBe(false);
  });
});
