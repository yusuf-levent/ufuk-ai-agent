/**
 * Playwright Electron smoke test: launches the BUILT app (pnpm build first)
 * and verifies the M3 security baseline + the M4 flow (privacy gate → login)
 * end to end. Uses an isolated APPDATA so the first-run state is fresh on
 * every run. When the gateway is reachable the gate is acknowledged through
 * the UI; otherwise the retryable error state is asserted.
 */
import {
  test,
  expect,
  _electron,
  type ElectronApplication,
} from "@playwright/test";
import { fileURLToPath } from "node:url";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";

const mainJs = fileURLToPath(
  new URL("../../out/main/index.js", import.meta.url),
);

let app: ElectronApplication;
let dataDir: string;

test.beforeAll(async () => {
  dataDir = mkdtempSync(path.join(tmpdir(), "ufuk-e2e-"));
  app = await _electron.launch({
    args: [mainJs],
    env: {
      ...process.env,
      // isolate userData (fresh first-run privacy state) per test run;
      // Electron resolves appData via the Windows known-folder API, so
      // only an explicit setPath (UFUK_USER_DATA_DIR) works
      UFUK_USER_DATA_DIR: dataDir,
    },
  });
});

test.afterAll(async () => {
  await app.close();
  rmSync(dataDir, { recursive: true, force: true });
});

test("window opens with the first-run privacy gate", async () => {
  const win = await app.firstWindow();
  await expect(win).toHaveTitle("Ufuk");
  await expect(
    win.getByRole("heading", { name: /how Ufuk handles your data/i }),
  ).toBeVisible();
});

test("privacy gate acknowledges once and reaches the login screen", async () => {
  const win = await app.firstWindow();
  const checkbox = win.locator('input[type="checkbox"]');
  const errorBox = win.getByRole("alert");
  // backend reachable -> info loads; backend down -> retryable error state
  const first = await Promise.race([
    checkbox.waitFor({ state: "visible", timeout: 15_000 }).then(() => "gate"),
    errorBox.waitFor({ state: "visible", timeout: 15_000 }).then(() => "error"),
  ]);
  if (first === "error") {
    // documented prerequisite (docker compose up) not met on this machine
    test.skip(true, "gateway unreachable: privacy gate shows the error state");
  }
  await checkbox.click();
  const continueBtn = win.getByRole("button", { name: "Continue" });
  await expect(continueBtn).toBeEnabled();
  await continueBtn.click();
  // logged out -> login screen
  await expect(
    win.getByRole("button", { name: "Log in", exact: true }),
  ).toBeVisible();
  // gate stays acknowledged: no privacy heading anymore
  await expect(
    win.getByRole("heading", { name: /how Ufuk handles your data/i }),
  ).toHaveCount(0);
});

test("renderer hardening is active", async () => {
  const win = await app.firstWindow();
  // sandbox: no node globals leak into the renderer
  const hasNode = await win.evaluate(
    () =>
      typeof (window as unknown as Record<string, unknown>)["require"] !==
        "undefined" ||
      typeof (window as unknown as Record<string, unknown>)["process"] !==
        "undefined",
  );
  expect(hasNode).toBe(false);
  // the preload bridge is the only exposed surface
  const bridge = await win.evaluate(
    () => typeof (window as unknown as Record<string, unknown>)["ufuk"],
  );
  expect(bridge).toBe("object");
});

test("BrowserWindow webPreferences match the security baseline", async () => {
  const prefs = await app.evaluate(({ BrowserWindow }) => {
    const win = BrowserWindow.getAllWindows()[0];
    // webPreferences is a getter (does not survive serialization);
    // getLastWebPreferences() returns a plain object (untyped in electron.d.ts).
    const wc = win?.webContents as unknown as {
      getLastWebPreferences?: () => Record<string, unknown>;
    };
    const p = wc.getLastWebPreferences?.() ?? null;
    return p
      ? {
          contextIsolation: p["contextIsolation"],
          nodeIntegration: p["nodeIntegration"],
          sandbox: p["sandbox"],
          webSecurity: p["webSecurity"],
        }
      : null;
  });
  expect(prefs).toMatchObject({
    contextIsolation: true,
    nodeIntegration: false,
    sandbox: true,
    webSecurity: true,
  });
});

test("CSP meta tag is present and strict", async () => {
  const win = await app.firstWindow();
  const csp = await win.evaluate(() => {
    const meta = document.querySelector(
      'meta[http-equiv="Content-Security-Policy"]',
    );
    return meta?.getAttribute("content") ?? null;
  });
  expect(csp).not.toBeNull();
  expect(csp).toContain("script-src 'self'");
  expect(csp).not.toContain("unsafe-eval");
  expect(csp).not.toContain("unsafe-inline");
});

test("window.open is blocked by the main process", async () => {
  const win = await app.firstWindow();
  const opened = await win.evaluate(
    () =>
      (window as unknown as { open?: (u: string) => Window | null }).open?.(
        "https://example.com",
      ) ?? null,
  );
  expect(opened).toBeNull();
  // still exactly one window/page
  expect(app.windows().length).toBe(1);
});

test("all navigation away from the app is blocked (M9)", async () => {
  const win = await app.firstWindow();
  const urlBefore = win.url();
  const result = await win.evaluate(() => {
    // renderer tries to navigate: link click, location assignment
    const a = document.createElement("a");
    a.href = "https://evil.example/";
    document.body.appendChild(a);
    a.click();
    try {
      window.location.assign("https://evil.example/assign");
    } catch {
      // assign may throw in some contexts — the block still counts
    }
    return window.location.href;
  });
  await win.waitForTimeout(300);
  // the renderer never navigated away
  expect(win.url()).toBe(urlBefore);
  expect(result).not.toContain("evil.example");
});

test("IPC payloads are zod-validated in main (M9)", async () => {
  const win = await app.firstWindow();
  const bad = await win.evaluate(async () => {
    const ufuk = (window as unknown as {
      ufuk: { invoke: (c: string, p?: unknown) => Promise<unknown> };
    }).ufuk;
    // schema-violating payloads are rejected with invalid_request
    return (await ufuk.invoke("chat:send", {
      root: "",
      conversationId: "",
      message: "",
    })) as { ok: boolean; error?: { code?: string } };
  });
  expect(bad.ok).toBe(false);
  expect(bad.error?.code).toBe("invalid_request");
  // structurally wrong payloads too
  const wrong = await win.evaluate(async () => {
    const ufuk = (window as unknown as {
      ufuk: { invoke: (c: string, p?: unknown) => Promise<unknown> };
    }).ufuk;
    return (await ufuk.invoke("settings:set", {
      theme: "neon",
      permissionMode: "allow-everything",
    })) as { ok: boolean; error?: { code?: string } };
  });
  expect(wrong.ok).toBe(false);
  expect(wrong.error?.code).toBe("invalid_request");
});

test("IPC round-trip: version channel works through the bridge", async () => {
  const win = await app.firstWindow();
  const result = await win.evaluate(async () => {
    const ufuk = (
      window as unknown as {
        ufuk: { invoke: (c: string) => Promise<unknown> };
      }
    ).ufuk;
    return (await ufuk.invoke("app:version")) as {
      ok: boolean;
      value: { version: string; electron: string };
    };
  });
  expect(result.ok).toBe(true);
  expect(result.value.version).toBeTruthy();
});

test("IPC channel allowlist: unknown channels are rejected by the preload", async () => {
  const win = await app.firstWindow();
  const rejected = await win.evaluate(async () => {
    const ufuk = (
      window as unknown as {
        ufuk: { invoke: (c: string, p?: unknown) => Promise<unknown> };
      }
    ).ufuk;
    try {
      await ufuk.invoke("evil:channel", { anything: true });
      return false;
    } catch {
      return true;
    }
  });
  expect(rejected).toBe(true);
});

test("projects + conversations work end to end through the real main process", async () => {
  const win = await app.firstWindow();
  const projectDir = mkdtempSync(path.join(tmpdir(), "ufuk-e2e-proj-"));
  const result = await win.evaluate<
    {
      added: { root: string; isGitRepo: boolean };
      listLen: number;
      created: { id: string; title: string; model: string };
      renamed: boolean;
      deleted: boolean;
      afterDeleteLen: number;
    },
    string
  >(async (dir) => {
    const ufuk = (
      window as unknown as {
        ufuk: {
          invoke: (
            c: string,
            p?: unknown,
          ) => Promise<{
            ok: boolean;
            value?: unknown;
            error?: { message: string; code?: string };
          }>;
        };
      }
    ).ufuk;
    const call = (c: string, p?: unknown) => ufuk.invoke(c, p);
    const unwrap = async (
      r: Promise<{ ok: boolean; value?: unknown; error?: { message: string } }>,
    ): Promise<unknown> => {
      const res = await r;
      if (!res.ok) throw new Error(res.error?.message ?? "ipc failed");
      return res.value;
    };
    const added = (await unwrap(call("projects:add", { path: dir }))) as {
      root: string;
      isGitRepo: boolean;
    };
    const list = (await unwrap(
      call("conversations:list", { root: added.root }),
    )) as unknown[];
    const created = (await unwrap(
      call("conversations:create", { root: added.root }),
    )) as { id: string; title: string; model: string };
    const renamed = (await unwrap(
      call("conversations:rename", {
        root: added.root,
        id: created.id,
        title: "renamed by e2e",
      }),
    )) as boolean;
    const deleted = (await unwrap(
      call("conversations:delete", { root: added.root, id: created.id }),
    )) as boolean;
    const afterDelete = (await unwrap(
      call("conversations:list", { root: added.root }),
    )) as unknown[];
    return {
      added,
      listLen: list.length,
      created,
      renamed,
      deleted,
      afterDeleteLen: afterDelete.length,
    };
  }, projectDir);
  expect(result.added.isGitRepo).toBe(false);
  expect(result.added.root.length).toBeGreaterThan(0);
  expect(result.listLen).toBe(0);
  expect(result.created.model).toBe("fast");
  expect(result.created.title).toBe("new conversation");
  expect(result.renamed).toBe(true);
  expect(result.deleted).toBe(true);
  expect(result.afterDeleteLen).toBe(0);
  rmSync(projectDir, { recursive: true, force: true });
});
