/**
 * Ufuk desktop app — main process entry.
 *
 * Architecture (Milestone 3 baseline):
 * - MAIN is the only place with filesystem, shell and network access. It
 *   hosts @evren/agent-core + @evren/local-runner and talks to the backend.
 * - RENDERER is UI-only: contextIsolation, sandbox, no node integration,
 *   strict CSP, navigation/window.open/permission requests all blocked.
 * - PRELOAD exposes exactly two functions (invoke/subscribe) with channel
 *   allowlists; payloads are zod-validated in main, senders are checked.
 */
import { app, BrowserWindow } from "electron";
import * as path from "node:path";
import { registerIpcHandlers } from "./ipc";
import { installSecurityDefaults } from "./security";
import { SettingsStore } from "./settings";
import { buildGatewaySession, type GatewaySession } from "./gateway";
import { ProjectManager } from "./projects";
import { AgentRuntime } from "./agent-runtime";
import { safeStorage } from "electron";

let mainWindow: BrowserWindow | null = null;

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 880,
    minHeight: 600,
    title: "Ufuk",
    backgroundColor: "#0a0a0a",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      spellcheck: false,
    },
  });
  mainWindow.on("ready-to-show", () => mainWindow?.show());
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  if (process.env["ELECTRON_RENDERER_URL"]) {
    // dev server from electron-vite
    void mainWindow.loadURL(process.env["ELECTRON_RENDERER_URL"]);
  } else {
    void mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
  }
}

// single instance: a second launch focuses the existing window
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    // security handlers must be in place BEFORE any BrowserWindow exists
    installSecurityDefaults();

    // test-only isolation: e2e/debug runs redirect userData (Electron's
    // appData path follows the Windows known-folder API, so APPDATA env
    // overrides do NOT work)
    const userDataOverride = process.env["UFUK_USER_DATA_DIR"];
    if (userDataOverride) {
      app.setPath("userData", userDataOverride);
    }

    const userDataDir = app.getPath("userData");
    const settings = new SettingsStore(userDataDir);
    let session: GatewaySession = buildGatewaySession(
      settings.load(),
      userDataDir,
      safeStorage,
    );
    const projects = new ProjectManager(userDataDir);
    const runtime = new AgentRuntime({
      win: () => mainWindow,
      settings,
      session: () => session,
      projects,
    });

    registerIpcHandlers({
      win: () => mainWindow,
      settings,
      userDataDir,
      safe: safeStorage,
      session: () => session,
      setSession: (s) => {
        session = s;
      },
      versions: () => ({
        version: app.getVersion(),
        electron: process.versions.electron ?? "",
        node: process.versions.node ?? "",
      }),
      projects,
      runtime,
    });

    createWindow();

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on("window-all-closed", () => {
    // Windows-only target: quit when the window closes.
    app.quit();
  });
}
