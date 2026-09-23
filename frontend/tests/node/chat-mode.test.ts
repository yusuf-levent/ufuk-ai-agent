// @vitest-environment node
/**
 * Chat mode (nav rework): the app-owned chat workspace behind the
 * CHAT_ROOT_ID sentinel — tool-less by construction — plus the one-time
 * activeMode migration and a zero-data-loss check for pre-rework
 * project data.
 */
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { CHAT_ROOT_ID } from "@shared/ipc";
import {
  ProjectManager,
  ProjectValidationError,
} from "../../electron/main/projects";
import { SettingsStore } from "../../electron/main/settings";
import { migrateActiveMode } from "../../electron/main/migrate";
import {
  createToolRegistry,
  CHAT_SYSTEM_PROMPT,
} from "../../electron/main/agent-runtime";
import { WorkspaceRoot, openConversationStore } from "@evren/local-runner";

const dirs: string[] = [];
const tmp = (): string => {
  const d = mkdtempSync(path.join(tmpdir(), "ufuk-chat-"));
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

describe("ProjectManager chat workspace (CHAT_ROOT_ID)", () => {
  it("maps the sentinel to an app-owned workspace under userData (never a project)", async () => {
    const userData = tmp();
    const pm = new ProjectManager(userData);
    expect(pm.isChatRoot(CHAT_ROOT_ID)).toBe(true);
    expect(pm.isChatRoot("C:\\some\\real\\path")).toBe(false);

    const chatDir = pm.chatRootPath();
    expect(existsSync(chatDir)).toBe(true);
    expect(path.dirname(chatDir)).toBe(userData);

    // the workspace resolves through the same safety path as projects
    const workspace = pm.requireKnownRoot(CHAT_ROOT_ID);
    expect(workspace.root).toBe(chatDir);

    // the sentinel never shows up as a project
    expect(pm.list().some((p) => p.root === chatDir)).toBe(false);
  });

  it("creates and lists chat conversations through the sentinel (separate store)", async () => {
    const userData = tmp();
    const pm = new ProjectManager(userData);

    const opened = await pm.store(CHAT_ROOT_ID);
    const id = await opened.store.createConversation(pm.chatRootPath(), "fast");
    const listed = await pm.listConversations(CHAT_ROOT_ID);
    expect(listed.map((c) => c.id)).toContain(id);

    // messages persist and reload through the sentinel
    await opened.store.appendMessages(id, [
      { role: "user", content: "hello" },
      { role: "assistant", content: "hi there" },
    ]);
    const detail = await opened.store.loadConversation(id);
    expect(detail?.messages.map((m) => m.content)).toEqual([
      "hello",
      "hi there",
    ]);

    // a REAL project gets its own separate store (different db dir)
    const pmProject = new ProjectManager(tmp());
    const projectRoot = path.join(tmp(), "proj");
    mkdirSync(projectRoot, { recursive: true });
    pmProject.add(projectRoot);
    const projectOpened = await pmProject.store(projectRoot);
    expect(projectOpened.dbDir).not.toBe(opened.dbDir);
  });

  it("rejects unknown sentinels that are not the chat root", () => {
    const pm = new ProjectManager(tmp());
    expect(() => pm.requireKnownRoot("ufuk:not-a-thing")).toThrow(
      ProjectValidationError,
    );
  });

  it("touch() is a no-op for the chat root (no recents ordering)", () => {
    const pm = new ProjectManager(tmp());
    expect(() => pm.touch(CHAT_ROOT_ID)).not.toThrow();
    expect(pm.list()).toEqual([]);
  });
});

describe("createToolRegistry (tool-less chat runs)", () => {
  it("registers ZERO tools for chat conversations (no filesystem/shell/git)", () => {
    const userData = tmp();
    const pm = new ProjectManager(userData);
    const workspace = pm.requireKnownRoot(CHAT_ROOT_ID);
    const registry = createToolRegistry(
      workspace,
      path.join(userData, "checkpoints"),
      { chat: true },
    );
    expect(registry.definitions()).toEqual([]);
  });

  it("registers the full file/run_command/git toolset for project runs", () => {
    const dir = tmp();
    const projectRoot = path.join(dir, "proj");
    mkdirSync(projectRoot, { recursive: true });
    const workspace = new WorkspaceRoot(projectRoot);
    const registry = createToolRegistry(workspace, path.join(dir, "cp"), {
      chat: false,
    });
    const names = registry.definitions().map((d) => d.name);
    expect(names).toContain("read_file");
    expect(names).toContain("write_file");
    expect(names).toContain("edit_file");
    expect(names).toContain("run_command");
    expect(names.length).toBeGreaterThan(4);
  });

  it("the chat system prompt states it has no tools and suggests Projects mode", () => {
    expect(CHAT_SYSTEM_PROMPT).toContain("NO tools");
    expect(CHAT_SYSTEM_PROMPT).toContain("Projects mode");
  });
});

describe("activeMode migration (nav rework)", () => {
  it("pre-rework settings with existing projects migrate to projects mode (persisted)", () => {
    const dir = tmp();
    // a settings.json exactly as the pre-rework app wrote it (no activeMode)
    writeFileSync(
      path.join(dir, "settings.json"),
      JSON.stringify({
        backendUrl: "http://localhost:8000",
        theme: "dark",
        defaultTier: "fast",
        permissionMode: "ask",
        privacyAcknowledged: true,
      }),
      "utf8",
    );
    const settings = new SettingsStore(dir);
    expect(settings.load().activeMode).toBe("chat"); // schema default
    migrateActiveMode(settings, true);
    expect(settings.load().activeMode).toBe("projects");
    // persisted: a fresh store sees projects mode, migration is one-time
    const reopened = new SettingsStore(dir);
    expect(reopened.rawHas("activeMode")).toBe(true);
    expect(reopened.load().activeMode).toBe("projects");
    migrateActiveMode(reopened, true); // idempotent
    expect(reopened.load().activeMode).toBe("projects");
  });

  it("pre-rework settings without projects stay on the chat default", () => {
    const dir = tmp();
    writeFileSync(
      path.join(dir, "settings.json"),
      JSON.stringify({ theme: "dark" }),
      "utf8",
    );
    const settings = new SettingsStore(dir);
    migrateActiveMode(settings, false);
    expect(settings.load().activeMode).toBe("chat");
    expect(settings.rawHas("activeMode")).toBe(false); // nothing written
  });
});

describe("zero data loss: pre-rework project data loads unchanged", () => {
  it("a pre-rework userData (settings + project + conversations) keeps working", async () => {
    // build a userData dir shaped like a pre-rework install: settings.json
    // without activeMode, projects.json with one project, and a real
    // conversation store under db/<hash> with messages
    const userData = tmp();
    const projectRoot = path.join(tmp(), "legacy-proj");
    mkdirSync(projectRoot, { recursive: true });

    writeFileSync(
      path.join(userData, "settings.json"),
      JSON.stringify({
        backendUrl: "http://localhost:8000",
        theme: "light",
        defaultTier: "strong",
        permissionMode: "auto-edits",
        privacyAcknowledged: true,
      }),
      "utf8",
    );

    const pm = new ProjectManager(userData);
    pm.add(projectRoot);

    const opened = await openConversationStore(new WorkspaceRoot(projectRoot), {
      baseDir: path.join(userData, "db"),
    });
    const convId = await opened.store.createConversation(projectRoot, "fast");
    await opened.store.appendMessages(convId, [
      { role: "user", content: "fix the test" },
      { role: "assistant", content: "done, tests pass" },
    ]);

    // "restart" with fresh managers (as the migrated app would boot)
    const pm2 = new ProjectManager(userData);
    const settings2 = new SettingsStore(userData);
    migrateActiveMode(settings2, pm2.list().length > 0);

    // settings survived (except the added activeMode key)
    const loaded = settings2.load();
    expect(loaded).toMatchObject({
      theme: "light",
      defaultTier: "strong",
      permissionMode: "auto-edits",
      privacyAcknowledged: true,
      activeMode: "projects", // migrated, everything else untouched
    });

    // the project and its conversations survived with zero loss
    const projects = pm2.list();
    expect(projects).toHaveLength(1);
    expect(projects[0]?.name).toBe(path.basename(projectRoot));
    const conversations = await pm2.listConversations(projectRoot);
    expect(conversations.map((c) => c.id)).toEqual([convId]);
    const detail = await (
      await pm2.store(projectRoot)
    ).store.loadConversation(convId);
    expect(detail?.messages).toEqual([
      { role: "user", content: "fix the test" },
      { role: "assistant", content: "done, tests pass" },
    ]);
  });
});
