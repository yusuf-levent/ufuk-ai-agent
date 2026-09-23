// debug helper: launch the built app with isolated APPDATA and dump state
import { _electron } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";

const mainJs = path.resolve("out/main/index.js");
const dataDir = mkdtempSync(path.join(tmpdir(), "ufuk-dbg-"));
console.log("dataDir:", dataDir);
const app = await _electron.launch({
  args: [mainJs],
  env: {
    ...process.env,
    UFUK_USER_DATA_DIR: dataDir,
  },
});
const win = await app.firstWindow();
win.on("console", (msg) => console.log("[renderer]", msg.type(), msg.text()));
win.on("pageerror", (err) => console.log("[pageerror]", err.message));
await win.waitForTimeout(8000);
const state = await win.evaluate(() => ({
  url: location.href,
  text: document.body.innerText.slice(0, 600),
  hasBridge: typeof window.ufuk === "object",
}));
console.log(JSON.stringify(state, null, 2));
const settings = await win.evaluate(async () => {
  const r = await window.ufuk.invoke("settings:get");
  return r;
});
console.log("settings:", JSON.stringify(settings));
await app.close();
process.exit(0);
