#!/usr/bin/env bash
# Lane 7 — WASM bench harness shell wrapper.
#
# Thin wrapper around `node runner.mjs` that:
#   * Parses the same `--target <name>` flag as native lanes via _lib.sh.
#   * Adds `--lane <cold-start|parse-speed|select-in-memory>` to pick the
#     WASM sub-lane.
#   * Emits one CSV row to stdout in the canonical
#     `lane,target,value,units,timestamp` format.
#   * Handles the "deps not installed" case with a helpful message.
#
# The heavy lifting (driver set-up, fresh-instance cold-start, per-statement
# replay, median aggregation) lives in runner.mjs. See the README in this
# directory for methodology.
#
# Targets: sqlite-leap-wasm, sql.js, sqlite-wasm
# Sub-lanes: cold-start, parse-speed, select-in-memory
#
# Usage:
#   ./run.sh --target sqlite-leap-wasm --lane cold-start
#   ./run.sh --target sql.js           --lane parse-speed
#   ./run.sh --target sqlite-wasm      --lane select-in-memory

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/../_lib.sh"

# Parse our own args — we accept both --target and --lane, so the canned
# parse_target_flag isn't quite right. Keep the two-flag style explicit.
TARGET=""
SUBLANE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)    TARGET="$2"; shift 2 ;;
        --target=*)  TARGET="${1#--target=}"; shift ;;
        --lane)      SUBLANE="$2"; shift 2 ;;
        --lane=*)    SUBLANE="${1#--lane=}"; shift ;;
        -h|--help)
            cat <<USAGE >&2
Usage: $0 --target <sqlite-leap-wasm|sql.js|sqlite-wasm>
          --lane   <cold-start|parse-speed|select-in-memory>
USAGE
            exit 2
            ;;
        *)  echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done
if [[ -z "$TARGET" || -z "$SUBLANE" ]]; then
    echo "--target and --lane are required" >&2
    exit 2
fi

case "$SUBLANE" in
    cold-start|parse-speed|select-in-memory) ;;
    *) echo "unknown --lane $SUBLANE" >&2; exit 2 ;;
esac

case "$TARGET" in
    sqlite-leap-wasm|sql.js|sqlite-wasm) ;;
    *) echo "unknown --target $TARGET" >&2; exit 2 ;;
esac

# Verify node and runner + deps.
if ! command -v node >/dev/null 2>&1; then
    emit_csv "wasm-$SUBLANE" "$TARGET" "NA" "no-node"
    exit 1
fi

if [[ "$TARGET" != "sqlite-leap-wasm" ]]; then
    if [[ ! -d "$SCRIPT_DIR/node_modules/sql.js" && ! -d "$SCRIPT_DIR/node_modules/@sqlite.org/sqlite-wasm" ]]; then
        # Not installed; emit a helpful NA and exit non-zero so run-all
        # surfaces the problem.
        echo "node_modules missing in $SCRIPT_DIR; run: (cd $SCRIPT_DIR && npm install)" >&2
        emit_csv "wasm-$SUBLANE" "$TARGET" "NA" "deps-missing"
        exit 1
    fi
fi

if [[ "$TARGET" == "sqlite-leap-wasm" && ! -f "$REPO_ROOT/src-wasm/sqlite_leap.wasm" ]]; then
    emit_csv "wasm-$SUBLANE" "$TARGET" "NA" "missing-wasm"
    exit 1
fi

# Delegate to the runner, pass-through --emit-csv so the CSV line ends up on
# our stdout verbatim.
cd "$SCRIPT_DIR"
exec node runner.mjs --lane "$SUBLANE" --target "$TARGET" --emit-csv
