// Asserts the engine facts of Node's V8.
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { Worker } from "node:worker_threads";
import { engineFacts, expectedFacts } from "./engines.mjs";

const root = new URL("../target/", import.meta.url);
const worker = new Worker("require('node:worker_threads').parentPort.on('message', () => {});", { eval: true });
const facts = await engineFacts({
  postToWorker: (value) => worker.postMessage(value),
  loadProbe: async (kind) => {
    const glue = await import(new URL(`pkg-${kind}/probe_buffer.js`, root));
    glue.initSync({ module: readFileSync(new URL(`pkg-${kind}/probe_buffer_bg.wasm`, root)) });
    return glue;
  },
});
await worker.terminate();
console.log(JSON.stringify(facts));
assert.deepEqual(facts, expectedFacts(true));
