# Building sidr-patch

## On Windows (simplest)

1. Install the Rust toolchain from https://rustup.rs (default MSVC toolchain).
2. Install "Build Tools for Visual Studio" with the "Desktop development with C++" workload.
   The bundled SQLite is C code and needs a C compiler.
3. In this folder:

   ```
   cargo build --release --locked
   ```

   The result is `target\release\sidr_patch.exe`.

The build downloads its dependencies from crates.io and the `ese_parser` library from
GitHub (`strozfriedberg/ese_parser`, tag v0.2.1), so it needs internet access.
`Cargo.lock` pins every dependency version.

## How a cross-compiled sidr_patch.exe can be built

It was cross-compiled on Linux for `x86_64-pc-windows-gnu` with MinGW-w64, a statically linked
C runtime, and the standard library built from source (Rust 1.91.1):

```
RUSTFLAGS="-C target-feature=+crt-static" \
CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER=x86_64-w64-mingw32-gcc \
cargo build --release --locked --target x86_64-pc-windows-gnu -Zbuild-std=std,panic_abort
```

The exe needs only standard Windows DLLs.

## Hashes

Rust release builds are not bit-for-bit reproducible by default. Temporary folder names and
internal symbol IDs differ between builds, so two builds from identical source will have
different SHA-256 hashes. To check a rebuild, compare its reports instead of its hash.

## Tests

```
cargo test --release
```

These run SIDR's original tests. For the Windows 11 24H2/25H2 fixes and `--history` checks, see `validation/README.md`.
