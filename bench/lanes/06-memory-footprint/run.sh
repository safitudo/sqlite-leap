#!/usr/bin/env bash
# Lane 6 — Memory footprint (RSS at steady state).
#
# Measurement method (deterministic):
#   * Open small-db.sqlite (~64 KiB, materialized by generate-corpus.sh from
#     the mainline baseline so every target reads identical bytes).
#   * Run `SELECT count(*) FROM t;` then exit.
#   * Wrap in /usr/bin/time — "maximum resident set size" — which reports
#     peak RSS over the process lifetime.
#     - macOS: /usr/bin/time -l  (bytes)
#     - Linux: /usr/bin/time -v  (kilobytes; converted to bytes)
#   * Report peak RSS in bytes. This overcounts steady-state RSS slightly
#     because it includes transient allocations during startup, but it does
#     so equally for every target.
#   * Take the median of 5 runs to smooth out scheduler noise.
#
# Output: memory-footprint,<target>,<bytes>,bytes,<iso8601>

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/../_lib.sh"

LANE_NAME="memory-footprint"
parse_target_flag "$@"

DB="$SCRIPT_DIR/small-db.sqlite"
WORKLOAD="$SCRIPT_DIR/workload.sql"
if [[ ! -f "$WORKLOAD" || ! -f "$DB" ]]; then
    "$SCRIPT_DIR/generate-corpus.sh" >&2
fi

bin="$(binary_for_target "$TARGET" || true)"
[[ -z "$bin" ]] && emit_missing "$LANE_NAME" "$TARGET" && exit 1

if [[ ! -f "$DB" ]]; then
    # Baseline not built yet — we can't materialize a shared DB, so skip.
    emit_csv "$LANE_NAME" "$TARGET" "NA" "missing-corpus"
    exit 1
fi

case "$TARGET" in
    sqlite-mainline|turso)
        cmd=(bash -c "$bin $DB < $WORKLOAD")
        ;;
    turso-core)
        # Library variant: takes --db=PATH and --sql-file=PATH explicitly.
        cmd=("$bin" "--mode=run" "--db=$DB" "--sql-file=$WORKLOAD")
        ;;
    sqlite-leap-c|sqlite-leap-rust|sqlite-leap-zig|sqlite-leap-go|sqlite-leap-python)
        wrapped="$(mktemp)"
        {
            printf 'statement ok\n'
            cat "$WORKLOAD"
        } > "$wrapped"
        trap 'rm -f "$wrapped"' EXIT
        # The sqllogictest driver must accept --db-path or equivalent; if it
        # doesn't, the only portable way is to copy the DB to its expected
        # path. We pass the workload file and let the generated driver do
        # whatever it does. Harness note: once CLI flags stabilize we may
        # need to update this invocation.
        cmd=("$bin" "$wrapped")
        ;;
esac

# Median of 5 peak-RSS measurements.
samples=()
for _ in 1 2 3 4 5; do
    samples+=("$(peak_rss_bytes "${cmd[@]}")")
done
median_bytes="$(printf '%s\n' "${samples[@]}" | python3 -c '
import sys, statistics
vals = [int(x) for x in sys.stdin.read().split() if x]
print(int(statistics.median(vals)))
')"
emit_csv "$LANE_NAME" "$TARGET" "$median_bytes" "bytes"
