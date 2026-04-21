#!/usr/bin/env bash
# Shared helpers for every lane's run.sh. Sourced, not executed.
# Conventions used by every caller:
#   - TARGET          — value of --target flag
#   - BENCH_ROOT      — absolute path to bench/
#   - REPO_ROOT       — absolute path to repo root
#   - LANE_NAME       — lane identifier emitted in the CSV `lane` column
set -euo pipefail

# Resolve repo layout regardless of where the script was invoked from.
_lib_self="${BASH_SOURCE[0]}"
BENCH_ROOT="$(cd -- "$(dirname -- "$_lib_self")/.." && pwd)"
REPO_ROOT="$(cd -- "$BENCH_ROOT/.." && pwd)"
export BENCH_ROOT REPO_ROOT

parse_target_flag() {
    # Usage: parse_target_flag "$@" — sets global TARGET.
    TARGET=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --target) TARGET="$2"; shift 2 ;;
            --target=*) TARGET="${1#--target=}"; shift ;;
            -h|--help)
                echo "Usage: $0 --target <sqlite-leap-c|sqlite-leap-rust|sqlite-mainline|turso>" >&2
                exit 2
                ;;
            *) echo "unknown arg: $1" >&2; exit 2 ;;
        esac
    done
    if [[ -z "$TARGET" ]]; then
        echo "--target is required" >&2
        exit 2
    fi
    export TARGET
}

# Resolve the binary for a given target. Echoes the absolute path on stdout
# if found; prints nothing and returns 1 if the binary is missing.
binary_for_target() {
    local target="$1"
    local path=""
    case "$target" in
        sqlite-leap-c)    path="$REPO_ROOT/src-c/bin/sqllogictest" ;;
        sqlite-leap-rust) path="$REPO_ROOT/src-rust/target/release/sqllogictest" ;;
        sqlite-mainline)  path="$BENCH_ROOT/baselines/bin/sqlite-mainline" ;;
        turso)            path="$BENCH_ROOT/baselines/bin/turso" ;;
        # Library-variant adapter: links against `turso_core` directly, no
        # CLI shell (no rustyline/syntect/mimalloc/tracing-subscriber). See
        # bench/baselines/turso-core-harness/README.md for methodology.
        turso-core)       path="$BENCH_ROOT/baselines/turso-core-harness/target/release/turso-core-bench" ;;
        *) echo "unknown target: $target" >&2; return 2 ;;
    esac
    if [[ -x "$path" ]]; then
        echo "$path"
        return 0
    fi
    return 1
}

# Emit the single canonical CSV line to stdout.
emit_csv() {
    local lane="$1" target="$2" value="$3" units="$4"
    local ts
    ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    printf "%s,%s,%s,%s,%s\n" "$lane" "$target" "$value" "$units" "$ts"
}

emit_missing() {
    local lane="$1" target="$2"
    emit_csv "$lane" "$target" "NA" "missing-binary"
    exit 1
}

# Detect hyperfine; echo the executable path if found, else echo "".
detect_hyperfine() {
    command -v hyperfine || true
}

# Portable monotonic nanosecond clock. Falls back to Python on macOS where
# date(1) lacks %N.
now_ns() {
    if date +%N 2>/dev/null | grep -q '^[0-9]'; then
        date +%s%N
    else
        python3 -c 'import time; print(time.monotonic_ns())'
    fi
}

# Median of N timings (whitespace-separated floats, seconds). Echoes median.
median() {
    python3 -c '
import sys, statistics
vals = [float(x) for x in sys.stdin.read().split() if x]
print(f"{statistics.median(vals):.9f}")
'
}

# Run a command N times and echo the median wall-clock (seconds) to stdout.
# Arguments: runs warmup -- <command>
time_median() {
    local runs="$1" warmup="$2"
    shift 2
    [[ "$1" == "--" ]] && shift
    local hf; hf="$(detect_hyperfine)"
    if [[ -n "$hf" ]]; then
        # hyperfine 1.18+ with `-- a b c` parses as a single command token with
        # extra positional args, which it silently drops for some invocations.
        # Build a shell-quoted single-string command and rely on hyperfine's
        # default shell invocation.
        local cmd_str=""
        local a
        for a in "$@"; do
            # shell-quote each token
            cmd_str+="${cmd_str:+ }$(printf '%q' "$a")"
        done
        # hyperfine writes the human summary to stdout AND the JSON to the
        # --export-json path. Give it a temp file so we get clean JSON.
        local json_tmp
        json_tmp="$(mktemp)"
        "$hf" --warmup "$warmup" --runs "$runs" --export-json "$json_tmp" "$cmd_str" >/dev/null 2>&1 || true
        if [[ -s "$json_tmp" ]]; then
            python3 -c '
import json, sys
data = json.loads(sys.stdin.read())
median = data["results"][0]["median"]
print(f"{median:.9f}")
' < "$json_tmp"
            rm -f "$json_tmp"
            return 0
        fi
        rm -f "$json_tmp"
    fi
    # Fallback: Python-timed loop.
    python3 - "$runs" "$warmup" "$@" <<'PY'
import subprocess, sys, time, statistics
runs = int(sys.argv[1]); warmup = int(sys.argv[2])
cmd = sys.argv[3:]
for _ in range(warmup):
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
ts = []
for _ in range(runs):
    t0 = time.monotonic()
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ts.append(time.monotonic() - t0)
print(f"{statistics.median(ts):.9f}")
PY
}

# Peak RSS in bytes for a command. Uses /usr/bin/time -l on macOS, -v on Linux.
peak_rss_bytes() {
    local out
    if [[ "$(uname)" == "Darwin" ]]; then
        # -l prints "maximum resident set size" in BYTES on modern macOS.
        out="$(/usr/bin/time -l "$@" 2>&1 >/dev/null || true)"
        # Look for the line; extract first integer.
        awk '/maximum resident set size/ { print $1; exit }' <<<"$out"
    else
        # Linux: -v prints "Maximum resident set size (kbytes): N".
        out="$(/usr/bin/time -v "$@" 2>&1 >/dev/null || true)"
        awk '/Maximum resident set size/ { print $6 * 1024; exit }' <<<"$out"
    fi
}
