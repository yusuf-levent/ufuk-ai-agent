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
  ChatMessageSchema,
  ConversationRenameRequestSchema,
  ConversationSummarySchema,
  LoginRequestSchema,
  OpenExternalRequestSchema,
  ProjectPathRequestSchema,
  ProjectRootRequestSchema,
  RegisterRequestSchema,
  SettingsPatchSchema,
  SettingsSchema,
  type EventMap,
  type InvokeMap,
} from "@shared/ipc";

describe("channel allowlists", () => {
  it("invoke and event channel sets are disjoint", () => {
    for (const c of INVOKE_CHANNEL_SET)
      expect(EVENT_CHANNEL_SET.has(c)).toBe(false);
    for (const c of EVENT_CHANNEL_SET)
      expect(INVOKE_CHANNEL_SET.has(c)).toBe(false);
  });

  it("every InvokeMap entry is a registered invoke channel and vice versa", () => {
    // type-level table is keyed by the literal channel strings; the map
    // below must list every InvokeMap key (checked against INVOKE_CHANNELS)
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
      "projects:list",
      "projects:add",
      "projects:remove",
      "projects:pick-folder",
      "projects:set-permission-mode",
      "conversations:list",
      "conversations:create",
      "conversations:load",
      "conversations:rename",
      "conversations:delete",
      "conversations:changed-files",
      "chat:send",
      "chat:stop",
      "approvals:respond",
      "approvals:preview",
      "checkpoints:list",
      "checkpoints:undo",
      "checkpoints:revert",
      "checkpoints:diff",
      "models:list",
      "usage:get",
    ];
    const invokeValues = Object.values(INVOKE_CHANNELS);
    // every InvokeMap key is a registered channel...
    for (const k of mapKeys) expect(INVOKE_CHANNEL_SET.has(k)).toBe(true);
    // ...and every registered channel has an InvokeMap entry
    expect(mapKeys.length).toBe(invokeValues.length);
    expect(mapKeys.sort()).toEqual([...invokeValues].sort());
  });

  it("every EventMap entry is a registered event channel", () => {
    const eventKeys: (keyof EventMap)[] = ["chat:event"];
    for (const k of eventKeys) expect(EVENT_CHANNEL_SET.has(k)).toBe(true);
    expect(Object.values(EVENT_CHANNELS)).toContain("chat:event");
  });

  it("channel names are namespaced and kebab/colon style (no free-form)", () => {
    for (const c of INVOKE_CHANNEL_SET)
      expect(c).toMatch(/^[a-z]+(-[a-z]+)*:[a-z-]+$/);
    for (const c of EVENT_CHANNEL_SET)
      expect(c).toMatch(/^[a-z]+(-[a-z]+)*:[a-z-]+$/);
  });
});

describe("payload schemas", () => {
  it("login rejects malformed emails and empty passwords", () => {
    expect(
      LoginRequestSchema.safeParse({ email: "a@b.co", password: "x" }).success,
    ).toBe(true);
    expect(
      LoginRequestSchema.safeParse({ email: "not-an-email", password: "x" })
        .success,
    ).toBe(false);
    expect(
      LoginRequestSchema.safeParse({ email: "a@b.co", password: "" }).success,
    ).toBe(false);
    expect(LoginRequestSchema.safeParse({ email: "a@b.co" }).success).toBe(
      false,
    );
  });

  it("register extends login with an optional display name (password min 8, name max 100)", () => {
    expect(
      RegisterRequestSchema.safeParse({
        email: "a@b.co",
        password: "longenough",
        displayName: "A",
      }).success,
    ).toBe(true);
    expect(
      RegisterRequestSchema.safeParse({
        email: "a@b.co",
        password: "longenough",
      }).success,
    ).toBe(true);
    expect(
      RegisterRequestSchema.safeParse({ email: "a@b.co", password: "short" })
        .success,
    ).toBe(false);
    expect(
      RegisterRequestSchema.safeParse({
        email: "a@b.co",
        password: "longenough",
        displayName: "",
      }).success,
    ).toBe(false);
    expect(
      RegisterRequestSchema.safeParse({
        email: "a@b.co",
        password: "longenough",
        displayName: "x".repeat(101),
      }).success,
    ).toBe(false);
  });

  it("settings schema rejects invalid URLs, themes and permission modes", () => {
    expect(
      SettingsPatchSchema.safeParse({ backendUrl: "http://x.example" }).success,
    ).toBe(true);
    expect(
      SettingsPatchSchema.safeParse({ backendUrl: "ftp://nope" }).success,
    ).toBe(false);
    expect(SettingsPatchSchema.safeParse({ theme: "blue" }).success).toBe(
      false,
    );
    expect(
      SettingsPatchSchema.safeParse({ permissionMode: "everything" }).success,
    ).toBe(false);
  });

  it("settings defaults are the documented ones", () => {
    expect(SettingsSchema.parse({})).toEqual({
      backendUrl: "http://localhost:8000",
      theme: "dark",
      defaultTier: "fast",
      permissionMode: "ask",
      privacyAcknowledged: false,
      activeMode: "chat",
    });
  });

  it("openExternal requires a URL (main re-validates protocol)", () => {
    expect(
      OpenExternalRequestSchema.safeParse({ url: "https://x.example" }).success,
    ).toBe(true);
    expect(OpenExternalRequestSchema.safeParse({ url: "" }).success).toBe(
      false,
    );
    expect(OpenExternalRequestSchema.safeParse({}).success).toBe(false);
  });

  it("project and conversation requests validate their payloads", () => {
    expect(
      ProjectPathRequestSchema.safeParse({ path: "C:\\proj" }).success,
    ).toBe(true);
    expect(ProjectPathRequestSchema.safeParse({ path: "" }).success).toBe(
      false,
    );
    expect(ProjectPathRequestSchema.safeParse({}).success).toBe(false);
    expect(ProjectRootRequestSchema.safeParse({ root: "/x" }).success).toBe(
      true,
    );
    expect(
      ConversationRenameRequestSchema.safeParse({
        root: "/x",
        id: "c_1",
        title: "t",
      }).success,
    ).toBe(true);
    // 200-char cap matches the store contract
    expect(
      ConversationRenameRequestSchema.safeParse({
        root: "/x",
        id: "c_1",
        title: "x".repeat(201),
      }).success,
    ).toBe(false);
  });

  it("conversation summaries and chat messages round-trip through schemas", () => {
    expect(
      ConversationSummarySchema.safeParse({
        id: "c_1",
        title: "fix the test",
        createdAt: "2026-01-01T00:00:00Z",
        updatedAt: "2026-01-01T00:00:00Z",
        model: "fast",
      }).success,
    ).toBe(true);
    expect(
      ChatMessageSchema.safeParse({ role: "user", content: "hi" }).success,
    ).toBe(true);
    expect(
      ChatMessageSchema.safeParse({
        role: "assistant",
        content: null,
        toolCalls: [{ id: "c1", name: "read_file", arguments: "{}" }],
      }).success,
    ).toBe(true);
    expect(
      ChatMessageSchema.safeParse({
        role: "tool",
        toolCallId: "c1",
        name: "read_file",
        content: "body",
      }).success,
    ).toBe(true);
    // unknown roles are rejected
    expect(
      ChatMessageSchema.safeParse({ role: "evil", content: "x" }).success,
    ).toBe(false);
  });
});
