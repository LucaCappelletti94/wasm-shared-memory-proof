// Asserts the engine facts of Chromium, Firefox and WebKit, with and without cross-origin isolation.
import { strict as assert } from "node:assert";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname } from "node:path";
import { chromium, firefox, webkit } from "playwright";
import { expectedFacts } from "./engines.mjs";

const harness = new URL("./", import.meta.url);
const target = new URL("../target/", import.meta.url);
const types = { ".html": "text/html", ".mjs": "text/javascript", ".js": "text/javascript", ".wasm": "application/wasm" };

// /isolated/… and /open/… serve the same files, only the first with the isolation headers.
const server = createServer(async (request, response) => {
  const [, mode, ...rest] = new URL(request.url, "http://localhost").pathname.split("/");
  const path = rest.join("/");
  const file = path.startsWith("pkg-") ? new URL(path, target) : new URL(path, harness);
  try {
    const body = await readFile(file);
    const headers = { "content-type": types[extname(path)] ?? "application/octet-stream" };
    if (mode === "isolated") {
      headers["cross-origin-opener-policy"] = "same-origin";
      headers["cross-origin-embedder-policy"] = "require-corp";
    }
    response.writeHead(200, headers).end(body);
  } catch {
    response.writeHead(404).end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;

let failed = false;
for (const [engine, type] of [["chromium", chromium], ["firefox", firefox], ["webkit", webkit]]) {
  const browser = await type.launch();
  for (const mode of ["isolated", "open"]) {
    const page = await browser.newPage();
    await page.goto(`${origin}/${mode}/page.html`);
    const { crossOriginIsolated, ...facts } = await page.evaluate(() => window.facts);
    console.log(JSON.stringify({ engine, mode, crossOriginIsolated, ...facts }));
    try {
      assert.equal(crossOriginIsolated, mode === "isolated");
      assert.deepEqual(facts, expectedFacts(mode === "isolated"));
    } catch (error) {
      failed = true;
      console.error(`FAIL ${engine} ${mode}: ${error.message}`);
    }
    await page.close();
  }
  await browser.close();
}
server.close();
process.exitCode = failed ? 1 : 0;
