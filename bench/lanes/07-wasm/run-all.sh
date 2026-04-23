#!/usr/bin/env bash
# Run all WASM lane × target combinations and emit a single CSV block.
#
# Writes to stdout the canonical 5-column format (header included on first
# call to match the existing bench/results/*.csv files). Intended to be
# redirected to `bench/results/YYYY-MM-DD-wasm.csv`.
#
# Usage:
#   ./run-all.sh > bench/results/2026-04-21-wasm.csv

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

TARGETS=(sqlite-leap-wasm sql.js sqlite-wasm)
LANES=(cold-start parse-speed select-in-memory)

echo "lane,target,value,units,timestamp"
for lane in "${LANES[@]}"; do
    for target in "${TARGETS[@]}"; do
        # parse and select lanes are slow for leap; let the caller know
        # which combo is running via stderr.
        echo "[run-all] lane=$lane target=$target" >&2
        # Don't let one target's failure abort the whole matrix — we still
        # want rows for the rest. The wrapper emits a NA row on failure.
        "$SCRIPT_DIR/run.sh" --target "$target" --lane "$lane" || true
    done
done
