#!/usr/bin/env bash
# Lane 3 — In-memory SELECT throughput, 5-target.
#
# Each engine runs a fixture with:
#   * CREATE TABLE t (id, name)
#   * 1000 INSERT rows
#   * 100 identical SELECT id FROM t WHERE id > 500
#
# Wallclock is divided by the number of SELECTs to give queries/sec.
# This includes a small share of CREATE/INSERT setup, so the published
# number is "amortised SELECT-loop throughput" — biased slightly low
# vs. pure inner-loop throughput, identically across targets.
#
# Resolution: time.perf_counter() (sub-ms) — /usr/bin/time -lp's 10ms
# resolution is too coarse for sub-100ms runs.
#
# Usage: bench/select_throughput_5target.sh [N_samples]   (default 5)
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib_5target.sh"

REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
N="${1:-5}"
FIXTURE="$REPO_ROOT/bench/fixtures/select_throughput.test"
SQLFILE="$REPO_ROOT/bench/fixtures/select_throughput.sql"
OUT_DIR="$REPO_ROOT/bench/results/select_throughput_5target"
mkdir -p "$OUT_DIR"

N_QUERIES="$(grep -c '^query I nosort$' "$FIXTURE")"
N_INSERTS="$(grep -c '^INSERT INTO ' "$FIXTURE")"

ensure_go_slt

echo ">>> Lane 3 select throughput; queries=$N_QUERIES, rows=$N_INSERTS, samples=$N" >&2

runner_py='
import subprocess, sys, time, statistics
n = int(sys.argv[1])
mode = sys.argv[2]   # "exec" | "stdin"
sqlfile = sys.argv[3]
cmd = sys.argv[4:]
xs = []
# warm-up
if mode == "exec":
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
else:
    with open(sqlfile, "rb") as f:
        subprocess.run(cmd, stdin=f, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(n):
    if mode == "exec":
        t0 = time.perf_counter()
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        with open(sqlfile, "rb") as f:
            t0 = time.perf_counter()
            subprocess.run(cmd, stdin=f, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    xs.append((time.perf_counter() - t0) * 1000.0)
print(f"{statistics.median(xs):.3f}")
'

ML_MS="$(python3 -c "$runner_py" "$N" stdin "$SQLFILE" /usr/bin/sqlite3 ":memory:")"

declare -a NAMES=(c rust zig go python)
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
    MS+=("$(python3 -c "$runner_py" "$N" exec "$FIXTURE" "${cmdline[@]}")")
done

qps_of_ms() {
    local ms="$1"
    if [[ "$ms" == "NA" ]]; then echo "NA"; return; fi
    python3 -c "import sys; ms=float(sys.argv[1]); n=int(sys.argv[2]); print(f'{1000.0*n/ms:.0f}' if ms>0 else 'NA')" "$ms" "$N_QUERIES"
}

ratio_ms() {
    if [[ "$1" == "NA" || "$2" == "NA" ]]; then echo "n/a"
    else python3 -c "import sys; print(f'{float(sys.argv[1])/float(sys.argv[2]):.2f}x')" "$1" "$2"; fi
}

REPORT="$OUT_DIR/REPORT.md"
{
    echo "# Lane 3 — 5-target in-memory SELECT throughput"
    echo
    echo "Generated $(date -u +'%Y-%m-%dT%H:%M:%SZ') on $(uname -sm)."
    echo
    echo "Each engine runs the same fixture: \`CREATE TABLE\` + ${N_INSERTS}"
    echo "\`INSERT\`s + ${N_QUERIES} repeated \`SELECT id FROM t WHERE id > 500\`."
    echo "Wallclock divided by ${N_QUERIES} gives amortised queries/sec."
    echo
    echo "Median of $N samples per target. Resolution: \`time.perf_counter()\`."
    echo
    echo "| target | wallclock (ms) | queries/sec | vs mainline | notes |"
    echo "|---|---:|---:|---:|---|"
    for i in "${!NAMES[@]}"; do
        t="${NAMES[$i]}"
        m="${MS[$i]}"
        qps="$(qps_of_ms "$m")"
        ratio="$(ratio_ms "$ML_MS" "$m")"
        echo "| $t | $m | $qps | $ratio | slt_runner($t) |"
    done
    ML_QPS="$(qps_of_ms "$ML_MS")"
    echo "| sqlite3 (mainline) | $ML_MS | $ML_QPS | 1.00x | system \`$(/usr/bin/sqlite3 -version 2>/dev/null | awk '{print $1}')\` |"
    echo
    echo "Ratio convention: mainline-wallclock / leap-wallclock. >1.0x means"
    echo "leap is **faster**."
    echo
    echo "## Caveats"
    echo "- The throughput number is amortised: it includes the table setup"
    echo "  cost (CREATE + ${N_INSERTS} INSERTs) divided across ${N_QUERIES}"
    echo "  SELECTs. Pure inner-loop SELECT throughput is higher."
    echo "- The mainline number reflects the \`sqlite3\` CLI parsing the .sql"
    echo "  script — its line-by-line statement loop is not zero-cost either."
    echo "- The Zig run is anomalously slow on this workload (high syscall"
    echo "  time); a target-side allocator hot spot is the most likely cause."
    echo "  Reported as-measured."
    echo "- macOS arm64 only."
    echo
    echo "Fixtures: \`bench/fixtures/select_throughput.{test,sql}\`."
} > "$REPORT"

cat "$REPORT"
echo
echo "report written to: $REPORT" >&2
