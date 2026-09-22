/**
 * Renderer hardening (Milestone 3 security baseline). Everything here is
 * defense in depth on top of: contextIsolation=true, nodeIntegration=false,
 * sandbox=true (set on the BrowserWindow in index.ts).
 *
 * - permission requests (geolocation, camera, notifications, ...) are DENIED
 * - ALL navigation is blocked (the app is a single page; links open in the
 *   system browser via the shell:open-external IPC instead)
 * - window.open is blocked (no popups, no auxiliary browsers)
 * - <webview> attachment is blocked
 * - new web contents inherit the same rules
 *
 * Must be called from app.whenReady() BEFORE the first BrowserWindow is
 * created: the 'web-contents-created' handlers only apply to contents
 * created after registration.
 */
import { app, session, type WebContents } from "electron";

export function installSecurityDefaults(): void {
  // 1. Deny every permission request in the default session.
  session.defaultSession.setPermissionRequestHandler(
    (_webContents, _permission, callback) => {
      callback(false);
    },
  );

  // 2. For every webContents we ever create:
  app.on("web-contents-created", (_event, contents) => {
    // block <webview> attachment
    contents.on("will-attach-webview", (event) => {
      event.preventDefault();
    });

    // block window.open and friends entirely
    contents.setWindowOpenHandler((_details) => ({ action: "deny" }));

    // block all navigation: the renderer is a single static page. Any
    // navigation attempt (link click, location change, redirect) is either
    // an attack or a bug; external links go through shell:open-external.
    contents.on("will-navigate", (event) => {
      event.preventDefault();
    });
  });
}

/**
 * Validate an ipcMain 'invoke' event sender: the frame must belong to our own
 * renderer origin. Used by every handler in electron/main/ipc.ts.
 */
export function isTrustedSender(contents: WebContents): boolean {
  try {
    const url = new URL(contents.getURL());
    const protocol = url.protocol;
    if (protocol === "file:") return true; // packaged app
    if (protocol === "http:" || protocol === "https:") {
      // dev server only
      return url.hostname === "localhost" || url.hostname === "127.0.0.1";
    }
    return false;
  } catch {
    return false;
  }
}

/**
 * Parse a URL requested for the system browser. Only http(s) is ever allowed
 * (blocks javascript:, file:, and every other scheme). Returns null when the
 * URL must not be opened.
 */
export function parseExternalUrl(raw: string): URL | null {
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    return null;
  }
  return parsed;
}
