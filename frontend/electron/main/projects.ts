/**
 * Project manager (main process). Owns:
 * - the recent-projects list (JSON in userData/projects.json)
 * - validation of added folders (must be a real directory; safe workspace root)
 * - the per-project ConversationStore (SQLite preferred, JSONL fallback —
 *   same engine the CLI uses), cached per workspace hash
 * - the git-repo probe (informational warning in the UI)
 *
 * The renderer never touches the filesystem: everything goes through the
 * projects and conversations IPC channels.
 */
import { existsSync, statSync } from "node:fs";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import * as path from "node:path";
import { z } from "zod";
import {
  openConversationStore,
  ShadowCheckpointStore,
  WorkspaceRoot,
  type OpenedStore,
} from "@evren/local-runner";
import type { ConversationSummary } from "@evren/agent-core";

/** Per-project permission mode ('ask' | 'auto-edits'). */
export type PermissionMode = "ask" | "auto-edits";

/** Serialized recent-projects entry (userData/projects.json). */
export interface ProjectEntry {
  root: string;
  name: string;
  addedAt: string;
  lastOpenedAt: string;
  /** Per-project override; undefined = use the global setting. */
  permissionMode?: PermissionMode;
}

/** What the renderer sees. */
export interface ProjectInfo extends ProjectEntry {
  isGitRepo: boolean;
}

export class ProjectValidationError extends Error {
  constructor(
    public code: "not_a_directory" | "path_unsafe",
    message: string,
  ) {
    super(message);
  }
}

const ProjectFileSchema = z.object({
  projects: z.array(
    z.object({
      root: z.string().min(1),
      name: z.string().min(1),
      addedAt: z.string().min(1),
      lastOpenedAt: z.string().min(1),
      permissionMode: z.enum(["ask", "auto-edits"]).optional(),
    }),
  ),
});

export class ProjectManager {
  private readonly file: string;
  private readonly baseDir: string;
  private entries: ProjectEntry[] | null = null;
  private readonly stores = new Map<string, Promise<OpenedStore>>();
  private readonly checkpointStores = new Map<string, ShadowCheckpointStore>();

  constructor(
    private readonly userDataDir: string,
    /** Injectable for tests. */
    private readonly deps: {
      statSync?: (p: string) => { isDirectory(): boolean };
      existsSync?: (p: string) => boolean;
    } = {},
  ) {
    this.file = path.join(userDataDir, "projects.json");
    this.baseDir = path.join(userDataDir, "db");
  }

  /** Recent projects, most recently opened first, with git-repo flag. */
  list(): ProjectInfo[] {
    return this.load()
      .slice()
      .sort((a, b) => (a.lastOpenedAt < b.lastOpenedAt ? 1 : -1))
      .map((e) => ({ ...e, isGitRepo: this.probeGit(e.root) }));
  }

  /** Validate and remember a project folder. Returns the stored entry. */
  add(folderPath: string): ProjectInfo {
    const abs = path.resolve(folderPath);
    const stat = this.deps.statSync ?? statSync;
    let isDir: boolean;
    try {
      isDir = stat(abs).isDirectory();
    } catch {
      throw new ProjectValidationError(
        "not_a_directory",
        `Folder does not exist or is not accessible: ${abs}`,
      );
    }
    if (!isDir) {
      throw new ProjectValidationError(
        "not_a_directory",
        `Not a folder: ${abs}`,
      );
    }
    // WorkspaceRoot performs the native realpath safety check (throws on
    // inaccessible roots); the isDirectory check above catches files.
    let root: WorkspaceRoot;
    try {
      root = new WorkspaceRoot(abs);
    } catch (err) {
      throw new ProjectValidationError(
        "path_unsafe",
        err instanceof Error ? err.message : String(err),
      );
    }
    const now = new Date().toISOString();
    const entries = this.load();
    const existing = entries.find((e) => e.root === root.root);
    const entry: ProjectEntry = {
      root: root.root,
      name: path.basename(root.root) || root.root,
      addedAt: existing?.addedAt ?? now,
      lastOpenedAt: now,
      permissionMode: existing?.permissionMode,
    };
    const next = existing
      ? entries.map((e) => (e.root === entry.root ? entry : e))
      : [...entries, entry];
    this.save(next);
    return { ...entry, isGitRepo: this.probeGit(root.root) };
  }

  /** Forget a project (its conversations stay on disk, untouched). */
  remove(root: string): void {
    const normalized = path.resolve(root);
    this.save(this.load().filter((e) => e.root !== normalized));
    this.stores.delete(normalized);
  }

  /** Mark a project as opened now (drives the recents ordering). */
  touch(root: string): void {
    const normalized = path.resolve(root);
    const entries = this.load();
    const entry = entries.find((e) => e.root === normalized);
    if (!entry) return;
    entry.lastOpenedAt = new Date().toISOString();
    this.save(entries);
  }

  /** Set the per-project permission mode (ask / auto-edits). */
  setPermissionMode(root: string, mode: PermissionMode): ProjectInfo | null {
    const normalized = path.resolve(root);
    const entries = this.load();
    const entry = entries.find((e) => e.root === normalized);
    if (!entry) return null;
    entry.permissionMode = mode;
    this.save(entries);
    return { ...entry, isGitRepo: this.probeGit(normalized) };
  }

  /** The per-project mode, falling back to the global setting. */
  effectivePermissionMode(
    root: string,
    globalMode: PermissionMode,
  ): PermissionMode {
    const normalized = path.resolve(root);
    return (
      this.load().find((e) => e.root === normalized)?.permissionMode ??
      globalMode
    );
  }

  /** The checkpoint store for a project (same dir the agent runtime uses). */
  async checkpoints(root: string): Promise<ShadowCheckpointStore> {
    const workspace = this.requireKnownRoot(root);
    let store = this.checkpointStores.get(workspace.root);
    if (!store) {
      const opened = await this.store(root);
      store = new ShadowCheckpointStore(
        workspace,
        path.join(opened.dbDir, "checkpoints"),
      );
      this.checkpointStores.set(workspace.root, store);
    }
    return store;
  }

  /** The conversation store for a known project root (cached). */
  store(root: string): Promise<OpenedStore> {
    const normalized = path.resolve(root);
    let opened = this.stores.get(normalized);
    if (!opened) {
      const workspace = new WorkspaceRoot(normalized);
      opened = openConversationStore(workspace, { baseDir: this.baseDir });
      this.stores.set(normalized, opened);
      // on failure, drop the cache entry so a later call can retry
      opened.catch(() => this.stores.delete(normalized));
    }
    return opened;
  }

  /** Validate a renderer-supplied project root before using it. */
  requireKnownRoot(root: string): WorkspaceRoot {
    const normalized = path.resolve(root);
    const known = this.load().some((e) => e.root === normalized);
    if (!known) {
      throw new ProjectValidationError(
        "not_a_directory",
        `Unknown project: ${normalized}`,
      );
    }
    try {
      return new WorkspaceRoot(normalized);
    } catch (err) {
      throw new ProjectValidationError(
        "not_a_directory",
        err instanceof Error ? err.message : String(err),
      );
    }
  }

  async listConversations(root: string): Promise<ConversationSummary[]> {
    const workspace = this.requireKnownRoot(root);
    const opened = await this.store(root);
    return opened.store.listConversations(workspace.root, 200);
  }

  private probeGit(root: string): boolean {
    const exists = this.deps.existsSync ?? existsSync;
    try {
      return exists(path.join(path.resolve(root), ".git"));
    } catch {
      return false;
    }
  }

  private load(): ProjectEntry[] {
    if (this.entries) return this.entries;
    let raw: unknown = { projects: [] };
    try {
      raw = JSON.parse(readFileSync(this.file, "utf8"));
    } catch {
      raw = { projects: [] };
    }
    const parsed = ProjectFileSchema.safeParse(raw);
    this.entries = parsed.success ? parsed.data.projects : [];
    return this.entries;
  }

  private save(entries: ProjectEntry[]): void {
    this.entries = entries;
    mkdirSync(path.dirname(this.file), { recursive: true });
    writeFileSync(
      this.file,
      JSON.stringify({ projects: entries }, null, 2),
      "utf8",
    );
  }
}
