"""Builds the probes and asserts what rustc and the linker do with them.

    python3 harness/proof.py TOOLCHAIN link CASE...   link a probe into shared memory, assert the verdict
    python3 harness/proof.py TOOLCHAIN asm            what safe AtomicU32::fetch_add compiles to
    python3 harness/proof.py TOOLCHAIN cfg            whether cfg reveals atomics

A case that links leaves its module at target/proof/TOOLCHAIN/CASE.wasm.
"""

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wasmfile  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TARGET = "wasm32-unknown-unknown"
SHARED = ("--shared-memory", "--import-memory", "--max-memory=1073741824")
ATOMICS = "-Ctarget-feature=+atomics,+bulk-memory"
C_ATOMICS = "-matomics -mbulk-memory"

MARKED = "--shared-memory is disallowed by {} because it was not compiled with 'atomics' or 'bulk-memory' features."
NO_ATOMICS = "'atomics' feature must be used in order to use shared memory"
NO_BULK_MEMORY = "'bulk-memory' feature must be used in order to use shared memory"


@dataclass(frozen=True)
class Case:
    """A probe, the way it is built and linked, the linker errors expected (none meaning it links) and what its run() returns."""

    probe: str
    lto: str
    refused: tuple
    rustflags: tuple = ()
    link_args: tuple = ()
    cflags: str = ""
    features: tuple = ()
    shared: bool = True
    returns: int | None = None


def memvfs(lto, refused, **options):
    return Case("probe-memvfs", lto, refused, **options)


def race(lto, refused, **options):
    return Case("probe-race", lto, refused, **options)


EXTRA_FEATURES = "--extra-features=atomics,bulk-memory"

# Instantiates a module, handing every memory import a fresh shared memory, and prints run().
RUN_SCRIPT = """
const module = new WebAssembly.Module(require("node:fs").readFileSync(process.argv[1]));
const imports = {};
for (const { module: from, name, kind } of WebAssembly.Module.imports(module)) {
  if (kind !== "memory") throw new Error(`unexpected import ${from}.${name}`);
  (imports[from] ??= {})[name] = new WebAssembly.Memory({ initial: 256, maximum: 16384, shared: true });
}
console.log(new WebAssembly.Instance(module, imports).exports.run());
"""

CASES = {
    # Spxg's claim: memvfs, Rust built without atomics, through every route, after a control that it runs unshared.
    "memvfs-unshared": memvfs("false", (), shared=False, returns=42),
    "memvfs-lto-false": memvfs("false", (MARKED.format("<sqlite_wasm_rs>"), NO_ATOMICS)),
    "memvfs-lto-thin": memvfs("thin", (MARKED.format("<probe>"), NO_ATOMICS)),
    "memvfs-lto-fat": memvfs("fat", (MARKED.format("<probe>"), NO_ATOMICS)),
    "memvfs-c-atomics-lto-false": memvfs("false", (MARKED.format("<sqlite_wasm_rs>"),), cflags=C_ATOMICS),
    "memvfs-c-atomics-lto-thin": memvfs("thin", (MARKED.format("<probe>"),), cflags=C_ATOMICS),
    "memvfs-c-atomics-lto-fat": memvfs("fat", (MARKED.format("<probe>"),), cflags=C_ATOMICS),
    "memvfs-extra-features-lto-false": memvfs("false", (MARKED.format("<sqlite_wasm_rs>"),), link_args=(EXTRA_FEATURES,)),
    "memvfs-extra-features-lto-thin": memvfs("thin", (MARKED.format("<probe>"),), link_args=(EXTRA_FEATURES,)),
    "memvfs-extra-features-lto-fat": memvfs("fat", (MARKED.format("<probe>"),), link_args=(EXTRA_FEATURES,)),
    "memvfs-no-check-features": memvfs("false", (), link_args=("--no-check-features",)),
    "race-no-check-features": race("false", (), link_args=("--no-check-features",)),
    # Spxg's claim in general: an object with no atomics carries no mark, so supplying the feature is enough.
    "bare-shared": Case("probe-bare", "false", (NO_ATOMICS,)),
    "bare-extra-features": Case("probe-bare", "false", (), link_args=(EXTRA_FEATURES,), returns=42),
    "bare-std-extra-features": Case("probe-bare", "false", (MARKED.format("<std>"),), link_args=(EXTRA_FEATURES,), features=("std",)),
    # The cfg gate: +atomics on toolchains whose shipped std has none.
    "race-atomics-lto-false": race("false", (MARKED.format("<std>"),), rustflags=(ATOMICS,)),
    "race-atomics-lto-thin": race("thin", (), rustflags=(ATOMICS,)),
    "race-atomics-lto-fat": race("fat", (), rustflags=(ATOMICS,)),
}


def run(command, env=None):
    """Runs `command` and returns its exit code and combined output."""
    done = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def cargo(toolchain, verb, package, target_dir, rustflags=(), lto="false", cflags="", target=TARGET, features=()):
    env = dict(os.environ)
    env.pop("RUSTFLAGS", None)
    env["CARGO_ENCODED_RUSTFLAGS"] = "\x1f".join(rustflags)
    env["CARGO_PROFILE_RELEASE_LTO"] = lto
    env["CARGO_TARGET_DIR"] = str(target_dir)
    if cflags:
        env["CFLAGS_wasm32_unknown_unknown"] = cflags
    else:
        env.pop("CFLAGS_wasm32_unknown_unknown", None)
    command = ["cargo", f"+{toolchain}", verb, "--release", "-p", package, "--target", target]
    if features:
        command += ["--features", ",".join(features)]
    return run(command, env)


def object_label(path):
    """Names an object in a linker error by the crate it comes from, `<probe>` for the final crate's own."""
    base = os.path.basename(path)
    if base.startswith("probe_"):
        return "<probe>"
    crate = re.match(r"([a-z0-9_]+)-[0-9a-f]{16}\.", base)
    return f"<{crate.group(1)}>" if crate else base


def linker_errors(output):
    errors = []
    for line in re.findall(r"rust-lld: error: (.*)", output):
        line = re.sub(r"disallowed by (\S+) because", lambda m: f"disallowed by {object_label(m.group(1))} because", line)
        errors.append(line)
    return errors


def expect(condition, message):
    if not condition:
        raise SystemExit(f"FAIL {message}")


def link(toolchain, names):
    out = ROOT / "target" / "proof" / toolchain
    out.mkdir(parents=True, exist_ok=True)
    # The target enables bulk-memory by default from Rust 1.87, so on 1.82 the linker also asks for it.
    printed = run(["rustc", f"+{toolchain}", "--print", "cfg", "--target", TARGET])[1]
    bulk_memory = 'target_feature="bulk-memory"' in printed.splitlines()
    for name in names:
        case = CASES[name]
        refused = list(case.refused)
        if NO_ATOMICS in refused and not bulk_memory:
            refused.append(NO_BULK_MEMORY)
        link_args = (*SHARED, *case.link_args) if case.shared else case.link_args
        rustflags = (*case.rustflags, *(f"-Clink-arg={arg}" for arg in link_args))
        target_dir = ROOT / "target" / f"link-{toolchain}"
        code, output = cargo(
            toolchain, "build", case.probe, target_dir, rustflags, case.lto, case.cflags, features=case.features
        )
        errors = linker_errors(output)
        module = target_dir / TARGET / "release" / f"{case.probe.replace('-', '_')}.wasm"
        if refused:
            expect(code != 0, f"{name}: linked, expected {refused}")
            expect(errors == refused, f"{name}: linker said {errors}, expected {refused}\n{output}")
            print(f"ok {name}: refused, {errors}")
            if name == "memvfs-lto-false":
                marks(toolchain, target_dir)
            continue
        expect(code == 0, f"{name}: build failed\n{output}")
        flags = wasmfile.memory_limits_flags(module.read_bytes())
        expect(flags is not None and bool(flags & 2) == case.shared, f"{name}: memory limits flags {flags}")
        shutil.copyfile(module, out / f"{name}.wasm")
        print(f"ok {name}: links, memory {'shared' if case.shared else 'not shared'}")
        if case.returns is not None:
            result = run(["node", "-e", RUN_SCRIPT, str(module)])[1].strip()
            expect(result == str(case.returns), f"{name}: run() returned {result}")
            print(f"ok {name}: run() returns {result}")


def marks(toolchain, target_dir):
    """The shipped core and the objects holding memvfs carry -shared-mem, and no object uses atomics."""
    sysroot = Path(run(["rustc", f"+{toolchain}", "--print", "sysroot"])[1].strip())
    seen = {}
    for archive in [*(target_dir / TARGET / "release").rglob("librsqlite_vfs-*.rlib"), *sysroot.glob(f"lib/rustlib/{TARGET}/lib/libcore-*.rlib")]:
        for _, body in wasmfile.objects(archive):
            crate = archive.name[3:].split("-")[0]
            seen.setdefault(crate, set()).add(wasmfile.mark(wasmfile.target_features(body)))
    expect("-shared-mem" in seen.get("rsqlite_vfs", ()), f"no rsqlite_vfs object marks -shared-mem: {seen}")
    expect(seen.get("core") == {"-shared-mem"}, f"core objects: {seen.get('core')}")
    expect(all("+atomics" not in kinds for kinds in seen.values()), f"an object uses atomics: {seen}")
    print(f"ok memvfs-marks: {dict((crate, sorted(kinds)) for crate, kinds in seen.items())}")


def asm(toolchain):
    """Safe fetch_add is a plain load, add and store without atomics, one atomic instruction with them."""
    expected = {
        "without atomics": ((), ["i32.load", "i32.add", "i32.store"]),
        "with atomics": ((ATOMICS,), ["i32.atomic.rmw.add"]),
    }
    for label, (flags, sequence) in expected.items():
        target_dir = ROOT / "target" / f"asm-{toolchain}-{'atomics' if flags else 'plain'}"
        code, output = cargo(toolchain, "build", "probe-race", target_dir, (*flags, "--emit=asm"))
        expect(code == 0, f"asm {label}: build failed\n{output}")
        listing = next((target_dir / TARGET / "release").rglob("probe_race.s")).read_text()
        # Legacy mangling on 1.82, v0 mangling later.
        body = re.search(r"^(?:_ZN10probe_race4bump\w*|_RNv\w+_10probe_race4bump):\n(.*?)\bend_function", listing, re.S | re.M)
        expect(body is not None, f"asm {label}: no probe_race::bump in the listing")
        ops = [op for op in re.findall(r"^\s+([a-z0-9_.]+)", body.group(1), re.M) if op.startswith("i32.") and op != "i32.const"]
        expect(ops == sequence, f"asm {label}: bump is {ops}, expected {sequence}")
        print(f"ok asm {label}: {ops}")


def cfg(toolchain):
    """cfg sees atomics on nightly only, for wasip1-threads and for +atomics."""
    release = run(["rustc", f"+{toolchain}", "-vV"])[1]
    nightly = bool(re.search(r"^release: .*-(nightly|dev)$", release, re.M))
    for target, flags in (("wasm32-wasip1-threads", ()), (TARGET, (ATOMICS,))):
        label = " ".join((target, *flags))
        printed = run(["rustc", f"+{toolchain}", "--print", "cfg", "--target", target, *flags])[1]
        shown = 'target_feature="atomics"' in printed.splitlines()
        expect(shown == nightly, f"cfg {label}: --print cfg shows atomics: {shown}")
        target_dir = ROOT / "target" / f"cfg-{toolchain}"
        code, output = cargo(toolchain, "check", "probe-cfg", target_dir, flags, target=target)
        if nightly:
            expect(code != 0 and 'error: cfg(target_feature = "atomics") is set' in output, f"cfg {label}: compiled\n{output}")
        else:
            expect(code == 0, f"cfg {label}: did not compile\n{output}")
        print(f"ok cfg {label}: --print cfg shows atomics: {shown}, gate sees atomics: {nightly}")


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    toolchain, command, *rest = argv
    if command == "link":
        link(toolchain, rest or list(CASES))
    elif command == "asm":
        asm(toolchain)
    elif command == "cfg":
        cfg(toolchain)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
