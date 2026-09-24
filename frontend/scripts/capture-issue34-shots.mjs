// screenshot capture for the Issue 3/4 docs: the credit indicator
// (remaining-first label + breakdown popover) and the bottom-left
// account/settings area. Uses the e2e account (pro plan -> real usage).
import { _electron } from "@playwright/test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MAIN_JS = path.resolve(HERE, "../out/main/index.js");
// scripts/ is one level below tests/e2e — the docs live TWO levels up
const SCREENSHOTS = path.resolve(HERE, "../../docs/screenshots");

const USER_EMAIL = "ufuk-e2e@example.com";
const USER_PASSWORD = "UfukE2E-2026";

const dataDir = mkdtempSync(path.join(tmpdir(), "ufuk-shot-"));
const app = await _electron.launch({
  args: [MAIN_JS],
  env: { ...process.env, UFUK_USER_DATA_DIR: dataDir },
});
const win = await app.firstWindow();

// gate (fresh dir)
await win
  .getByRole("heading", { name: /how Ufuk handles your data/i })
  .waitFor({ state: "visible", timeout: 30_000 });
await win.locator('input[type="checkbox"]').check();
await win.getByRole("button", { name: "Continue" }).click();

// login (e2e account has the pro plan -> usage numbers)
await win
  .getByRole("button", { name: "Log in", exact: true })
  .waitFor({ timeout: 20_000 });
await win.getByPlaceholder("you@example.com").fill(USER_EMAIL);
await win.locator('input[type="password"]').fill(USER_PASSWORD);
await win.getByRole("button", { name: "Log in", exact: true }).click();

// main shell — wait for the credit indicator to load from /usage
await win
  .getByRole("tab", { name: "Chat" })
  .waitFor({ state: "visible", timeout: 30_000 });
await win
  .getByLabel("Credits")
  .waitFor({ state: "visible", timeout: 20_000 });
await win.waitForTimeout(500);

// 11: remaining-first credit indicator in the header
await win.screenshot({ path: path.join(SCREENSHOTS, "11-credits-remaining.png") });

// 12: the click breakdown (plan/used/remaining/reset)
await win.getByLabel("Credits").click();
await win.waitForTimeout(300);
await win.screenshot({ path: path.join(SCREENSHOTS, "12-credits-breakdown.png") });

// 13: bottom-left account area (avatar + email + gear) and the dialog
await win.getByLabel("Settings").click();
await win.waitForTimeout(300);
await win.screenshot({ path: path.join(SCREENSHOTS, "13-settings-bottom-left.png") });

console.log("screenshots captured");
await app.close();
rmSync(dataDir, { recursive: true, force: true });
process.exit(0);
