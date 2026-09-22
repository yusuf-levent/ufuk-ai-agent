/**
 * Playwright Electron smoke test: launches the BUILT app (pnpm build first)
 * and verifies the M3 security baseline end to end.
 */
import { test, expect, _electron, type ElectronApplication } from "@playwright/test";
import { fileURLToPath } from "node:url";

const mainJs = fileURLToPath(new URL("../../out/main/index.js", import.meta.url));

let app: ElectronApplication;

test.beforeAll(async () => {
  app = await _electron.launch({ args: [mainJs] });
});

test.afterAll(async () => {
  await app.close();
});

test("window opens with the Ufuk shell", async () => {
  const win = await app.firstWindow();
  await expect(win).toHaveTitle("Ufuk");
  await expect(win.getByRole("heading", { name: "Ufuk", exact: true })).toBeVisible();
});

test("renderer hardening is active", async () => {
  const win = await app.firstWindow();
  // sandbox: no node globals leak into the renderer
  const hasNode = await win.evaluate(
    () =>
      typeof (window as unknown as Record<string, unknown>)["require"] !== "undefined" ||
      typeof (window as unknown as Record<string, unknown>)["process"] !== "undefined",
  );
  expect(hasNode).toBe(false);
  // the preload bridge is the only exposed surface
  const bridge = await win.evaluate(() => typeof (window as unknown as Record<string, unknown>)["ufuk"]);
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
    const meta = document.querySelector('meta[http-equiv="Content-Security-Policy"]');
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

test("IPC round-trip: version channel works through the bridge", async () => {
  const win = await app.firstWindow();
  const result = await win.evaluate(async () => {
    const ufuk = (window as unknown as {
      ufuk: { invoke: (c: string) => Promise<unknown> };
    }).ufuk;
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
    const ufuk = (window as unknown as {
      ufuk: { invoke: (c: string, p?: unknown) => Promise<unknown> };
    }).ufuk;
    try {
      await ufuk.invoke("evil:channel", { anything: true });
      return false;
    } catch {
      return true;
    }
  });
  expect(rejected).toBe(true);
});
