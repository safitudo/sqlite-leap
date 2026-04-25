#!/usr/bin/env bash
# Build the WASM artifact for sqlite-leap.
#
# This compiles the `sqlite_leap_wasm` wrapper crate (which path-depends on
# src-rust/) to wasm32-unknown-unknown and copies the resulting .wasm file to
# src-wasm/ at the repo root. src-wasm/ is gitignored per CLAUDE.md.
#
# Prerequisites:
#   - rustup target add wasm32-unknown-unknown
#   - wasm-opt is NOT required (we keep the toolchain minimal); if you want
#     further size shrinking, run `wasm-opt -Oz <file>.wasm -o <file>.opt.wasm`
#     manually.
#
# The build is hermetic to this crate — the parent src-rust/.cargo/config.toml
# (which sets target-cpu=native) is NOT picked up because cargo walks UP from
# the invocation dir, finding generators/wasm/.cargo/config.toml first.
#
# Usage:
#   ./generators/wasm/build.sh           # release build (default)
#   PROFILE=dev ./generators/wasm/build.sh   # unoptimised, faster iteration
#
# DO NOT CHEAT: this script compiles our own spec-generated Rust engine into
# wasm. No mainline SQLite, Turso, or sql.js code is linked.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
TARGET="wasm32-unknown-unknown"
PROFILE="${PROFILE:-release}"
OUT_DIR="$REPO_ROOT/src-wasm"
ARTIFACT_NAME="sqlite_leap.wasm"

if [ ! -f "$REPO_ROOT/src-rust/lib.rs" ]; then
    echo "[generators/wasm] ERROR: src-rust/lib.rs missing — run generators/rust/generate.sh first." >&2
    exit 1
fi

# Pick the cargo/rustc toolchain that actually has wasm32 std installed.
#
# The default $PATH cargo on this machine may point at a Homebrew rustc that
# lacks the wasm32-unknown-unknown rust-std component (Homebrew ships rustc
# without rustup's per-target stds). `rustup run stable cargo` alone isn't
# enough: cargo invokes rustc via $PATH lookup and Homebrew's rustc shim at
# /opt/homebrew/bin/rustc still wins on macOS.
#
# So: if rustup is present, pin BOTH cargo and RUSTC to absolute paths inside
# the rustup-managed toolchain directory. That bypasses $PATH entirely.
#
# If rustup isn't installed, fall back to plain `cargo`; the user brought
# their own toolchain and we should not second-guess them.
if command -v rustup >/dev/null 2>&1; then
    # Make sure the wasm std is present for the default toolchain.
    if ! rustup target list --installed 2>/dev/null | grep -q "^${TARGET}$"; then
        echo "[generators/wasm] Installing missing target: $TARGET"
        rustup target add "$TARGET"
    fi
    RUSTUP_TOOLCHAIN_BIN="$(dirname "$(rustup which cargo)")"
    CARGO=("$RUSTUP_TOOLCHAIN_BIN/cargo")
    export RUSTC="$RUSTUP_TOOLCHAIN_BIN/rustc"
else
    CARGO=(cargo)
fi

# Clear any inherited RUSTFLAGS — our .cargo/config.toml already sets empty
# rustflags for wasm32, but an ambient RUSTFLAGS=-C target-cpu=native (which
# is what src-rust's benchmark wrapper scripts export) would still break the
# wasm build because target-cpu=native is meaningless for wasm.
unset RUSTFLAGS

echo "[generators/wasm] Target:   $TARGET"
echo "[generators/wasm] Profile:  $PROFILE"
echo "[generators/wasm] Output:   $OUT_DIR/$ARTIFACT_NAME"
echo "[generators/wasm] Cargo:    ${CARGO[*]}"
echo "[generators/wasm] Manifest: $HERE/Cargo.toml"

# --lib: we only want the cdylib/rlib, not any spurious bin. The wrapper crate
# declares no binaries, but --lib is belt-and-braces and makes intent obvious.
if [ "$PROFILE" = "dev" ]; then
    "${CARGO[@]}" build \
        --manifest-path "$HERE/Cargo.toml" \
        --target "$TARGET" \
        --lib
    BUILT="$HERE/target/$TARGET/debug/sqlite_leap_wasm.wasm"
else
    "${CARGO[@]}" build \
        --manifest-path "$HERE/Cargo.toml" \
        --target "$TARGET" \
        --release \
        --lib
    BUILT="$HERE/target/$TARGET/release/sqlite_leap_wasm.wasm"
fi

if [ ! -f "$BUILT" ]; then
    echo "[generators/wasm] ERROR: expected artifact not found at $BUILT" >&2
    exit 2
fi

mkdir -p "$OUT_DIR"
cp "$BUILT" "$OUT_DIR/$ARTIFACT_NAME"

SIZE_BYTES=$(wc -c < "$OUT_DIR/$ARTIFACT_NAME" | tr -d ' ')
SIZE_KB=$(( SIZE_BYTES / 1024 ))
echo "[generators/wasm] OK: $OUT_DIR/$ARTIFACT_NAME (${SIZE_BYTES} bytes, ~${SIZE_KB} KB)"
