// Windows integration: the real popup must resume drawing after page suspension.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { createServer } from "node:net";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
assert.equal(typeof WebSocket, "function", "This regression requires Node.js 22+");
const exeArg = process.argv.indexOf("--exe");
const exe = resolve(root, exeArg < 0
  ? "src-tauri/target/release/overlay-lifecycle-regression.exe"
  : process.argv[exeArg + 1]);
const port = 9227;
const reservation = createServer();
await new Promise((resolve, reject) => {
  reservation.once("error", reject);
  reservation.listen(port, "127.0.0.1", resolve);
});
await new Promise((resolve) => reservation.close(resolve));

const proc = spawn(exe, [], { cwd: root, windowsHide: true, stdio: ["pipe", "pipe", "pipe"] });
let output = "";
let spawnError;
proc.on("error", (error) => { spawnError = error; });
proc.stdout.on("data", (data) => { output += data; });
proc.stderr.on("data", (data) => { output += data; });
const send = (command, payload) => proc.stdin.write(JSON.stringify({ command, payload }) + "\n");
let socket;

try {
  let page;
  for (let n = 0; n < 60; n++) {
    if (spawnError) throw spawnError;
    if (proc.exitCode !== null) throw new Error(`Regression app exited: ${output}`);
    try {
      const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      page = pages.find((page) => page.title === "Sber Whisper");
      if (page) break;
    } catch { /* WebView2 is still starting. */ }
    await delay(250);
  }
  assert.ok(page, "Regression WebView2 did not start");
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let id = 0;
  const pending = new Map();
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    pending.get(message.id)?.(message);
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const requestId = ++id;
    const timeout = setTimeout(() => {
      pending.delete(requestId);
      reject(new Error(`CDP timeout: ${method}`));
    }, 5000);
    pending.set(requestId, (message) => {
      clearTimeout(timeout);
      pending.delete(requestId);
      message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result);
    });
    socket.send(JSON.stringify({ id: requestId, method, params }));
  });
  const state = async () => {
    const result = await call("Runtime.evaluate", {
      expression: `JSON.stringify({
        visibility: document.visibilityState,
        shell: document.querySelector('main')?.className,
        opacity: document.querySelector('.pill') && getComputedStyle(document.querySelector('.pill')).opacity
      })`, returnByValue: true,
    });
    assert.ok(!result.exceptionDetails, "Reading popup state failed");
    return JSON.parse(result.result.value);
  };
  const waitFor = async (predicate, label) => {
    let current;
    for (let n = 0; n < 40; n++) {
      assert.equal(proc.exitCode, null, `Regression app exited: ${output}`);
      assert.ok(!output.includes("panicked at"), `Regression app panicked: ${output}`);
      current = await state();
      if (predicate(current)) return current;
      await delay(100);
    }
    assert.fail(`${label}: ${JSON.stringify(current)}`);
  };
  await call("Runtime.enable");
  await call("Page.enable");
  await waitFor((s) => !!s.shell, "Popup frontend did not mount");
  // Allow the initial React effect to register its asynchronous event listener.
  await delay(500);
  send("show");
  send("event", { event: "dictation_starting" });
  await waitFor((s) => s.visibility === "visible" && s.shell.includes("is-visible") && s.opacity === "1",
    "Ordinary dictation is not visible");

  for (let cycle = 1; cycle <= 3; cycle++) {
    // Freeze a hidden popup, reactivate it, then run the product's ordinary show path.
    send("event", { event: "text_inserted" });
    await waitFor((s) => s.shell.includes("is-hidden"), "Popup did not hide after insertion");
    await call("Page.setWebLifecycleState", { state: "frozen" });
    await delay(100);
    await call("Page.setWebLifecycleState", { state: "active" });
    const suspended = await state();
    assert.equal(suspended.visibility, "hidden", "Suspension did not reproduce a hidden page");
    send("show");
    send("event", { event: "dictation_starting" });
    await waitFor((s) => s.visibility === "visible" && s.shell.includes("is-visible") && s.opacity === "1",
      `Cycle ${cycle}: popup stayed hidden after resume`);
    console.log(`PASS: popup resumes with a visible page and opacity 1 (cycle ${cycle})`);
  }
  send("event", { event: "job_cancelled" });
  await waitFor((s) => s.shell.includes("is-hidden"), "Cancellation did not hide the popup");
} catch (error) {
  console.error(output);
  throw error;
} finally {
  socket?.close();
  if (!spawnError && proc.exitCode === null) {
    send("quit");
    await delay(500);
    if (proc.exitCode === null) proc.kill();
  }
}
assert.ok(!output.includes("panicked at"), `Regression app panicked: ${output}`);
assert.equal(proc.exitCode, 0, `Regression app failed to exit cleanly: ${output}`);
