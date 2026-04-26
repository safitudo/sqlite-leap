#!/usr/bin/env bash
# Lane 3 — In-memory SELECT throughput, 5-target. Two-column edition.
#
# Each engine runs TWO fixtures back-to-back:
#
#   1) AMORTIZED  (select_throughput.{test,sql}): CREATE + 1000 INSERTs +
#      100 × `SELECT id FROM t WHERE id > 500`. Wallclock / 100 = q/s.
#      Honest about full pipeline cost (process startup + INSERT setup
#      + parse + 100 SELECTs amortized).
#
#   2) PURE-LOOP  (select_throughput_pure.{test,sql}): CREATE + 1000
#      INSERTs + 10000 × `SELECT id FROM t WHERE id = 750`. Wallclock /
#      10000 = q/s. The 10:1 SELECT:INSERT ratio (vs 0.1:1 in (1))
#      makes the inner SELECT loop dominant; setup is ~5-10% of total.
#      Predicate is selective (returns 1 row) so render cost is minimal
#      and we measure scan-and-filter throughput on the engine side.
#
# Both numbers go in the report. Pure-loop is the publication-grade
# "engine SELECT throughput" claim; amortized is the "full pipeline"
# claim.
#
# Resolution: time.perf_counter() (sub-ms).
#
# Usage: bench/select_throughput_5target.sh [N_samples]   (default 5)
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib_5target.sh"

REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
N="${1:-5}"

FIX_AMORT="$REPO_ROOT/bench/fixtures/select_throughput.test"
SQL_AMORT="$REPO_ROOT/bench/fixtures/select_throughput.sql"
FIX_PURE="$REPO_ROOT/bench/fixtures/select_throughput_pure.test"
SQL_PURE="$REPO_ROOT/bench/fixtures/select_throughput_pure.sql"

OUT_DIR="$REPO_ROOT/bench/results/select_throughput_5target"
mkdir -p "$OUT_DIR"

NQ_AMORT="$(grep -c '^query I nosort$' "$FIX_AMORT")"
NI_AMORT="$(grep -c '^INSERT INTO ' "$FIX_AMORT")"
NQ_PURE="$(grep -c '^query I nosort$' "$FIX_PURE")"
NI_PURE="$(grep -c '^INSERT INTO ' "$FIX_PURE")"

ensure_go_slt

echo ">>> Lane 3 select throughput (two-column)" >&2
echo "    amortized: queries=$NQ_AMORT, rows=$NI_AMORT" >&2
echo "    pure-loop: queries=$NQ_PURE, rows=$NI_PURE" >&2
echo "    samples=$N" >&2

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

# --- AMORTIZED measurements -----------------------------------------------
echo ">>> sampling mainline (amortized)..." >&2
ML_MS_AMORT="$(python3 -c "$runner_py" "$N" stdin "$SQL_AMORT" /usr/bin/sqlite3 ":memory:")"
echo ">>> sampling mainline (pure-loop)..." >&2
ML_MS_PURE="$(python3 -c "$runner_py" "$N" stdin "$SQL_PURE" /usr/bin/sqlite3 ":memory:")"

declare -a NAMES=(c rust zig go python)
declare -a MS_AMORT=()
declare -a MS_PURE=()
for t in "${NAMES[@]}"; do
    case "$t" in
      c)      cmdline=("$C_SLT") ;;
      rust)   cmdline=("$RUST_SLT") ;;
      zig)    cmdline=("$ZIG_SLT") ;;
      go)     cmdline=("$GO_SLT_BIN") ;;
      python) cmdline=(python3 "$PY_DRIVER") ;;
    esac
    echo ">>> sampling $t (amortized)..." >&2
    MS_AMORT+=("$(python3 -c "$runner_py" "$N" exec "$FIX_AMORT" "${cmdline[@]}" "$FIX_AMORT")")
    echo ">>> sampling $t (pure-loop)..." >&2
    MS_PURE+=("$(python3 -c "$runner_py" "$N" exec "$FIX_PURE" "${cmdline[@]}" "$FIX_PURE")")
done

qps_of_ms() {
    local ms="$1" nq="$2"
    if [[ "$ms" == "NA" ]]; then echo "NA"; return; fi
    python3 -c "import sys; ms=float(sys.argv[1]); n=int(sys.argv[2]); print(f'{1000.0*n/ms:.0f}' if ms>0 else 'NA')" "$ms" "$nq"
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
    echo "Each engine is sampled on **two** fixtures, $N samples each, median reported."
    echo "Resolution: \`time.perf_counter()\`."
    echo
    echo "## Fixtures"
    echo
    echo "| fixture | rows | SELECTs | predicate | what it measures |"
    echo "|---|---:|---:|---|---|"
    echo "| amortized | $NI_AMORT | $NQ_AMORT | \`id > 500\` (500 rows) | full pipeline (startup + INSERT setup amortized over $NQ_AMORT SELECTs) |"
    echo "| pure-loop | $NI_PURE | $NQ_PURE | \`id = 750\` (1 row) | engine inner-loop (setup is ~5-10% of total at 10:1 SELECT:INSERT) |"
    echo
    echo "## Amortized (full pipeline)"
    echo
    echo "Wallclock divided by ${NQ_AMORT} SELECTs."
    echo
    echo "| target | wallclock (ms) | queries/sec | vs mainline |"
    echo "|---|---:|---:|---:|"
    for i in "${!NAMES[@]}"; do
        t="${NAMES[$i]}"
        m="${MS_AMORT[$i]}"
        qps="$(qps_of_ms "$m" "$NQ_AMORT")"
        ratio="$(ratio_ms "$ML_MS_AMORT" "$m")"
        echo "| $t | $m | $qps | $ratio |"
    done
    ML_QPS_AMORT="$(qps_of_ms "$ML_MS_AMORT" "$NQ_AMORT")"
    echo "| sqlite3 (mainline) | $ML_MS_AMORT | $ML_QPS_AMORT | 1.00x |"
    echo
    echo "## Pure-loop (engine inner-loop)"
    echo
    echo "Wallclock divided by ${NQ_PURE} SELECTs. Setup amortizes to ~5-10%."
    echo
    echo "| target | wallclock (ms) | queries/sec | vs mainline |"
    echo "|---|---:|---:|---:|"
    for i in "${!NAMES[@]}"; do
        t="${NAMES[$i]}"
        m="${MS_PURE[$i]}"
        qps="$(qps_of_ms "$m" "$NQ_PURE")"
        ratio="$(ratio_ms "$ML_MS_PURE" "$m")"
        echo "| $t | $m | $qps | $ratio |"
    done
    ML_QPS_PURE="$(qps_of_ms "$ML_MS_PURE" "$NQ_PURE")"
    echo "| sqlite3 (mainline) | $ML_MS_PURE | $ML_QPS_PURE | 1.00x |"
    echo
    echo "Ratio convention: mainline-wallclock / leap-wallclock. >1.0x means"
    echo "leap is **faster**."
    echo
    echo "## Caveats"
    echo
    echo "- The amortized number shares a fraction of the table-setup cost"
    echo "  ($NI_AMORT INSERTs / $NQ_AMORT SELECTs = 10x setup overhead)."
    echo "  The pure-loop number flips the ratio (1:10) and uses a lean"
    echo "  predicate so render cost is negligible — closer to true engine"
    echo "  SELECT throughput."
    echo "- The two predicates differ. Amortized returns 500 rows per query;"
    echo "  pure-loop returns 1 row. Both perform a full table scan over"
    echo "  $NI_PURE rows (no index)."
    echo "- The mainline number reflects the \`sqlite3\` CLI parsing the .sql"
    echo "  script — its line-by-line statement loop is not zero-cost either."
    echo "- macOS arm64 only."
    echo
    echo "Fixtures: \`bench/fixtures/select_throughput.{test,sql}\` and"
    echo "\`bench/fixtures/select_throughput_pure.{test,sql}\`."
} > "$REPORT"

cat "$REPORT"
echo
echo "report written to: $REPORT" >&2
