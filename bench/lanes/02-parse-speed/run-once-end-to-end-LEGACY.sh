#!/usr/bin/env bash
# Lane 2 fast-path: single-run-per-target measurement.
#
# The standard run.sh does median-of-5 + 1 warmup, which on a 10 MiB
# corpus-with-full-execute load takes ~30 min/target for leap. This
# script runs each target exactly once, emits the same CSV shape, and
# labels the value honestly (single-run, not median).
#
# Usage: run-once.sh --target <t>
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/../_lib.sh"

LANE_NAME="parse-speed"
parse_target_flag "$@"

CORPUS="$SCRIPT_DIR/corpus.sql"
bytes=$(wc -c < "$CORPUS" | tr -d ' ')

bin="$(binary_for_target "$TARGET" || true)"
[[ -z "$bin" ]] && emit_missing "$LANE_NAME" "$TARGET" && exit 1

case "$TARGET" in
    sqlite-mainline|turso)
        cmd=(bash -c "$bin :memory: < $CORPUS")
        ;;
    sqlite-leap-c|sqlite-leap-rust)
        wrapped="$SCRIPT_DIR/corpus.slt"
        if [[ ! -f "$wrapped" || "$CORPUS" -nt "$wrapped" ]]; then
            python3 "$BENCH_ROOT/lanes/_wrap_sql.py" "$CORPUS" "$wrapped" >&2
        fi
        cmd=("$bin" "$wrapped")
        ;;
esac

t0=$(python3 -c 'import time; print(time.monotonic())')
"${cmd[@]}" >/dev/null 2>&1 || true
t1=$(python3 -c 'import time; print(time.monotonic())')
elapsed=$(python3 -c "print(${t1}-${t0})")
bps="$(python3 -c "print(int(${bytes}/${elapsed}))")"
emit_csv "$LANE_NAME" "$TARGET" "$bps" "bytes_per_second_single_run"
