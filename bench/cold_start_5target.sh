#!/usr/bin/env bash
# Lane 1 — Cold start, 5-target.
#
# Measures wallclock from process exec to completion of a one-record
# SLT fixture (`SELECT 1 + 2`). The SLT runner does open + parse +
# compile + execute + emit; on a one-record fixture, total wallclock
# is dominated by cold-start cost (image load, runtime init, first
# allocator hit). Mainline baseline: `sqlite3 :memory: "SELECT 1+2;"`.
#
# Uses Python's time.perf_counter() for sub-millisecond resolution —
# /usr/bin/time -lp only resolves to 10ms which is coarser than the
# fastest target's cold-start time (~2-3ms).
#
# Usage: bench/cold_start_5target.sh [N_samples]   (default 21)
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib_5target.sh"

REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
N="${1:-21}"
FIXTURE="$REPO_ROOT/bench/fixtures/cold_start.test"
OUT_DIR="$REPO_ROOT/bench/results/cold_start_5target"
mkdir -p "$OUT_DIR"

ensure_go_slt

echo ">>> Lane 1 cold start, N=$N samples per target" >&2

# Python sub-program: takes argv = [N, *cmd]; runs cmd N times,
# emits "<median_ms>" on stdout.
runner_py='
import subprocess, sys, time, statistics
n = int(sys.argv[1])
cmd = sys.argv[2:]
xs = []
# warm-up (page-cache the image; fair to all targets)
subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(n):
    t0 = time.perf_counter()
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    xs.append((time.perf_counter() - t0) * 1000.0)
print(f"{statistics.median(xs):.3f}")
'

ML_MS="$(python3 -c "$runner_py" "$N" /usr/bin/sqlite3 ":memory:" "SELECT 1+2;")"

declare -a NAMES=(c rust zig go python)
declare -a CMD=()
declare -a MS=()
for t in "${NAMES[@]}"; do
    case "$t" in
      c)      cmdline=("$C_SLT" "$FIXTURE") ;;
      rust)   cmdline=("$RUST_SLT" "$FIXTURE") ;;
      zig)    cmdline=("$ZIG_SLT" "$FIXTURE") ;;
      go)     cmdline=("$GO_SLT_BIN" "$FIXTURE") ;;
      python) cmdline=(python3 "$PY_DRIVER" "$FIXTURE") ;;
    esac
    echo ">>> sampling $t..." >&2
    MS+=("$(python3 -c "$runner_py" "$N" "${cmdline[@]}")")
done

ratio_ms() {
    if [[ "$1" == "NA" || "$2" == "NA" ]]; then echo "n/a"
    else python3 -c "import sys; print(f'{float(sys.argv[1])/float(sys.argv[2]):.2f}x')" "$1" "$2"; fi
}

REPORT="$OUT_DIR/REPORT.md"
{
    echo "# Lane 1 — 5-target cold start"
    echo
    echo "Generated $(date -u +'%Y-%m-%dT%H:%M:%SZ') on $(uname -sm)."
    echo
    echo "Median wallclock over $N samples for a process running a single"
    echo "\`SELECT 1+2\` query in memory. Includes process spawn, image load,"
    echo "runtime init, parser/compiler/VDBE invocation, and result emission."
    echo "One warm-up run is discarded before measurement to page-cache the"
    echo "image (identically for every target)."
    echo
    echo "Mainline baseline: \`sqlite3 :memory: \"SELECT 1+2;\"\`."
    echo "Each leap target runs the equivalent fixture via its slt_runner."
    echo
    echo "Resolution: Python \`time.perf_counter()\` (sub-millisecond)."
    echo
    echo "| target | median (ms) | vs mainline | notes |"
    echo "|---|---:|---:|---|"
    for i in "${!NAMES[@]}"; do
        t="${NAMES[$i]}"
        m="${MS[$i]}"
        ratio="$(ratio_ms "$ML_MS" "$m")"
        echo "| $t | $m | $ratio | slt_runner($t) on cold_start.test |"
    done
    echo "| sqlite3 (mainline) | $ML_MS | 1.00x | system \`$(/usr/bin/sqlite3 -version 2>/dev/null | awk '{print $1}')\` |"
    echo
    echo "Ratio convention: mainline-wallclock / leap-wallclock. >1.00x means"
    echo "leap is **faster** to cold-start."
    echo
    echo "## Caveats"
    echo "- macOS arm64 only. Linux cross-validation needed for publication."
    echo "- The Python row includes CPython interpreter init"
    echo "  (\`$(python3 -c 'import sys;print(sys.version.split()[0])')\`) — not directly"
    echo "  comparable to native binaries."
    echo "- Mainline \`sqlite3\` is the CLI shell binary (includes readline + cmd"
    echo "  parsing). A pure libsqlite3 \`sqlite3_open + sqlite3_exec\` would be"
    echo "  lower; we report the published binary as our baseline."
    echo
    echo "Fixture: \`bench/fixtures/cold_start.test\`."
} > "$REPORT"

cat "$REPORT"
echo
echo "report written to: $REPORT" >&2
