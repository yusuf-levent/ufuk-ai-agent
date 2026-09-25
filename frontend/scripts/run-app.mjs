import { _electron } from "@playwright/test";
import * as path from "node:path";

const mainJs = path.resolve("out/main/index.js");
console.log("Launching Ufuk Desktop Application from:", mainJs);

const app = await _electron.launch({
  args: [mainJs],
  env: {
    ...process.env,
  },
});

const win = await app.firstWindow();
console.log("Ufuk Window successfully opened! PID:", app.process().pid);

// Keep alive until user closes the window or stops the task
win.on("close", () => {
  console.log("Window closed by user.");
  process.exit(0);
});

await new Promise(() => {});
