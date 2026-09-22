/**
 * Settings store: a small JSON file in the Electron user-data dir
 * (%APPDATA%/ufuk/settings.json), zod-validated on load with defaults.
 * The renderer can only read/patch it through the settings:get/set IPC.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import * as path from "node:path";
import { SettingsSchema, type Settings, type SettingsPatch } from "@shared/ipc";

export class SettingsStore {
  private readonly file: string;
  private cache: Settings | null = null;

  constructor(userDataDir: string) {
    this.file = path.join(userDataDir, "settings.json");
  }

  load(): Settings {
    if (this.cache) return this.cache;
    let raw: unknown = {};
    if (existsSync(this.file)) {
      try {
        raw = JSON.parse(readFileSync(this.file, "utf8"));
      } catch {
        raw = {}; // corrupt file: fall back to defaults
      }
    }
    const parsed = SettingsSchema.safeParse(raw);
    this.cache = parsed.success ? parsed.data : SettingsSchema.parse({});
    return this.cache;
  }

  patch(patch: SettingsPatch): Settings {
    const next = SettingsSchema.parse({ ...this.load(), ...patch });
    this.cache = next;
    mkdirSync(path.dirname(this.file), { recursive: true });
    writeFileSync(this.file, JSON.stringify(next, null, 2), "utf8");
    return next;
  }
}
