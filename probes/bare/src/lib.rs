//! Returns 42 with no atomics and no thread-local of its own, through std's allocator under the `std` feature.
#![cfg_attr(not(feature = "std"), no_std)]

#[cfg(not(feature = "std"))]
#[panic_handler]
fn panic(_: &core::panic::PanicInfo<'_>) -> ! {
    core::arch::wasm32::unreachable()
}

/// The answer, computed without touching any state another worker could share.
#[no_mangle]
pub extern "C" fn run() -> i32 {
    #[cfg(feature = "std")]
    {
        std::hint::black_box(vec![20, 22]).iter().sum()
    }
    #[cfg(not(feature = "std"))]
    {
        42
    }
}
