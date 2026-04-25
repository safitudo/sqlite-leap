#!/usr/bin/env bash
# Lane 6 — Memory footprint, 5-target.
#
# Reports peak resident set size (`maximum resident set size` from
# /usr/bin/time -lp) for a fixed workload: open + create + 1000 INSERTs
# + 1 SELECT. The runner exits immediately after; the recorded RSS is
# the high-water mark over the lifetime of the process.
#
# This is NOT "RSS at idle holding the db open" — none of the per-target
# slt_runners has a stay-open mode. Adding one would require touching
# parts/, which is out of scope per CLAUDE.md. Peak RSS over a fixed
# scenario is honest and comparable across targets.
#
# Usage: bench/memory_footprint_5target.sh [N_samples]   (default 5)
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib_5target.sh"

REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
N="${1:-5}"
FIXTURE="$REPO_ROOT/bench/fixtures/memory_footprint.test"
SQLFILE="$REPO_ROOT/bench/fixtures/memory_footprint.sql"
OUT_DIR="$REPO_ROOT/bench/results/memory_footprint_5target"
mkdir -p "$OUT_DIR"

ensure_go_slt

# Median of RSS samples — extract the second column from time_run output.
median_rss() {
    local n="$1"; shift
    local fn="$1"; shift
    local rsses=() i out
    for ((i=0; i<n; i++)); do
        out="$("$fn" "$@")"
        rsses+=("${out##*	}")
    done
    python3 - "${rsses[@]}" <<'PY'
import sys, statistics
xs = [int(x) for x in sys.argv[1:] if x not in ("NA","")]
print(int(statistics.median(xs)) if xs else "NA")
PY
}

fmt_kb() {
    if [[ "$1" == "NA" ]]; then echo "NA"
    else python3 -c "import sys;print(f'{int(sys.argv[1])/1024:.1f}')" "$1"; fi
}

echo ">>> Lane 6 memory footprint, N=$N samples per target" >&2

ML_RSS="$(median_rss "$N" run_mainline "$SQLFILE")"

declare -a NAMES=(c rust zig go python)
declare -a RSS=()
for t in "${NAMES[@]}"; do
    echo ">>> sampling $t..." >&2
    RSS+=("$(median_rss "$N" run_target "$t" "$FIXTURE")")
done

REPORT="$OUT_DIR/REPORT.md"
{
    echo "# Lane 6 — 5-target memory footprint"
    echo
    echo "Generated $(date -u +'%Y-%m-%dT%H:%M:%SZ') on $(uname -sm)."
    echo
    echo "Peak resident set size (\`maximum resident set size\` from"
    echo "\`/usr/bin/time -lp\`) over the lifetime of a process running a"
    echo "fixed workload: \`CREATE TABLE\` + 1000 \`INSERT\`s + 1 \`SELECT\`."
    echo
    echo "Median of $N samples per target."
    echo
    echo "| target | peak RSS (bytes) | KB | vs mainline | notes |"
    echo "|---|---:|---:|---:|---|"
    for i in "${!NAMES[@]}"; do
        t="${NAMES[$i]}"
        rss="${RSS[$i]}"
        ratio="$(fmt_ratio "$ML_RSS" "$rss")"
        note="slt_runner($t) on memory_footprint.test"
        echo "| $t | $rss | $(fmt_kb "$rss") | $ratio | $note |"
    done
    echo "| sqlite3 (mainline) | $ML_RSS | $(fmt_kb "$ML_RSS") | 1.00x | system \`$(/usr/bin/sqlite3 -version 2>/dev/null | awk '{print $1}')\` |"
    echo
    echo "Ratio convention: mainline-RSS / leap-RSS. >1.0x means leap is"
    echo "**lighter** (uses less memory)."
    echo
    echo "## Caveats"
    echo "- Peak RSS over a short-lived process — NOT \"idle RSS holding the"
    echo "  db open\". Adding a stay-open mode would require modifying parts/,"
    echo "  which is out of scope here."
    echo "- The Python row includes the CPython runtime; the leap engine code"
    echo "  contributes a small fraction of that total."
    echo "- macOS arm64 \`maximum resident set size\` is in **bytes**; on Linux"
    echo "  the same field is in KB. This script is macOS-only."
    echo
    echo "Fixtures: \`bench/fixtures/memory_footprint.{test,sql}\`."
} > "$REPORT"

cat "$REPORT"
echo
echo "report written to: $REPORT" >&2
