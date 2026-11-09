// Usage: node harness/race.mjs MODULE --atomic lossy|exact --cfg-atomics true|false
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { Worker } from "node:worker_threads";

const { positionals, values } = parseArgs({
  allowPositionals: true,
  options: { atomic: { type: "string" }, "cfg-atomics": { type: "string" } },
});
const module = new WebAssembly.Module(readFileSync(positionals[0]));
// Long enough that the two workers overlap on any runner.
const TIMES = 20_000_000;

const worker = `
const { workerData, parentPort } = require("node:worker_threads");
const { module, memory, gate, bump } = workerData;
const instance = new WebAssembly.Instance(module, { env: { memory } });
Atomics.add(gate, 1, 1);
Atomics.wait(gate, 0, 0);
try { instance.exports[bump](${TIMES}); parentPort.postMessage("ok"); }
catch (error) { parentPort.postMessage(error.name); }`;

async function race(bump) {
  const memory = new WebAssembly.Memory({ initial: 17, maximum: 16384, shared: true });
  const main = new WebAssembly.Instance(module, { env: { memory } });
  main.exports.record_panics();
  const gate = new Int32Array(new SharedArrayBuffer(8));
  const workers = [0, 1].map(() => new Worker(worker, { eval: true, workerData: { module, memory, gate, bump } }));
  const outcomes = workers.map((w) => new Promise((resolve) => w.once("message", resolve)));
  while (Atomics.load(gate, 1) < 2) await new Promise((resolve) => setTimeout(resolve, 1));
  Atomics.store(gate, 0, 1);
  Atomics.notify(gate, 0);
  const results = (await Promise.all(outcomes)).sort();
  await Promise.all(workers.map((w) => w.terminate()));
  const start = main.exports.panic_message_ptr();
  const panic = new TextDecoder().decode(new Uint8Array(memory.buffer).slice(start, start + main.exports.panic_message_len()));
  return { main, results, panic };
}

const atomic = await race("bump_atomic");
const atomicValue = atomic.main.exports.atomic_value();
console.log(JSON.stringify({ counter: "AtomicU32", expected: 2 * TIMES, value: atomicValue, workers: atomic.results }));
assert.deepEqual(atomic.results, ["ok", "ok"]);
if (values.atomic === "lossy") assert.ok(atomicValue < 2 * TIMES, "no update was lost");
else assert.equal(atomicValue, 2 * TIMES);

const mutex = await race("bump_mutex");
console.log(JSON.stringify({ counter: "Mutex<u32>", workers: mutex.results, panic: mutex.panic }));
assert.ok(mutex.results.includes("RuntimeError"), "no worker trapped");
assert.match(mutex.panic, /cannot recursively acquire mutex/);

const cfgAtomics = Boolean(atomic.main.exports.cfg_atomics());
console.log(JSON.stringify({ cfgAtomics }));
assert.equal(String(cfgAtomics), values["cfg-atomics"]);
