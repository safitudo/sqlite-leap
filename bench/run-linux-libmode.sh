#!/usr/bin/env bash
# Linux x86_64 lib-mode bench — runs lanes 2/3/4 via lib_bench harnesses
# (in-process, no CLI overhead). Mirrors the Mac libmode methodology so
# numbers are directly comparable.
#
# Run inside sqlite-leap-bench:linux-amd64 with /repo bind-mount.

set -uo pipefail
HOST_REPO="${HOST_REPO:-/repo}"
SCRATCH="/tmp/leap-libmode-$$"
mkdir -p "$SCRATCH"
echo "[libmode] staging" >&2
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
: > "$LOG"
echo "lane,target,value,units,elapsed_s,statements,errors,timestamp" > "$CSV"

note() { printf '[libmode] %s\n' "$*" | tee -a "$LOG"; }
note "uname: $(uname -a)"
note "glibc: $(ldd --version 2>&1 | head -n1)"
note "rustc: $(rustc --version)"
note "cc:    $(cc --version | head -n1)"

# --- build mainline lib_bench ----------------------------------------------
note "=== build mainline sqlite_lib_bench ==="
mkdir -p bench/baselines/bin
if gcc -O3 -o bench/baselines/bin/sqlite_lib_bench bench/baselines/sqlite_lib_bench.c -lsqlite3 2>>"$LOG"; then
    note "mainline lib_bench OK"
else
    note "mainline lib_bench FAIL"; exit 2
fi

# --- build leap-rust lib_bench --------------------------------------------
note "=== build leap-rust lib_bench ==="
( cd src-rust && \
  CARGO_PROFILE_RELEASE_LTO=off CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16 \
  cargo build --release --example lib_bench >>"$LOG" 2>&1 ) \
  && note "rust lib_bench OK" || { note "rust lib_bench FAIL"; }

# --- build leap-c lib_bench ------------------------------------------------
note "=== build leap-c lib_bench ==="
# C build needs -lm for floor/round/fmod.
( cd src-c && \
  CFLAGS="-O3" make >>"$LOG" 2>&1 ) || true
# Now build lib_bench directly (the build_lib_bench.sh expects mac paths).
if [ -f src-c/build_lib_bench.sh ]; then
    ( cd src-c && bash build_lib_bench.sh >>"$LOG" 2>&1 ) \
        && note "c lib_bench OK" || note "c lib_bench FAIL (see log)"
fi

# --- build leap-zig lib_bench ----------------------------------------------
note "=== build leap-zig lib_bench ==="
if command -v zig >/dev/null 2>&1; then
    note "zig version: $(zig version)"
    ( bash src-zig/build_lib_bench.sh >>"$LOG" 2>&1 ) \
        && note "zig lib_bench OK" || note "zig lib_bench FAIL (see log)"
else
    note "zig lib_bench SKIP (zig not on PATH)"
fi

# --- build leap-go lib_bench -----------------------------------------------
note "=== build leap-go lib_bench ==="
if command -v go >/dev/null 2>&1; then
    note "go version: $(go version)"
    mkdir -p src-go/bin
    ( cd src-go && go build -o bin/lib_bench ./cmd/lib_bench >>"$LOG" 2>&1 ) \
        && note "go lib_bench OK" || note "go lib_bench FAIL (see log)"
else
    note "go lib_bench SKIP (go not on PATH)"
fi

# --- locate leap-python lib_bench (script, no build) ----------------------
note "=== leap-python lib_bench ==="
if command -v python3 >/dev/null 2>&1; then
    note "python: $(python3 --version 2>&1)"
    [ -f src-python/examples/lib_bench.py ] && note "python lib_bench OK" || note "python lib_bench MISSING"
else
    note "python lib_bench SKIP (python3 not on PATH)"
fi

RUST_BIN="$SCRATCH/src-rust/target/release/examples/lib_bench"
C_BIN="$SCRATCH/src-c/build/lib_bench"
ZIG_BIN="$SCRATCH/src-zig/zig-out/bin/lib_bench"
GO_BIN="$SCRATCH/src-go/bin/lib_bench"
PY_BIN="$SCRATCH/src-python/examples/lib_bench.py"
MAIN_BIN="$SCRATCH/bench/baselines/bin/sqlite_lib_bench"

# Wrapper to run Python script as if it were a binary (for run_lane).
PY_RUN="$SCRATCH/src-python/run_lib_bench.sh"
cat > "$PY_RUN" <<EOF
#!/usr/bin/env bash
exec python3 "$PY_BIN" "\$@"
EOF
chmod +x "$PY_RUN"

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

run_lane() {
    local lane="$1" target="$2" bin="$3" workload="$4" extra_args="$5" units="$6"
    [ -x "$bin" ] || { note "  $lane $target SKIP (binary missing: $bin)"; return; }
    note "  $lane $target ..."
    local out
    out="$("$bin" "$workload" $extra_args 2>>"$LOG")" || { note "    FAIL"; return; }
    note "    raw: $out"
    local elapsed stmts errors qps
    elapsed=$(echo "$out" | grep -oE 'elapsed_seconds=[0-9.]+' | cut -d= -f2)
    stmts=$(echo "$out" | grep -oE 'statements=[0-9]+' | cut -d= -f2)
    errors=$(echo "$out" | grep -oE 'errors=[0-9]+' | cut -d= -f2)
    qps=$(echo "$out" | grep -oE 'qps=[0-9.]+' | cut -d= -f2)
    [ -z "$qps" ] && qps="NA"
    [ -z "$elapsed" ] && elapsed="NA"
    [ -z "$stmts" ] && stmts="NA"
    [ -z "$errors" ] && errors="0"
    echo "$lane,$target,$qps,$units,$elapsed,$stmts,$errors,$(ts)" >> "$CSV"
}

# --- Lane 2 (parse) — default mode times everything from corpus ------------
L2_WL="$SCRATCH/bench/lanes/02-parse-speed/corpus.sql"
if [ ! -f "$L2_WL" ]; then
    note "Lane 2 generating corpus..."
    ( cd "$SCRATCH/bench/lanes/02-parse-speed" && bash generate-corpus.sh >>"$LOG" 2>&1 ) || true
fi

# --- Lane 3 (SELECT) — default mode (times the SELECT tail) ----------------
L3_WL="$SCRATCH/bench/lanes/03-select-in-memory/workload.sql"
if [ ! -f "$L3_WL" ]; then
    ( cd "$SCRATCH/bench/lanes/03-select-in-memory" && bash generate-corpus.sh >>"$LOG" 2>&1 ) || true
fi

# --- Lane 4 (INSERT) — --time-setup mode -----------------------------------
L4_WL="$SCRATCH/bench/lanes/04-insert-throughput/workload.sql"
if [ ! -f "$L4_WL" ]; then
    ( cd "$SCRATCH/bench/lanes/04-insert-throughput" && bash generate-corpus.sh >>"$LOG" 2>&1 ) || true
fi

note "=== Lane 2 parse (--parse-only; see lane2-parseonly/SUMMARY.md) ==="
# --parse-only mode: tokenize + parse only (mainline: prepare_v2 + finalize,
# no step). The previous --time-setup mode timed full pipeline including
# table-scan execution; profiling proved Lane 2 became dominated by VDBE
# work, not parse. Parse-only is the apples-to-apples Lane 2 measurement.
run_lane parse-speed sqlite-mainline    "$MAIN_BIN" "$L2_WL" "--parse-only" statements_per_second
run_lane parse-speed sqlite-leap-rust   "$RUST_BIN" "$L2_WL" "--parse-only" statements_per_second
run_lane parse-speed sqlite-leap-c      "$C_BIN"    "$L2_WL" "--parse-only" statements_per_second
run_lane parse-speed sqlite-leap-zig    "$ZIG_BIN"  "$L2_WL" "--parse-only" statements_per_second
run_lane parse-speed sqlite-leap-go     "$GO_BIN"   "$L2_WL" "--parse-only" statements_per_second
# leap-python lib_bench doesn't implement --parse-only (always exec-mode);
# documented gap, not a perf issue. Skip on L2.
note "  parse-speed sqlite-leap-python SKIP (harness has no --parse-only mode)"

note "=== Lane 3 SELECT (in-RAM both sides; mainline lib_bench defaults to :memory:) ==="
run_lane select-in-memory sqlite-mainline    "$MAIN_BIN" "$L3_WL" "" selects_per_second
run_lane select-in-memory sqlite-leap-rust   "$RUST_BIN" "$L3_WL" "" selects_per_second
run_lane select-in-memory sqlite-leap-c      "$C_BIN"    "$L3_WL" "" selects_per_second
run_lane select-in-memory sqlite-leap-zig    "$ZIG_BIN"  "$L3_WL" "" selects_per_second
run_lane select-in-memory sqlite-leap-go     "$GO_BIN"   "$L3_WL" "" selects_per_second
run_lane select-in-memory sqlite-leap-python "$PY_RUN"   "$L3_WL" "" selects_per_second

note "=== Lane 4 INSERT (--db on-disk; WAL-tier asymmetry caveat in PUBLISHED.md §B.3) ==="
L4_DB=$(mktemp -u)
run_lane insert-throughput sqlite-mainline    "$MAIN_BIN" "$L4_WL" "--time-setup --db ${L4_DB}.main"   inserts_per_second
run_lane insert-throughput sqlite-leap-rust   "$RUST_BIN" "$L4_WL" "--time-setup --db ${L4_DB}.rust"   inserts_per_second
run_lane insert-throughput sqlite-leap-c      "$C_BIN"    "$L4_WL" "--time-setup --db ${L4_DB}.c"      inserts_per_second
run_lane insert-throughput sqlite-leap-zig    "$ZIG_BIN"  "$L4_WL" "--time-setup --db ${L4_DB}.zig"    inserts_per_second
run_lane insert-throughput sqlite-leap-go     "$GO_BIN"   "$L4_WL" "--time-setup --db ${L4_DB}.go"     inserts_per_second
run_lane insert-throughput sqlite-leap-python "$PY_RUN"   "$L4_WL" "--time-setup --db ${L4_DB}.python" inserts_per_second
rm -f "${L4_DB}".*

note "=== done ==="
echo "[libmode] CSV: $CSV"
cat "$CSV"
