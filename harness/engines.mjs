// The engine facts behind the runtime check, measured the same way in Node and in browsers.

// (module (import "env" "memory" (memory 1))), a memory import that is not shared.
const NON_SHARED_IMPORT = new Uint8Array([
  0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00,
  0x02, 0x0f, 0x01,
  0x03, 0x65, 0x6e, 0x76,
  0x06, 0x6d, 0x65, 0x6d, 0x6f, 0x72, 0x79,
  0x02, 0x00, 0x01,
]);

function outcome(action) {
  try {
    action();
    return "ok";
  } catch (error) {
    return error.name;
  }
}

function instantiateWith(memory) {
  return () => new WebAssembly.Instance(new WebAssembly.Module(NON_SHARED_IMPORT), { env: { memory } });
}

/**
 * Measures what an engine lets a memory do across agents and what the probe sees.
 * `postToWorker` posts a value to a live worker, `loadProbe` instantiates the
 * wasm-bindgen probe built with (`"shared"`) or without (`"plain"`) shared memory.
 */
export async function engineFacts({ postToWorker, loadProbe }) {
  const facts = {
    sharedArrayBufferGlobal: typeof SharedArrayBuffer === "function",
    postNonShared: outcome(() => postToWorker(new WebAssembly.Memory({ initial: 1, maximum: 1 }))),
    nonSharedIntoNonSharedImport: outcome(instantiateWith(new WebAssembly.Memory({ initial: 1, maximum: 1 }))),
  };
  let shared = null;
  facts.constructShared = outcome(() => {
    shared = new WebAssembly.Memory({ initial: 1, maximum: 1, shared: true });
  });
  if (shared) {
    facts.postShared = outcome(() => postToWorker(shared));
    facts.sharedIntoNonSharedImport = outcome(instantiateWith(shared));
  }
  // The probe must tell the memories apart without the global.
  delete globalThis.SharedArrayBuffer;
  facts.probe = {};
  for (const kind of ["plain", "shared"]) {
    try {
      const probe = await loadProbe(kind);
      facts.probe[kind] = { isArrayBuffer: probe.memoryIsArrayBuffer(), tag: probe.memoryBufferTag() };
    } catch (error) {
      facts.probe[kind] = { error: error.name };
    }
  }
  return facts;
}

/** What every engine must report, `isolated` meaning cross-origin isolated or Node. */
export function expectedFacts(isolated) {
  return {
    sharedArrayBufferGlobal: isolated,
    postNonShared: "DataCloneError",
    nonSharedIntoNonSharedImport: "ok",
    constructShared: "ok",
    postShared: isolated ? "ok" : "DataCloneError",
    sharedIntoNonSharedImport: "LinkError",
    probe: {
      plain: { isArrayBuffer: true, tag: "[object ArrayBuffer]" },
      shared: { isArrayBuffer: false, tag: "[object SharedArrayBuffer]" },
    },
  };
}
