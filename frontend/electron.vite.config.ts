import { resolve } from "node:path";
import { defineConfig, externalizeDepsPlugin } from "electron-vite";
import type { Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { buildCsp } from "./shared/csp";

/**
 * Injects the Content-Security-Policy meta tag into index.html at build/dev
 * time. Production: strict (no unsafe-inline anywhere). Dev only widens
 * style-src (Vite HMR injects <style> tags) and connect-src (HMR websocket).
 */
function injectCsp(): Plugin {
  return {
    name: "ufuk-inject-csp",
    transformIndexHtml(html: string, ctx: { server?: unknown }): string {
      const dev = ctx.server !== undefined;
      const csp = buildCsp(dev);
      return html.replace(
        "<!-- %CSP% -->",
        `<meta http-equiv="Content-Security-Policy" content="${csp}">`,
      );
    },
  };
}

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    resolve: {
      alias: { "@shared": resolve("shared") },
    },
    build: {
      lib: { entry: resolve("electron/main/index.ts") },
      rollupOptions: {
        // 'electron' must stay external (bundling it would inline the
        // npm-package Node shim, which spawns install.js at runtime);
        // better-sqlite3 is a native module loaded from node_modules.
        external: ["electron", "better-sqlite3"],
      },
    },
  },
  preload: {
    // NOTE: the preload must stay fully self-contained (sandbox: true).
    // Sandboxed preloads must be CommonJS (Electron does not support ESM
    // preload scripts under sandbox), so we force cjs + index.js.
    // 'electron' must stay external: bundling it would inline the npm
    // package's Node shim (electron is a devDependency, which v5's
    // externalizeDepsPlugin does not externalize).
    plugins: [externalizeDepsPlugin({ exclude: [] })],
    resolve: {
      alias: { "@shared": resolve("shared") },
    },
    build: {
      lib: { entry: resolve("electron/preload/index.ts") },
      rollupOptions: {
        external: ["electron"],
        output: {
          format: "cjs",
          entryFileNames: "index.js",
          // sandboxed preload: no code splitting, no dynamic imports
          inlineDynamicImports: true,
        },
      },
    },
  },
  renderer: {
    root: ".",
    plugins: [react(), tailwindcss(), injectCsp()],
    resolve: {
      alias: { "@shared": resolve("shared") },
    },
    build: {
      rollupOptions: { input: resolve("index.html") },
    },
  },
});
