/**
 * One-time data migrations between app versions. Each migration must be
 * idempotent and must never lose user data — see the nav-rework tests.
 */
import type { SettingsStore } from "./settings";

/**
 * Nav rework (Chat/Projects top-level switch): settings written before
 * the rework have no `activeMode` key. Installs that already contain
 * projects keep landing in Projects mode (their data is all project
 * data); fresh installs keep the schema default (Chat). Project data
 * itself never moves — the rework only adds the mode switch.
 */
export function migrateActiveMode(
  settings: SettingsStore,
  hasProjects: boolean,
): void {
  if (!settings.rawHas("activeMode") && hasProjects) {
    settings.patch({ activeMode: "projects" });
  }
}
