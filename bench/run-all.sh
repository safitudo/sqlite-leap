#!/usr/bin/env bash
# Run every lane against every target whose binary exists. Append one CSV
# row per (lane, target) to bench/results/<date>-<hostname>.csv. Missing
# binaries are tolerated — they emit a single "NA,missing-binary" row and
# the runner moves on.

set -uo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p results
DATE="$(date -u +"%Y-%m-%d")"
HOST="$(hostname -s)"
OUT="results/${DATE}-${HOST}.csv"

# Write header once per file (idempotent — only on first creation).
if [[ ! -s "$OUT" ]]; then
    echo "lane,target,value,units,timestamp" > "$OUT"
fi

TARGETS=(sqlite-leap-c sqlite-leap-rust sqlite-leap-zig sqlite-leap-go sqlite-leap-python sqlite-mainline turso turso-core)
LANES=(
    lanes/01-cold-start/run.sh
    lanes/02-parse-speed/run.sh
    lanes/03-select-in-memory/run.sh
    lanes/04-insert-throughput/run.sh
    lanes/05-binary-size/run.sh
    lanes/06-memory-footprint/run.sh
)

for lane in "${LANES[@]}"; do
    [[ -x "$lane" ]] || chmod +x "$lane"
    for target in "${TARGETS[@]}"; do
        echo "[run-all] $lane --target $target" >&2
        line="$("$lane" --target "$target" 2>/dev/null || true)"
        if [[ -n "$line" ]]; then
            echo "$line" >> "$OUT"
            echo "  $line" >&2
        else
            echo "  (no output from $lane for $target)" >&2
        fi
    done
done

echo "[run-all] wrote $OUT" >&2
echo "$OUT"
