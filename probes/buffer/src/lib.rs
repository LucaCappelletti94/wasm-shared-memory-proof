//! Tells, from inside the module, whether its memory can be reached from another agent.
#![forbid(unsafe_code)]

use js_sys::{ArrayBuffer, Object, WebAssembly};
use wasm_bindgen::prelude::wasm_bindgen;
use wasm_bindgen::JsCast;

fn buffer() -> Object {
    wasm_bindgen::memory()
        .unchecked_into::<WebAssembly::Memory>()
        .buffer()
        .unchecked_into()
}

/// Whether the module's memory buffer is an `ArrayBuffer`, which no other agent can reach.
///
/// `instanceof ArrayBuffer` is false for a `SharedArrayBuffer`, and needs no
/// `SharedArrayBuffer` global, which is absent without cross-origin isolation.
#[wasm_bindgen(js_name = memoryIsArrayBuffer)]
pub fn memory_is_array_buffer() -> bool {
    buffer().is_instance_of::<ArrayBuffer>()
}

/// The `Object.prototype.toString` tag of the module's memory buffer.
#[wasm_bindgen(js_name = memoryBufferTag)]
pub fn memory_buffer_tag() -> String {
    Object::to_string(&buffer()).into()
}
