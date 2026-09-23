/**
 * Milestone 10 E2E — the full product scenario against the REAL local
 * stack (docker compose backend on :8000, REAL upstream model provider):
 *
 *   login -> add sample project -> "The test in this repo is failing.
 *   Fix it and verify." -> approve edit + npm test -> see diff -> undo.
 *
 * Prerequisites: backend running (docker compose up), database seeded.
 * The test account is created via the API (admin assigns the pro plan).
 * Screenshots are saved to docs/screenshots.
 */
import {
  test,
  expect,
  _electron,
  type ElectronApplication,
  type Page,
} from "@playwright/test";
import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MAIN_JS = path.resolve(HERE, "../../out/main/index.js");
const SAMPLE_REPO = path.resolve(
  HERE,
  "../../../evren-agent/apps/cli/fixtures/sample-repo",
);
const SCREENSHOTS = path.resolve(HERE, "../../../docs/screenshots");

const BACKEND = process.env["UFUK_E2E_BACKEND"] ?? "http://localhost:8000";
const USER_EMAIL = "ufuk-e2e@example.com";
const USER_PASSWORD = "UfukE2E-2026";
const ADMIN_EMAIL = "live-admin@example.com";
const ADMIN_PASSWORD = "admin-test-12345";

/** Register (idempotent) + ensure an active subscription; returns nothing. */
async function ensureAccount(): Promise<void> {
  const register = async (email: string, password: string): Promise<void> => {
    await fetch(`${BACKEND}/auth/register`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password, display_name: "Ufuk E2E" }),
    }).catch(() => undefined); // 400 = already registered
  };
  await register(ADMIN_EMAIL, ADMIN_PASSWORD);
  await register(USER_EMAIL, USER_PASSWORD);

  const login = async (
    email: string,
    password: string,
  ): Promise<{ access_token: string }> => {
    const res = await fetch(`${BACKEND}/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) throw new Error(`login failed for ${email}: ${res.status}`);
    return (await res.json()) as { access_token: string };
  };

  const user = await login(USER_EMAIL, USER_PASSWORD);
  const usageRes = await fetch(`${BACKEND}/usage`, {
    headers: { authorization: `Bearer ${user.access_token}` },
  });
  if (usageRes.ok) return; // already subscribed

  const admin = await login(ADMIN_EMAIL, ADMIN_PASSWORD);
  const plansRes = await fetch(`${BACKEND}/plans`);
  const plans = (await plansRes.json()) as Array<{
    id: string;
    name: string;
    allowed_tier_aliases: string[];
  }>;
  const plan =
    plans.find((p) => p.allowed_tier_aliases.length >= 3) ?? plans[0];
  if (!plan) throw new Error("no plans seeded — run scripts/seed.py");

  const meRes = await fetch(`${BACKEND}/me`, {
    headers: { authorization: `Bearer ${user.access_token}` },
  });
  const me = (await meRes.json()) as { id: string };
  const assignRes = await fetch(
    `${BACKEND}/admin/users/${me.id}/subscriptions`,
    {
      method: "POST",
      headers: {
        authorization: `Bearer ${admin.access_token}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ plan_id: plan.id }),
    },
  );
  if (!assignRes.ok && assignRes.status !== 409) {
    throw new Error(`plan assignment failed: ${assignRes.status}`);
  }
}

let app: ElectronApplication;
let win: Page;
let dataDir: string;
let projectDir: string;

test.setTimeout(420_000);

test.beforeAll(async () => {
  await ensureAccount();
  mkdirSync(SCREENSHOTS, { recursive: true });

  // fresh copy of the sample repo for every run (named sample-repo so the
  // sidebar shows a recognizable project name)
  const tempBase = mkdtempSync(path.join(tmpdir(), "ufuk-e2e-"));
  projectDir = path.join(tempBase, "sample-repo");
  cpSync(SAMPLE_REPO, projectDir, { recursive: true });

  dataDir = mkdtempSync(path.join(tmpdir(), "ufuk-e2e-app-"));
  app = await _electron.launch({
    args: [MAIN_JS],
    env: { ...process.env, UFUK_USER_DATA_DIR: dataDir },
  });
  win = await app.firstWindow();
  // stub the native folder picker (cannot be driven headlessly otherwise)
  await app.evaluate(({ dialog }, dir) => {
    dialog.showOpenDialog = async () => ({
      canceled: false,
      filePaths: [dir],
    });
  }, projectDir);
});

test.afterAll(async () => {
  await app.close();
  rmSync(dataDir, { recursive: true, force: true });
  // keep projectDir for inspection; temp cleaner removes it eventually
});

const shot = async (name: string): Promise<void> => {
  await win.screenshot({ path: path.join(SCREENSHOTS, name) });
};

/** Approve every permission modal until the run finishes. */
async function approveUntilDone(maxMs = 300_000): Promise<void> {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    const allow = win.getByRole("button", { name: "Allow once", exact: true });
    if (await allow.isVisible().catch(() => false)) {
      await allow.click();
      continue;
    }
    // run finished when the Send button is back
    const send = win.getByRole("button", { name: "Send", exact: true });
    const running = await win
      .getByRole("button", { name: /Stop/ })
      .isVisible()
      .catch(() => false);
    if ((await send.isVisible().catch(() => false)) && !running) {
      return;
    }
    await win.waitForTimeout(500);
  }
  throw new Error("run did not finish in time");
}

test("full scenario: login -> fix the failing test -> diff -> undo", async () => {
  // 1. first-run privacy gate
  await expect(
    win.getByRole("heading", { name: /how Ufuk handles your data/i }),
  ).toBeVisible({ timeout: 30_000 });
  await shot("01-privacy-gate.png");
  await win.locator('input[type="checkbox"]').check();
  await win.getByRole("button", { name: "Continue" }).click();

  // 2. login
  await expect(
    win.getByRole("button", { name: "Log in", exact: true }),
  ).toBeVisible();
  await shot("02-login.png");
  await win.getByPlaceholder("you@example.com").fill(USER_EMAIL);
  await win.locator('input[type="password"]').fill(USER_PASSWORD);
  await win.getByRole("button", { name: "Log in", exact: true }).click();

  // 3. main shell -> add the sample project (picker stubbed)
  await expect(win.getByRole("button", { name: "+ Add" })).toBeVisible({
    timeout: 30_000,
  });
  await shot("03-main-shell.png");
  await win.getByRole("button", { name: "+ Add" }).click();
  await expect(
    win.getByRole("button", { name: /sample-repo/ }).first(),
  ).toBeVisible({ timeout: 15_000 });

  // 4. new conversation + send the task
  await win.getByRole("button", { name: "+ New" }).click();
  const composer = win.locator("textarea");
  await expect(composer).toBeVisible();
  await composer.fill("The test in this repo is failing. Fix it and verify.");
  await shot("04-task-sent.png");
  await composer.press("Enter");

  // 5. approve the edit + the test run (modal per permission request)
  await approveUntilDone();
  await shot("05-run-finished.png");

  // 6. the fix landed: sum.js now adds
  const sumFixed = readFileSync(path.join(projectDir, "sum.js"), "utf8");
  expect(sumFixed).toContain("a + b");

  // 7. the conversation got a real title from the first user message
  await expect(
    win.getByText(/test in this repo is failing/i).first(),
  ).toBeVisible();

  // 8. see the diff (changed-files panel)
  await win.getByRole("button", { name: "Changed files" }).click();
  const fileButton = win.getByTitle(
    "Show diff against the pre-change snapshot",
  );
  await expect(fileButton).toBeVisible({ timeout: 15_000 });
  await fileButton.click();
  const diffDialog = win.getByRole("dialog", { name: "Diff viewer" });
  await expect(diffDialog).toBeVisible();
  // the diff shows the removed buggy line and the added fixed line
  await expect(diffDialog.getByText(/return a - b/)).toBeVisible();
  await expect(diffDialog.getByText(/return a \+ b/)).toBeVisible();
  await shot("06-diff.png");
  await diffDialog.getByRole("button", { name: "Close diff" }).click();

  // 9. undo the last change (checkpoint history)
  await win.getByRole("button", { name: "History" }).click();
  await win.getByRole("button", { name: /Undo last change/ }).click();
  await expect(win.getByText(/Undid /)).toBeVisible({ timeout: 15_000 });
  await shot("07-undo.png");

  // the workspace file is back to the broken version
  const sumRestored = readFileSync(path.join(projectDir, "sum.js"), "utf8");
  expect(sumRestored).toContain("a - b");

  // 10. changed-files list reflects the conversation's tool calls
  expect(existsSync(path.join(SCREENSHOTS, "01-privacy-gate.png"))).toBe(true);
});
