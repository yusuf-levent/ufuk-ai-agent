// diagnostic runner for the fix-it flow (same as the e2e but with console
// capture) — used to debug the intermittent gate-regression
import { _electron } from "@playwright/test";
import { cpSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MAIN_JS = path.resolve(HERE, "../out/main/index.js");
const SAMPLE_REPO = path.resolve(
  HERE,
  "../../evren-agent/apps/cli/fixtures/sample-repo",
);

const BACKEND = process.env["UFUK_E2E_BACKEND"] ?? "http://localhost:8000";
const USER_EMAIL = "ufuk-e2e@example.com";
const USER_PASSWORD = "UfukE2E-2026";

const dataDir = mkdtempSync(path.join(tmpdir(), "ufuk-dbg-"));
const tempBase = mkdtempSync(path.join(tmpdir(), "ufuk-dbg-proj-"));
const projectDir = path.join(tempBase, "sample-repo");
cpSync(SAMPLE_REPO, projectDir, { recursive: true });

const app = await _electron.launch({
  args: [MAIN_JS],
  env: { ...process.env, UFUK_USER_DATA_DIR: dataDir },
});
const win = await app.firstWindow();
win.on("console", (msg) => {
  const t = msg.text();
  if (!t.includes("Download the React DevTools")) {
    console.log("[renderer]", msg.type(), t.slice(0, 300));
  }
});
win.on("pageerror", (err) =>
  console.log("[pageerror]", err.message.slice(0, 300)),
);
await app.evaluate(({ dialog }, dir) => {
  dialog.showOpenDialog = async () => ({
    canceled: false,
    filePaths: [dir],
  });
}, projectDir);

const step = async (name, fn) => {
  try {
    await fn();
    console.log("[step ok]", name);
  } catch (err) {
    console.log("[STEP FAIL]", name, "—", String(err.message).slice(0, 400));
    const state = await win
      .evaluate(() => ({
        url: location.href,
        text: document.body.innerText.slice(0, 400),
      }))
      .catch(() => null);
    console.log("[page state]", JSON.stringify(state, null, 2));
    await app.close();
    rmSync(dataDir, { recursive: true, force: true });
    process.exit(1);
  }
};

await step("gate heading", () =>
  win
    .getByRole("heading", { name: /how Ufuk handles your data/i })
    .waitFor({ state: "visible", timeout: 30_000 }),
);
await step("checkbox", () => win.locator('input[type="checkbox"]').check());
await step("continue", () =>
  win.getByRole("button", { name: "Continue" }).click(),
);
await step("login button", () =>
  win
    .getByRole("button", { name: "Log in", exact: true })
    .waitFor({ state: "visible", timeout: 20_000 }),
);
await step("fill email", () =>
  win.getByPlaceholder("you@example.com").fill(USER_EMAIL),
);
await step("fill password", () =>
  win.locator('input[type="password"]').fill(USER_PASSWORD),
);
await step("login", () =>
  win.getByRole("button", { name: "Log in", exact: true }).click(),
);
await step("projects tab", () =>
  win
    .getByRole("tab", { name: "Projects" })
    .waitFor({ state: "visible", timeout: 30_000 }),
);
const settingsAfterLogin = await win.evaluate(async () => {
  return window.ufuk.invoke("settings:get");
});
console.log("[settings:get after login]", JSON.stringify(settingsAfterLogin));
await step("click projects tab", () =>
  win.getByRole("tab", { name: "Projects" }).click(),
);
await win.waitForTimeout(1500);
// dump the CURRENT settings through the bridge + the raw file via main
const settingsNow = await win.evaluate(async () => {
  return window.ufuk.invoke("settings:get");
});
console.log("[settings:get after tab click]", JSON.stringify(settingsNow));
await step("+ Add visible", () =>
  win
    .getByRole("button", { name: "+ Add" })
    .waitFor({ state: "visible", timeout: 15_000 }),
);
await step("click + Add", () =>
  win.getByRole("button", { name: "+ Add" }).click(),
);
await step("sample-repo visible", () =>
  win
    .getByRole("button", { name: /sample-repo/ })
    .first()
    .waitFor({ state: "visible", timeout: 15_000 }),
);

console.log("ALL STEPS PASSED");
await app.close();
rmSync(dataDir, { recursive: true, force: true });
process.exit(0);
