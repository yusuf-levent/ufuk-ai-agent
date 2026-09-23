// debug helper: launch the built app with isolated userData and verify the
// M6 chat runtime wiring (send to a missing conversation -> chat:error event)
import { _electron } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";

const mainJs = path.resolve("out/main/index.js");
const dataDir = mkdtempSync(path.join(tmpdir(), "ufuk-dbg-"));
const app = await _electron.launch({
  args: [mainJs],
  env: { ...process.env, UFUK_USER_DATA_DIR: dataDir },
});
const win = await app.firstWindow();
await win.waitForTimeout(3000);

// subscribe to chat events from the renderer (plain JS inside evaluate)
await win.evaluate(() => {
  window.__events = [];
  window.ufuk.subscribe("chat:event", (payload) => {
    window.__events.push(payload);
  });
});

const added = await win.evaluate((projDir) => {
  return window.ufuk.invoke("projects:add", { path: projDir });
}, process.env["UFUK_PROJ"] ?? "C:\\Windows\\Temp");
console.log("projects:add ->", JSON.stringify(added).slice(0, 140));

const sent = await win.evaluate(async () => {
  const list = await window.ufuk.invoke("projects:list");
  return window.ufuk.invoke("chat:send", {
    root: list.value[0].root,
    conversationId: "c_doesnotexist",
    message: "hello",
  });
});
console.log("chat:send (bogus id) ->", JSON.stringify(sent));

await win.waitForTimeout(1500);
const events = await win.evaluate(() => window.__events);
console.log("chat events received:", JSON.stringify(events, null, 2));

await app.close();
process.exit(0);
