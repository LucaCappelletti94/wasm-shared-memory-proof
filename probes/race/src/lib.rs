//! Safe counters that two workers bump through one shared memory.
#![deny(unsafe_code)]

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Mutex, PoisonError};

static ATOMIC: AtomicU32 = AtomicU32::new(0);
static GUARDED: Mutex<u32> = Mutex::new(0);
static PANIC: Mutex<String> = Mutex::new(String::new());

/// Adds one to `counter` and returns its previous value.
#[inline(never)]
pub fn bump(counter: &AtomicU32) -> u32 {
    counter.fetch_add(1, Ordering::Relaxed)
}

/// Adds one to the counter `guarded` protects.
#[inline(never)]
pub fn bump_guarded(guarded: &Mutex<u32>) {
    *guarded.lock().unwrap_or_else(PoisonError::into_inner) += 1;
}

/// Bumps the atomic counter `times` times.
#[expect(
    unsafe_code,
    reason = "exporting a symbol is the harness, the counter is safe code"
)]
#[no_mangle]
pub extern "C" fn bump_atomic(times: u32) {
    for _ in 0..times {
        bump(&ATOMIC);
    }
}

/// Bumps the mutex-guarded counter `times` times.
#[expect(
    unsafe_code,
    reason = "exporting a symbol is the harness, the counter is safe code"
)]
#[no_mangle]
pub extern "C" fn bump_mutex(times: u32) {
    for _ in 0..times {
        bump_guarded(&GUARDED);
    }
}

/// Reads the atomic counter.
#[expect(unsafe_code, reason = "exporting a symbol is the harness")]
#[no_mangle]
pub extern "C" fn atomic_value() -> u32 {
    ATOMIC.load(Ordering::Relaxed)
}

/// Records the message of the next panic in any instance sharing this memory.
#[expect(unsafe_code, reason = "exporting a symbol is the harness")]
#[no_mangle]
pub extern "C" fn record_panics() {
    std::panic::set_hook(Box::new(|info| {
        let payload = info.payload();
        let message = payload
            .downcast_ref::<String>()
            .map(String::as_str)
            .or_else(|| payload.downcast_ref::<&str>().copied())
            .unwrap_or_default();
        *PANIC.lock().unwrap_or_else(PoisonError::into_inner) = message.to_owned();
    }));
}

/// Address of the recorded panic message.
#[expect(unsafe_code, reason = "exporting a symbol is the harness")]
#[no_mangle]
pub extern "C" fn panic_message_ptr() -> usize {
    PANIC
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .as_ptr() as usize
}

/// Length in bytes of the recorded panic message.
#[expect(unsafe_code, reason = "exporting a symbol is the harness")]
#[no_mangle]
pub extern "C" fn panic_message_len() -> usize {
    PANIC.lock().unwrap_or_else(PoisonError::into_inner).len()
}

/// Whether rustc compiled this module with `cfg(target_feature = "atomics")`.
#[expect(unsafe_code, reason = "exporting a symbol is the harness")]
#[no_mangle]
pub extern "C" fn cfg_atomics() -> bool {
    cfg!(target_feature = "atomics")
}
