// @vitest-environment node
/**
 * Issue 2 — canonical userData pinning + legacy migration. The app used
 * to end up with three different userData dirs depending on the launch
 * mode (packaged "Ufuk", `pnpm start` "ufuk", dev "Electron"), which
 * fragmented tokens/settings/projects and forced re-logins. The pin
 * makes every mode use %APPDATA%\Ufuk; the merge brings legacy data in
 * with zero loss.
 */
import {
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
  readFileSync,
  existsSync,
  utimesSync,
} from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import {
  USER_DATA_KEYS,
  canonicalUserDataDir,
  legacyUserDataDirs,
  migrateLegacyUserData,
} from "../../electron/main/userdata";
import { SettingsStore } from "../../electron/main/settings";
import { ProjectManager } from "../../electron/main/projects";

const dirs: string[] = [];
const tmp = (): string => {
  const d = mkdtempSync(path.join(tmpdir(), "ufuk-userdata-"));
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
      // ignore (fs handles on Windows)
    }
  }
});

const writeFile = (dir: string, rel: string, content: string): void => {
  mkdirSync(path.dirname(path.join(dir, rel)), { recursive: true });
  writeFileSync(path.join(dir, rel), content, "utf8");
};

describe("canonical dir", () => {
  it("is %APPDATA%\\Ufuk — the packaged app's existing dir (no move for installs)", () => {
    const appData = tmp();
    expect(canonicalUserDataDir(appData)).toBe(path.join(appData, "Ufuk"));
  });

  it("legacy dirs cover the pnpm-start and plain-electron identities", () => {
    const appData = tmp();
    expect(legacyUserDataDirs(appData)).toEqual([
      path.join(appData, "ufuk"),
      path.join(appData, "Electron"),
    ]);
  });
});

describe("migrateLegacyUserData", () => {
  // NOTE: tests use custom legacy dir names ("legacy-a"/"legacy-b")
  // instead of the real "ufuk"/"Ufuk" pair — on Windows those two
  // spellings are the SAME (case-insensitive) directory, so the real
  // legacyUserDataDirs() would collide with the canonical dir here.
  it("copies missing keys from legacy dirs (zero data loss, newest wins)", async () => {
    const appData = tmp();
    const canonical = canonicalUserDataDir(appData);
    const legacyA = path.join(appData, "legacy-a");
    const legacyB = path.join(appData, "legacy-b");

    // legacy-a has settings + a token file
    writeFile(
      legacyA,
      "settings.json",
      JSON.stringify({ theme: "light", privacyAcknowledged: true }),
    );
    writeFile(legacyA, path.join("gateway", "tokens-abc.bin"), "tok-a");
    // legacy-b has a NEWER token file + projects + db
    writeFile(
      legacyB,
      "projects.json",
      JSON.stringify({
        projects: [
          {
            root: "C:\\code\\x",
            name: "x",
            addedAt: "2026-01-01T00:00:00Z",
            lastOpenedAt: "2026-01-01T00:00:00Z",
          },
        ],
      }),
    );
    writeFile(legacyB, path.join("gateway", "tokens-abc.bin"), "tok-b");
    writeFile(legacyB, path.join("db", "abc", "store.jsonl"), "{}");

    // make the legacy-b token strictly newer
    const later = Date.now() / 1000 + 100;
    utimesSync(path.join(legacyB, "gateway", "tokens-abc.bin"), later, later);

    const migrated = migrateLegacyUserData(canonical, [legacyA, legacyB]);
    expect(migrated.sort()).toEqual([
      "db",
      "gateway",
      "projects.json",
      "settings.json",
    ]);
    // settings from legacy-a (legacy-b has none)
    expect(
      JSON.parse(readFileSync(path.join(canonical, "settings.json"), "utf8")),
    ).toEqual({ theme: "light", privacyAcknowledged: true });
    // the NEWER (legacy-b) token file won
    expect(
      readFileSync(path.join(canonical, "gateway", "tokens-abc.bin"), "utf8"),
    ).toBe("tok-b");
    // projects + db copied
    expect(existsSync(path.join(canonical, "db", "abc", "store.jsonl"))).toBe(
      true,
    );
    expect(
      JSON.parse(readFileSync(path.join(canonical, "projects.json"), "utf8")),
    ).toMatchObject({ projects: [{ root: "C:\\code\\x" }] });
  });

  it("never overwrites existing canonical data (idempotent, canonical wins)", () => {
    const appData = tmp();
    const canonical = canonicalUserDataDir(appData);
    const legacy = path.join(appData, "legacy-x");
    writeFile(canonical, "settings.json", JSON.stringify({ theme: "dark" }));
    writeFile(legacy, "settings.json", JSON.stringify({ theme: "light" }));

    const migrated = migrateLegacyUserData(canonical, [legacy]);
    expect(migrated).toEqual([]); // canonical settings exist — nothing copied
    expect(
      JSON.parse(readFileSync(path.join(canonical, "settings.json"), "utf8")),
    ).toEqual({ theme: "dark" });
  });

  it("returns [] when there is nothing to migrate (fresh machine)", () => {
    const appData = tmp();
    const migrated = migrateLegacyUserData(canonicalUserDataDir(appData), [
      path.join(appData, "legacy-none"),
    ]);
    expect(migrated).toEqual([]);
  });

  it("a migrated install actually boots: settings + projects + conversations load", async () => {
    // simulate a real legacy install: a project with a conversation and
    // messages under a legacy dir, then merge and open everything
    const appData = tmp();
    const legacy = path.join(appData, "legacy-install");
    const canonical = canonicalUserDataDir(appData);

    const projDir = path.join(appData, "proj");
    mkdirSync(projDir, { recursive: true });
    const pm = new ProjectManager(legacy);
    pm.add(projDir);
    const opened = await pm.store(projDir);
    const id = await opened.store.createConversation(projDir, "fast");
    await opened.store.appendMessages(id, [
      { role: "user", content: "fix the test" },
    ]);
    writeFile(legacy, "settings.json", JSON.stringify({ theme: "dark" }));

    migrateLegacyUserData(canonical, [legacy]);

    // "boot" on the canonical dir: everything is there
    const settings = new SettingsStore(canonical);
    expect(settings.load().theme).toBe("dark");
    const pm2 = new ProjectManager(canonical);
    expect(pm2.list().map((p) => p.root)).toEqual([projDir]);
    const convs = await pm2.listConversations(projDir);
    expect(convs.map((c) => c.id)).toEqual([id]);
    const detail = await (await pm2.store(projDir)).store.loadConversation(id);
    expect(detail?.messages).toEqual([
      { role: "user", content: "fix the test" },
    ]);
  });

  it("only touches app-owned keys", () => {
    expect([...USER_DATA_KEYS]).toEqual([
      "settings.json",
      "projects.json",
      "gateway",
      "db",
    ]);
  });

  it("handles legacy dirs with foreign junk safely (unknown files are ignored)", () => {
    const appData = tmp();
    const legacy = path.join(appData, "legacy-junk");
    // some OTHER electron app's data lives there too
    writeFile(legacy, "DevToolsActivePort", "12345");
    writeFile(legacy, path.join("Local Storage", "leveldb", "x.log"), "junk");
    const migrated = migrateLegacyUserData(canonicalUserDataDir(appData), [
      legacy,
    ]);
    expect(migrated).toEqual([]);
    expect(
      existsSync(
        path.join(canonicalUserDataDir(appData), "DevToolsActivePort"),
      ),
    ).toBe(false);
  });
});
