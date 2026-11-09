//! Opens an SQLite database in sqlite-wasm-rs's memvfs, with no atomics of its own.
#![no_std]

extern crate alloc;

use core::alloc::{GlobalAlloc, Layout};
use core::cell::Cell;
use core::ptr;
use sqlite_wasm_rs as ffi;

/// Hands out memory from pages grown on demand and never frees it.
struct Bump(Cell<usize>);

// SAFETY: the probe is linked only to test whether the linker lets it into shared memory.
unsafe impl Sync for Bump {}

// SAFETY: every block is fresh, aligned and never handed out twice.
unsafe impl GlobalAlloc for Bump {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let next = match self.0.get() {
            0 => core::arch::wasm32::memory_size(0) * 65536,
            next => next,
        };
        let start = (next + layout.align() - 1) & !(layout.align() - 1);
        let end = start + layout.size();
        let have = core::arch::wasm32::memory_size(0) * 65536;
        if end > have {
            let pages = (end - have).div_ceil(65536);
            if core::arch::wasm32::memory_grow(0, pages) == usize::MAX {
                return ptr::null_mut();
            }
        }
        self.0.set(end);
        start as *mut u8
    }

    unsafe fn dealloc(&self, _: *mut u8, _: Layout) {}
}

#[global_allocator]
static ALLOCATOR: Bump = Bump(Cell::new(0));

#[panic_handler]
fn panic(_: &core::panic::PanicInfo<'_>) -> ! {
    core::arch::wasm32::unreachable()
}

/// Creates a table in a memvfs database and returns the row it reads back.
#[no_mangle]
pub extern "C" fn run() -> i32 {
    // SAFETY: one call on one thread, the database handle stays local.
    unsafe {
        let mut db = ptr::null_mut();
        if ffi::sqlite3_open(c"probe.db".as_ptr(), &mut db) != ffi::SQLITE_OK {
            return -1;
        }
        let mut stmt = ptr::null_mut();
        ffi::sqlite3_exec(
            db,
            c"CREATE TABLE t(v); INSERT INTO t VALUES (42);".as_ptr(),
            None,
            ptr::null_mut(),
            ptr::null_mut(),
        );
        ffi::sqlite3_prepare_v2(
            db,
            c"SELECT v FROM t".as_ptr(),
            -1,
            &mut stmt,
            ptr::null_mut(),
        );
        let value = if ffi::sqlite3_step(stmt) == ffi::SQLITE_ROW {
            ffi::sqlite3_column_int(stmt, 0)
        } else {
            -2
        };
        ffi::sqlite3_finalize(stmt);
        ffi::sqlite3_close(db);
        value
    }
}

/// Host hook, no sleeping in the probe.
#[no_mangle]
pub extern "C" fn rust_sqlite_wasm_host_sleep(_seconds: u64, _nanoseconds: u32) {}

/// Host hook, fills nothing and reports zero random bytes.
#[no_mangle]
pub extern "C" fn rust_sqlite_wasm_host_random(_buf: *mut u8, _len: usize) -> usize {
    0
}

/// Host hook, the clock reads the epoch. `out` is null or an `i64` the shim owns for the call.
#[no_mangle]
pub extern "C" fn rust_sqlite_wasm_host_epoch_timestamp_in_ms(out: Option<&mut i64>) -> i32 {
    if let Some(out) = out {
        *out = 0;
    }
    0
}

/// Host hook, entropy is unavailable.
#[no_mangle]
pub extern "C" fn rust_sqlite_wasm_host_fill_entropy(_buf: *mut u8, _len: usize) -> i32 {
    1
}

/// Host hook, local time is unavailable.
#[no_mangle]
pub extern "C" fn rust_sqlite_wasm_host_localtime(
    _unix_seconds: i64,
    _out: *mut core::ffi::c_void,
) -> i32 {
    1
}
