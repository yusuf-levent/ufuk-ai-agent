// @vitest-environment node
/** SettingsStore (main process): defaults, persistence, corrupt-file safety. */
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { SettingsStore } from "../../electron/main/settings";

const dirs: string[] = [];
const tmp = (): string => {
  const d = mkdtempSync(path.join(tmpdir(), "ufuk-settings-"));
  dirs.push(d);
  return d;
};
afterAll(() => {
  for (const d of dirs) rmSync(d, { recursive: true, force: true });
});

describe("SettingsStore", () => {
  it("returns documented defaults when no file exists", () => {
    const store = new SettingsStore(tmp());
    expect(store.load()).toEqual({
      backendUrl: "http://localhost:8000",
      theme: "dark",
      defaultTier: "fast",
      permissionMode: "ask",
      privacyAcknowledged: false,
      activeMode: "chat",
    });
  });

  it("persists patches and round-trips through a new instance", () => {
    const dir = tmp();
    const store = new SettingsStore(dir);
    const next = store.patch({ theme: "light", defaultTier: "strong" });
    expect(next.theme).toBe("light");
    expect(next.defaultTier).toBe("strong");

    const raw = JSON.parse(
      readFileSync(path.join(dir, "settings.json"), "utf8"),
    );
    expect(raw).toEqual(next);

    const reopened = new SettingsStore(dir);
    expect(reopened.load()).toEqual(next);
  });

  it("falls back to defaults on a corrupt settings file", () => {
    const dir = tmp();
    writeFileSync(path.join(dir, "settings.json"), "{not json", "utf8");
    const store = new SettingsStore(dir);
    expect(store.load().backendUrl).toBe("http://localhost:8000");
  });

  it("falls back to defaults when the file fails schema validation", () => {
    const dir = tmp();
    writeFileSync(
      path.join(dir, "settings.json"),
      JSON.stringify({ theme: "neon", permissionMode: "yolo" }),
      "utf8",
    );
    const store = new SettingsStore(dir);
    const loaded = store.load();
    expect(loaded.theme).toBe("dark");
    expect(loaded.permissionMode).toBe("ask");
  });

  it("rejects invalid patches instead of writing them", () => {
    const store = new SettingsStore(tmp());
    // values the type system forbids but IPC payloads could still carry
    const badMode = { permissionMode: "allow-all" } as unknown as Parameters<
      typeof store.patch
    >[0];
    expect(() => store.patch(badMode)).toThrow();
    const badUrl = { backendUrl: "not a url" } as unknown as Parameters<
      typeof store.patch
    >[0];
    expect(() => store.patch(badUrl)).toThrow();
    // store unchanged
    expect(store.load().permissionMode).toBe("ask");
  });

  it("a patch keeps the other fields intact (zod partial-with-defaults regression)", async () => {
    // zod v4's .partial() KEEPS .default() values: a naive
    // SettingsSchema.partial() patch parsed {activeMode} into a full
    // object with every default filled in, so every settings:set call
    // RESET all other fields — e.g. the privacy acknowledgement was
    // lost right after login when the nav switched modes (found by the
    // fix-it e2e: the privacy gate came back after clicking Projects).
    const { SettingsPatchSchema } = await import("@shared/ipc");
    const parsed = SettingsPatchSchema.parse({ activeMode: "projects" });
    expect(Object.keys(parsed)).toEqual(["activeMode"]);

    // the real-world chain: acknowledge -> later patch a different key
    const dir = tmp();
    const store = new SettingsStore(dir);
    store.patch({ privacyAcknowledged: true, theme: "light" });
    store.patch({ activeMode: "projects" });
    const after = store.load();
    expect(after.privacyAcknowledged).toBe(true);
    expect(after.theme).toBe("light");
    expect(after.activeMode).toBe("projects");
    // and it round-trips through a fresh instance (file content too)
    expect(new SettingsStore(dir).load().privacyAcknowledged).toBe(true);
  });

  it("has no allow-everything permission mode in the schema", async () => {
    const { SettingsSchema } = await import("@shared/ipc");
    const mode = SettingsSchema.shape.permissionMode;
    // behaviorally: exactly 'ask' and 'auto-edits' parse; anything else fails
    expect(mode.safeParse("ask").success).toBe(true);
    expect(mode.safeParse("auto-edits").success).toBe(true);
    for (const denied of ["allow-all", "everything", "yolo", ""]) {
      expect(mode.safeParse(denied).success).toBe(false);
    }
  });
});
