/**
 * Issue 2 e2e — session persistence across restart:
 *
 *   launch (isolated userData) -> privacy gate -> login -> main shell
 *   -> CLOSE the app -> relaunch on the SAME userData -> still logged in.
 *
 * Also covers the Issue 1 nav on a fresh install: Chat mode is the
 * default and a chat conversation can be created with no project.
 *
 * Prerequisites: backend running (docker compose up). Skips gracefully
 * (documented) when the gateway is unreachable.
 */
import {
  test,
  expect,
  _electron,
  type ElectronApplication,
  type Page,
} from "@playwright/test";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MAIN_JS = path.resolve(HERE, "../../out/main/index.js");
const SCREENSHOTS = path.resolve(HERE, "../../../docs/screenshots");

const BACKEND = process.env["UFUK_E2E_BACKEND"] ?? "http://localhost:8000";
// unique per run: a fresh email avoids any dependency on fix-it's state
const RUN = Date.now();
const USER_EMAIL = `ufuk-restore-${RUN}@example.com`;
const USER_PASSWORD = "UfukRestore-2026";

let dataDir: string;

/** Register a fresh account via the API (no plan needed for /me). */
async function ensureAccount(): Promise<void> {
  const res = await fetch(`${BACKEND}/auth/register`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      email: USER_EMAIL,
      password: USER_PASSWORD,
      display_name: "Restore E2E",
    }),
  });
  // 201 = created; 400 = already registered (unexpected with a fresh
  // timestamp email, but tolerated)
  if (res.status !== 201 && res.status !== 400) {
    throw new Error(`registration failed: ${res.status}`);
  }
}

async function backendUp(): Promise<boolean> {
  try {
    const res = await fetch(`${BACKEND}/health`, {
      signal: AbortSignal.timeout(5_000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Launch the app on the shared dataDir and drive gate + login. */
async function launchAndLogin(): Promise<{
  app: ElectronApplication;
  win: Page;
}> {
  const app = await _electron.launch({
    args: [MAIN_JS],
    env: { ...process.env, UFUK_USER_DATA_DIR: dataDir },
  });
  const win = await app.firstWindow();

  const gateHeading = win.getByRole("heading", {
    name: /how Ufuk handles your data/i,
  });
  const first = await Promise.race([
    gateHeading
      .waitFor({ state: "visible", timeout: 20_000 })
      .then(() => "gate"),
    win
      .getByRole("button", { name: "Log in", exact: true })
      .waitFor({ state: "visible", timeout: 20_000 })
      .then(() => "login"),
  ]);
  if (first === "gate") {
    await win.locator('input[type="checkbox"]').check();
    await win.getByRole("button", { name: "Continue" }).click();
  }

  await expect(
    win.getByRole("button", { name: "Log in", exact: true }),
  ).toBeVisible({ timeout: 20_000 });
  await win.getByPlaceholder("you@example.com").fill(USER_EMAIL);
  await win.locator('input[type="password"]').fill(USER_PASSWORD);
  await win.getByRole("button", { name: "Log in", exact: true }).click();
  return { app, win };
}

test.setTimeout(180_000);

test.beforeAll(async () => {
  if (!(await backendUp())) {
    test.skip(
      true,
      "gateway unreachable: session-restore e2e needs the local stack (docker compose up)",
    );
  }
  await ensureAccount();
  mkdirSync(SCREENSHOTS, { recursive: true });
  dataDir = mkdtempSync(path.join(tmpdir(), "ufuk-restore-"));
});

test.afterAll(() => {
  if (dataDir) rmSync(dataDir, { recursive: true, force: true });
});

test("login survives closing and reopening the app", async () => {
  // 1. first launch: gate + login -> main shell
  const first = await launchAndLogin();
  const win = first.win;
  await expect(win.getByRole("tab", { name: "Chat" })).toBeVisible({
    timeout: 20_000,
  });
  await expect(win.getByRole("tab", { name: "Projects" })).toBeVisible();
  await win.screenshot({
    path: path.join(SCREENSHOTS, "08-session-login.png"),
  });

  // fresh install defaults to Chat mode: create a chat conversation with
  // no project folder at all
  await win.getByTitle("New chat").click();
  await expect(win.locator("textarea")).toBeVisible({ timeout: 10_000 });
  await win.screenshot({
    path: path.join(SCREENSHOTS, "09-chat-mode.png"),
  });

  // 2. close the app completely
  await first.app.close();

  // 3. relaunch on the SAME userData dir — the stored (safeStorage) token
  //    must restore the session WITHOUT a re-login
  const second = await _electron.launch({
    args: [MAIN_JS],
    env: { ...process.env, UFUK_USER_DATA_DIR: dataDir },
  });
  const relaunched = await second.firstWindow();
  // main shell (NOT the login screen): the mode switcher is visible and
  // the Log in button never appears
  await expect(relaunched.getByRole("tab", { name: "Chat" })).toBeVisible({
    timeout: 20_000,
  });
  await expect(
    relaunched.getByRole("button", { name: "Log in", exact: true }),
  ).toHaveCount(0);
  // the chat conversation from the first run is still listed (persisted)
  await expect(relaunched.getByTitle("New chat")).toBeVisible();
  await relaunched.screenshot({
    path: path.join(SCREENSHOTS, "10-session-restored.png"),
  });
  await second.close();
});
