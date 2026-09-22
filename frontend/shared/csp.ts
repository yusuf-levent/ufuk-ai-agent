/** Content-Security-Policy for the renderer (see electron.vite.config.ts).
 *
 * Rules:
 * - scripts: only from the app itself ('self'); no inline, no eval, ever.
 * - styles: 'self' in production. Dev only: 'unsafe-inline' because Vite HMR
 *   injects <style> tags (React style props use the CSSOM and are unaffected).
 * - connect: the renderer NEVER talks to the backend directly (all network
 *   goes through the main process); dev opens the HMR websocket.
 * - frames, objects, plugins, form submissions: disabled.
 */
export function buildCsp(dev: boolean): string {
  const styleSrc = dev
    ? "style-src 'self' 'unsafe-inline';"
    : "style-src 'self';";
  const connectSrc = dev
    ? "connect-src 'self' ws://localhost:5173 http://localhost:5173;"
    : "connect-src 'self';";
  return [
    "default-src 'self';",
    "script-src 'self';",
    styleSrc,
    "img-src 'self' data:;",
    "font-src 'self' data:;",
    connectSrc,
    "object-src 'none';",
    "base-uri 'none';",
    "form-action 'none';",
    "frame-src 'none';",
    "child-src 'none';",
  ].join(" ");
}
