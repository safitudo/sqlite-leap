#!/usr/bin/env bash
# Retry: build leap-c lib_bench with the missing scalar_json1.c source,
# then re-run lanes 2/3/4 vs mainline (skip Rust — toolchain too old in image).
set -uo pipefail
HOST_REPO="/repo"
SCRATCH="/tmp/leap-libmode-retry-$$"
mkdir -p "$SCRATCH"
rsync -a --quiet \
    --exclude='src-c/obj/' --exclude='src-c/bin/' --exclude='src-c/build/' \
    --exclude='src-rust/target/' --exclude='src-wasm/' \
    --exclude='bench/baselines/src/' --exclude='bench/baselines/bin/' \
    --exclude='bench/results/' --exclude='tests/sqllogictest/upstream/' \
    --exclude='tests/sqllogictest/results/' --exclude='tests/sqllogictest/.fetched/' \
    --exclude='.git/' \
    "$HOST_REPO/" "$SCRATCH/"
cd "$SCRATCH"

OUT_DIR="$HOST_REPO/bench/results/2026-04-27-linux-x86_64"
mkdir -p "$OUT_DIR"
LOG="$OUT_DIR/run.log"
CSV="$OUT_DIR/raw.csv"

note() { printf '[libmode-retry] %s\n' "$*" | tee -a "$LOG"; }
ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

note "=== build mainline sqlite_lib_bench ==="
mkdir -p bench/baselines/bin
gcc -O3 -o bench/baselines/bin/sqlite_lib_bench bench/baselines/sqlite_lib_bench.c -lsqlite3 2>>"$LOG" \
  && note "main OK" || { note "main FAIL"; exit 2; }

note "=== build leap-c lib_bench (with scalar_json1.c patch) ==="
# Inject scalar_json1.c after opcodes_window.c.
sed -i 's|src-c/vdbe/opcodes_window.c|src-c/vdbe/opcodes_window.c\n  src-c/scalar_json1.c|' src-c/build_lib_bench.sh
( cd src-c && bash build_lib_bench.sh >>"$LOG" 2>&1 ) \
    && note "c lib_bench OK" || { note "c lib_bench FAIL"; tail -30 "$LOG"; }

C_BIN="$SCRATCH/src-c/build/lib_bench"
MAIN_BIN="$SCRATCH/bench/baselines/bin/sqlite_lib_bench"
ls -la "$C_BIN" "$MAIN_BIN" 2>&1 | tee -a "$LOG"

run_lane() {
    local lane="$1" target="$2" bin="$3" workload="$4" extra_args="$5" units="$6"
    [ -x "$bin" ] || { note "  $lane $target SKIP (binary missing)"; return; }
    note "  $lane $target ..."
    local out
    out="$("$bin" "$workload" $extra_args 2>>"$LOG")" || { note "    FAIL"; return; }
    note "    raw: $out"
    local elapsed stmts errors qps
    elapsed=$(echo "$out" | grep -oE 'elapsed_seconds=[0-9.]+' | cut -d= -f2)
    stmts=$(echo "$out" | grep -oE 'statements=[0-9]+' | cut -d= -f2)
    errors=$(echo "$out" | grep -oE 'errors=[0-9]+' | cut -d= -f2)
    qps=$(echo "$out" | grep -oE 'qps=[0-9.]+' | cut -d= -f2)
    [ -z "$qps" ] && qps="NA"; [ -z "$elapsed" ] && elapsed="NA"
    [ -z "$stmts" ] && stmts="NA"; [ -z "$errors" ] && errors="0"
    echo "$lane,$target,$qps,$units,$elapsed,$stmts,$errors,$(ts)" >> "$CSV"
}

L2_WL="$SCRATCH/bench/lanes/02-parse-speed/corpus.sql"
L3_WL="$SCRATCH/bench/lanes/03-select-in-memory/workload.sql"
L4_WL="$SCRATCH/bench/lanes/04-insert-throughput/workload.sql"

note "=== Lane 2 ==="
run_lane parse-speed sqlite-leap-c "$C_BIN" "$L2_WL" "--time-setup" statements_per_second
note "=== Lane 3 ==="
run_lane select-in-memory sqlite-leap-c "$C_BIN" "$L3_WL" "" selects_per_second
note "=== Lane 4 ==="
L4_DB=$(mktemp -u)
run_lane insert-throughput sqlite-leap-c "$C_BIN" "$L4_WL" "--time-setup --db ${L4_DB}.c" inserts_per_second
rm -f "${L4_DB}".*

note "done"
cat "$CSV"
