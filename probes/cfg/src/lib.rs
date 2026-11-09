//! Fails to compile exactly when rustc reveals `atomics` to `cfg`.
#![no_std]

#[cfg(target_feature = "atomics")]
compile_error!("cfg(target_feature = \"atomics\") is set");
