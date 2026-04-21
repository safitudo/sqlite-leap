#!/usr/bin/env bash
# Lane 5 — Binary size.
#
# Measurement method (deterministic):
#   * `stat` the target's stripped release binary on disk. The build step is
#     NOT in this harness's responsibility — the build pipeline must produce
#     an already-stripped binary (strip(1) applied) for a fair number.
#   * Report raw bytes. Additional metadata (sections, dynamic deps) belongs
#     in publication narrative, not in the CSV.
#
# This lane has no timing, no corpus, no runs — just a stat call. It's
# included so `run-all.sh` can emit a single uniform CSV row per lane.
#
# Output: binary-size,<target>,<bytes>,bytes,<iso8601>

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/../_lib.sh"

LANE_NAME="binary-size"
parse_target_flag "$@"

bin="$(binary_for_target "$TARGET" || true)"
[[ -z "$bin" ]] && emit_missing "$LANE_NAME" "$TARGET" && exit 1

# Portable byte-size. BSD stat (macOS) uses -f "%z"; GNU stat (Linux) uses -c "%s".
if stat -f "%z" "$bin" >/dev/null 2>&1; then
    bytes="$(stat -f "%z" "$bin")"
else
    bytes="$(stat -c "%s" "$bin")"
fi
emit_csv "$LANE_NAME" "$TARGET" "$bytes" "bytes"
