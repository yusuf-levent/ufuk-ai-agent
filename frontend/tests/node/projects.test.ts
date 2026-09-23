// @vitest-environment node
/**
 * ProjectManager (main process): folder validation, recents persistence,
 * git probe, per-project conversation stores (create/list/rename/delete).
 */
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import {
  ProjectManager,
  ProjectValidationError,
} from "../../electron/main/projects";

const dirs: string[] = [];
const tmp = (prefix: string): string => {
  const d = mkdtempSync(path.join(tmpdir(), `ufuk-${prefix}-`));
  dirs.push(d);
  return d;
};
afterAll(() => {
  // best-effort: sqlite keeps WAL files open on Windows, so a dir may
  // briefly resist deletion — the OS temp cleaner catches the rest
  for (const d of dirs) {
    try {
      rmSync(d, {
        recursive: true,
        force: true,
        maxRetries: 3,
        retryDelay: 100,
      });
    } catch {
      // ignore
    }
  }
});

const managerIn = (dir: string): ProjectManager => new ProjectManager(dir);

describe("ProjectManager.add", () => {
  it("accepts a real directory and remembers it", () => {
    const dataDir = tmp("data");
    const proj = tmp("proj");
    const m = managerIn(dataDir);
    const info = m.add(proj);
    expect(info.root).toBe(path.resolve(proj));
    expect(info.isGitRepo).toBe(false);
    expect(m.list()).toHaveLength(1);
    expect(m.list()[0]?.name).toBe(path.basename(proj));
  });

  it("flags git repositories (root/.git exists)", () => {
    const dataDir = tmp("data");
    const proj = tmp("proj");
    mkdirSync(path.join(proj, ".git"));
    const m = managerIn(dataDir);
    expect(m.add(proj).isGitRepo).toBe(true);
  });

  it("rejects files and missing paths with not_a_directory", () => {
    const dataDir = tmp("data");
    const file = path.join(tmp("proj"), "some-file.txt");
    writeFileSync(file, "x");
    const m = managerIn(dataDir);
    expect(() => m.add(file)).toThrowError(ProjectValidationError);
    try {
      m.add(file);
    } catch (err) {
      expect((err as ProjectValidationError).code).toBe("not_a_directory");
    }
    expect(() => m.add(path.join(dataDir, "does-not-exist"))).toThrowError(
      /does not exist|not accessible/i,
    );
    expect(m.list()).toHaveLength(0);
  });

  it("re-adding a project updates lastOpenedAt, not duplicated", () => {
    const dataDir = tmp("data");
    const proj = tmp("proj");
    const m = managerIn(dataDir);
    m.add(proj);
    const first = m.list()[0]!;
    m.add(proj);
    const second = m.list()[0]!;
    expect(m.list()).toHaveLength(1);
    expect(second.lastOpenedAt >= first.lastOpenedAt).toBe(true);
    expect(second.addedAt).toBe(first.addedAt);
  });

  it("recents survive a new manager instance (persistence)", () => {
    const dataDir = tmp("data");
    const proj = tmp("proj");
    managerIn(dataDir).add(proj);
    const again = managerIn(dataDir);
    expect(again.list().map((p) => p.root)).toEqual([path.resolve(proj)]);
  });
});

describe("ProjectManager remove/touch", () => {
  it("removes a project and clears its store cache; unknown roots are rejected", () => {
    const dataDir = tmp("data");
    const proj = tmp("proj");
    const m = managerIn(dataDir);
    m.add(proj);
    m.remove(path.resolve(proj));
    expect(m.list()).toHaveLength(0);
    expect(() => m.requireKnownRoot(path.resolve(proj))).toThrowError(
      ProjectValidationError,
    );
  });

  it("touch reorders the recents list", async () => {
    const dataDir = tmp("data");
    const a = tmp("projA");
    const b = tmp("projB");
    const m = managerIn(dataDir);
    m.add(a);
    await new Promise((r) => setTimeout(r, 20));
    m.add(b);
    // a was added earlier; touching it makes it most recent
    await new Promise((r) => setTimeout(r, 20));
    m.touch(path.resolve(a));
    expect(m.list().map((p) => p.name)[0]).toBe(path.basename(a));
  });
});

describe("ProjectManager conversation stores", () => {
  it("creates, lists, renames and deletes conversations per project", async () => {
    const dataDir = tmp("data");
    const proj = tmp("proj");
    const m = managerIn(dataDir);
    m.add(proj);
    const root = path.resolve(proj);

    const convs = await m.listConversations(root);
    expect(convs).toEqual([]);

    const opened = await m.store(root);
    const id = await opened.store.createConversation(root, "fast");
    await opened.store.appendMessages(id, [
      { role: "user", content: "fix the failing test please" },
    ]);

    const listed = await m.listConversations(root);
    expect(listed).toHaveLength(1);
    expect(listed[0]?.title).toBe("fix the failing test please");
    expect(listed[0]?.model).toBe("fast");

    expect(await opened.store.renameConversation(id, "renamed")).toBe(true);
    expect((await m.listConversations(root))[0]?.title).toBe("renamed");

    expect(await opened.store.deleteConversation(id)).toBe(true);
    expect(await m.listConversations(root)).toEqual([]);
  });

  it("persists per project under the user-data dir (outside the workspace)", async () => {
    const dataDir = tmp("data");
    const proj = tmp("proj");
    const m = managerIn(dataDir);
    m.add(proj);
    const opened = await m.store(path.resolve(proj));
    expect(path.relative(proj, opened.dbDir).startsWith("..")).toBe(true);
    expect(opened.dbDir.startsWith(dataDir)).toBe(true);
  });

  it("conversations of different projects never mix", async () => {
    const dataDir = tmp("data");
    const a = tmp("projA");
    const b = tmp("projB");
    const m = managerIn(dataDir);
    m.add(a);
    m.add(b);
    const storeA = await m.store(path.resolve(a));
    const idA = await storeA.store.createConversation(path.resolve(a), "fast");
    const listB = await m.listConversations(path.resolve(b));
    expect(listB.map((c) => c.id)).not.toContain(idA);
    expect(await m.listConversations(path.resolve(a))).toHaveLength(1);
  });
});
