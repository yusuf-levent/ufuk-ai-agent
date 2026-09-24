/**
 * Canonical user-data dir + legacy migration (Issue 2).
 *
 * Root cause of the re-login-after-restart reports: the app's userData
 * directory differed per launch mode — %APPDATA%\Ufuk (packaged),
 * %APPDATA%\ufuk (`pnpm start` resolves the app name from package.json),
 * %APPDATA%\Electron (plain `electron` dev launches) — so tokens,
 * settings, projects and conversation stores were fragmented across
 * three directories and each mode looked "logged out".
 *
 * Fix: pin userData to ONE canonical dir (%APPDATA%\Ufuk, the packaged
 * app's identity) in every launch mode, and merge any legacy dirs into
 * it on boot: for each app file/dir we own (settings.json,
 * projects.json, gateway/, db/), copy the newest existing copy into the
 * canonical dir when it is missing there. Never deletes anything —
 * zero data loss, idempotent, runs in milliseconds.
 */
import { cpSync, existsSync, mkdirSync, statSync } from "node:fs";
import * as path from "node:path";

/** App-owned files/dirs inside userData that participate in the merge. */
export const USER_DATA_KEYS = [
  "settings.json",
  "projects.json",
  "gateway",
  "db",
] as const;

/** Injectable fs surface for tests. */
export interface UserdataFs {
  existsSync(p: string): boolean;
  statSync(p: string): { mtimeMs: number; isDirectory(): boolean };
  cpSync(src: string, dest: string, opts: { recursive: boolean }): void;
  mkdirSync(p: string, opts: { recursive: boolean }): void;
}

const defaultFs: UserdataFs = {
  existsSync,
  statSync,
  cpSync,
  mkdirSync,
};

/**
 * The single canonical userData dir for every launch mode. Same value
 * the packaged app already uses (%APPDATA%\Ufuk), so packaged installs
 * are untouched; `pnpm start` / dev modes stop fragmenting data.
 */
export function canonicalUserDataDir(appDataDir: string): string {
  return path.join(appDataDir, "Ufuk");
}

/**
 * Legacy userData dirs that earlier builds may have written. On Windows
 * (case-insensitive FS) "ufuk" and "Ufuk" are the SAME directory, so the
 * practical legacy set is just "Electron" (plain-electron dev launches);
 * "ufuk" is listed for case-sensitive filesystems and is a no-op on
 * Windows (the canonical dir already matches it).
 */
export function legacyUserDataDirs(appDataDir: string): string[] {
  return [path.join(appDataDir, "ufuk"), path.join(appDataDir, "Electron")];
}

/**
 * Merge legacy dirs into the canonical dir. For every app-owned key:
 * - canonical already has it → untouched (idempotent, no overwrites)
 * - missing in canonical → copied from the legacy dir that has the
 *   newest copy (zero data loss, newest wins)
 *
 * Returns the list of keys that were migrated (for logging/tests).
 */
export function migrateLegacyUserData(
  canonicalDir: string,
  legacyDirs: string[],
  fs: UserdataFs = defaultFs,
): string[] {
  const migrated: string[] = [];
  if (!fs.existsSync(canonicalDir)) {
    fs.mkdirSync(canonicalDir, { recursive: true });
  }
  for (const key of USER_DATA_KEYS) {
    const dest = path.join(canonicalDir, key);
    if (fs.existsSync(dest)) continue; // canonical wins, never overwritten
    let best: { dir: string; mtimeMs: number } | null = null;
    for (const dir of legacyDirs) {
      const src = path.join(dir, key);
      if (!fs.existsSync(src)) continue;
      const mtimeMs = fs.statSync(src).mtimeMs;
      if (!best || mtimeMs > best.mtimeMs) best = { dir, mtimeMs };
    }
    if (best) {
      fs.cpSync(path.join(best.dir, key), dest, { recursive: true });
      migrated.push(key);
    }
  }
  return migrated;
}
