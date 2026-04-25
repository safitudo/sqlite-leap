#!/usr/bin/env bash
# Lane 5 — Binary size, 5-target builder + reporter.
#
# Builds the smallest viable engine artifact for each target tree
# (parser + compiler + vdbe + storage exercised by the SELECT
# behavioral smoke) using each language's most aggressive size flags,
# strips where the toolchain doesn't already, then prints a single
# report table.
#
# Usage: bench/binary_size_5target.sh
# Prereqs on PATH: cargo, gcc/clang, zig (>=0.16), go, python3, sqlite3.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$REPO_ROOT/bench/results/binary_size_5target"
mkdir -p "$OUT_DIR"

bytes_of() {
    if stat -f "%z" "$1" >/dev/null 2>&1; then stat -f "%z" "$1"
    else stat -c "%s" "$1"; fi
}

# Parallel arrays (bash 3.2 compatible — no associative arrays).
TARGETS=(c rust zig go python)
SIZE_c=""; SIZE_rust=""; SIZE_zig=""; SIZE_go=""; SIZE_python=""
NOTE_c=""; NOTE_rust=""; NOTE_zig=""; NOTE_go=""; NOTE_python=""

# ---------------- Rust -----------------------------------------------
echo ">>> Rust (release-small: opt-level=z, lto=fat, panic=abort, strip)" >&2
(
    cd "$REPO_ROOT/src-rust"
    cargo build --profile release-small --example select_behavioral_smoke >&2
)
RUST_BIN="$REPO_ROOT/src-rust/target/release-small/examples/select_behavioral_smoke"
SIZE_rust="$(bytes_of "$RUST_BIN")"
NOTE_rust="cargo --profile release-small"

# ---------------- C --------------------------------------------------
echo ">>> C (-Os, strip, dead-code eliminations)" >&2
mkdir -p "$OUT_DIR/c"
C_BIN="$OUT_DIR/c/select_behavioral_smoke"
C_SRCS=(
  "$REPO_ROOT/src-c/core.c"
  "$REPO_ROOT/src-c/storage.c"
  "$REPO_ROOT/src-c/parser/tokenizer.c"
  "$REPO_ROOT/src-c/parser/expr.c"
  "$REPO_ROOT/src-c/parser/select_stmt.c"
  "$REPO_ROOT/src-c/compiler/expr_compile.c"
  "$REPO_ROOT/src-c/compiler/select_compile.c"
  "$REPO_ROOT/src-c/vdbe/mod.c"
  "$REPO_ROOT/src-c/vdbe/opcodes_core.c"
  "$REPO_ROOT/src-c/vdbe/opcodes_rows.c"
  "$REPO_ROOT/src-c/vdbe/opcodes_control.c"
  "$REPO_ROOT/src-c/vdbe/opcodes_expr.c"
  "$REPO_ROOT/src-c/vdbe/opcodes_scan.c"
  "$REPO_ROOT/src-c/vdbe/opcodes_agg.c"
  "$REPO_ROOT/src-c/vdbe/opcodes_window.c"
  "$REPO_ROOT/src-c/examples/select_behavioral_smoke.c"
)
# -Os = optimize for size; -ffunction-sections -fdata-sections + -Wl,-dead_strip
# (Apple ld) / -Wl,--gc-sections (GNU ld) drop unused symbols. Pick the right
# flag for the linker we're invoking.
LDDEAD="-Wl,-dead_strip"
if [[ "$(uname)" != "Darwin" ]]; then LDDEAD="-Wl,--gc-sections"; fi
gcc -std=c11 -Os -fno-asynchronous-unwind-tables \
    -ffunction-sections -fdata-sections -Wno-unused-parameter \
    $LDDEAD \
    -I "$REPO_ROOT/src-c" \
    "${C_SRCS[@]}" -o "$C_BIN" 2>&1 | sed 's/^/  /' >&2 || true
strip -x "$C_BIN" 2>/dev/null || strip "$C_BIN" 2>/dev/null || true
SIZE_c="$(bytes_of "$C_BIN")"
NOTE_c="gcc -Os -ffunction-sections + dead-strip + strip"

# ---------------- Zig ------------------------------------------------
echo ">>> Zig (-Doptimize=ReleaseSmall, strip)" >&2
(
    cd "$REPO_ROOT/src-zig"
    # -fstrip is the modern flag; some 0.16 builds accept -Dstrip=true. Use
    # the optimize flag (always supported) and post-strip.
    zig build -Doptimize=ReleaseSmall select-smoke >&2 || \
        zig build -Doptimize=ReleaseSmall >&2
)
ZIG_BIN="$REPO_ROOT/src-zig/zig-out/bin/select_behavioral_smoke"
strip -x "$ZIG_BIN" 2>/dev/null || strip "$ZIG_BIN" 2>/dev/null || true
SIZE_zig="$(bytes_of "$ZIG_BIN")"
NOTE_zig="zig build -Doptimize=ReleaseSmall + strip"

# ---------------- Go -------------------------------------------------
echo ">>> Go (-ldflags '-s -w' -trimpath)" >&2
mkdir -p "$OUT_DIR/go"
GO_BIN="$OUT_DIR/go/select_behavioral_smoke"
(
    cd "$REPO_ROOT/src-go"
    go build -trimpath -ldflags '-s -w' -o "$GO_BIN" ./cmd/select_behavioral_smoke >&2
)
SIZE_go="$(bytes_of "$GO_BIN")"
NOTE_go="go build -trimpath -ldflags '-s -w'"

# ---------------- Python ---------------------------------------------
# Python isn't a directly-comparable static binary. Honest report:
# total .py source bytes for the engine package + the interpreter footprint
# (sys.executable size). We list both rather than fabricate a single number.
echo ">>> Python (source bytes; interpreter footprint reported separately)" >&2
PY_SRC_BYTES="$(find "$REPO_ROOT/src-python/leap_sqlite" -name '*.py' -print0 \
    | xargs -0 wc -c 2>/dev/null | awk '/total$/ {print $1; exit} END{}' )"
# `wc -c total` only emits when there are >1 files; handle 1-file case.
if [[ -z "$PY_SRC_BYTES" ]]; then
    PY_SRC_BYTES="$(find "$REPO_ROOT/src-python/leap_sqlite" -name '*.py' -exec cat {} + | wc -c | tr -d ' ')"
fi
PY_INTERP_RAW="$(python3 -c 'import sys; print(sys.executable)')"
# Resolve symlinks so we measure the real binary, not the shim.
PY_INTERP="$(python3 -c "import os,sys;print(os.path.realpath(sys.executable))")"
PY_INTERP_BYTES="$(bytes_of "$PY_INTERP")"
SIZE_python="$PY_SRC_BYTES"
NOTE_python=".py source only; interpreter $(basename "$PY_INTERP") = $PY_INTERP_BYTES bytes (excluded)"

# ---------------- mainline sqlite3 baseline --------------------------
SQLITE_BIN="$(command -v sqlite3 || true)"
if [[ -n "$SQLITE_BIN" ]]; then
    SQLITE_BYTES="$(bytes_of "$SQLITE_BIN")"
else
    SQLITE_BYTES=0
fi

# ---------------- Report ---------------------------------------------
fmt_kb() { python3 -c "import sys;print(f'{int(sys.argv[1])/1024:.1f}')" "$1"; }
fmt_ratio() {
    if [[ "$2" -eq 0 ]]; then echo "n/a"
    else python3 -c "import sys;print(f'{int(sys.argv[1])/int(sys.argv[2]):.2f}x')" "$1" "$2"; fi
}

REPORT="$OUT_DIR/REPORT.md"
{
    echo "# Lane 5 — 5-target binary size"
    echo
    echo "Generated $(date -u +'%Y-%m-%dT%H:%M:%SZ') on $(uname -sm)."
    echo "Mainline sqlite3 baseline: \`$SQLITE_BIN\` = $SQLITE_BYTES bytes ($(fmt_kb "$SQLITE_BYTES") KB)."
    echo
    echo "Each row builds the same SELECT behavioral smoke (parser + compiler + VDBE + storage)"
    echo "with the smallest-binary flags available in that toolchain."
    echo
    echo "| target | bytes | KB | vs sqlite3 mainline | notes |"
    echo "|---|---:|---:|---:|---|"
    for t in c rust zig go python; do
        eval "b=\$SIZE_$t"
        eval "n=\$NOTE_$t"
        echo "| $t | $b | $(fmt_kb "$b") | $(fmt_ratio "$b" "$SQLITE_BYTES") | $n |"
    done
    echo "| sqlite3 (mainline) | $SQLITE_BYTES | $(fmt_kb "$SQLITE_BYTES") | 1.00x | system \`$(sqlite3 -version 2>/dev/null | awk '{print $1}')\` |"
    echo
    # Smallest non-Python target (Python is .py source, not comparable).
    smallest_t=""; smallest_b=999999999999
    for t in c rust zig go; do
        eval "b=\$SIZE_$t"
        if (( b < smallest_b )); then smallest_b=$b; smallest_t=$t; fi
    done
    echo "**Smallest binary target:** $smallest_t at $smallest_b bytes ($(fmt_kb "$smallest_b") KB)."
    if [[ "$SQLITE_BYTES" -gt 0 ]] && (( SIZE_c < SQLITE_BYTES )); then
        echo "**C target beats mainline sqlite3:** YES ($(fmt_ratio "$SIZE_c" "$SQLITE_BYTES") of mainline)."
    elif [[ "$SQLITE_BYTES" -gt 0 ]]; then
        echo "**C target beats mainline sqlite3:** NO (C = $SIZE_c bytes vs mainline $SQLITE_BYTES bytes)."
    fi
    echo
    echo "Notes:"
    echo "- Python is reported as engine-package \`.py\` source bytes; the CPython interpreter"
    echo "  ($(basename "$PY_INTERP"), $PY_INTERP_BYTES bytes) is NOT bundled and not counted."
    echo "- Mainline sqlite3 includes the CLI shell, readline, ICU shim — apples-to-oranges"
    echo "  vs leap-sqlite which only embeds the engine; we report it as published."
    echo "- All builds invoked from this script are reproducible: see source for flags."
} > "$REPORT"

cat "$REPORT"
echo
echo "report written to: $REPORT"
