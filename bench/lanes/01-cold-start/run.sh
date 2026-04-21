#!/usr/bin/env bash
# Lane 1 — Cold start.
#
# Measurement method (deterministic, reproducible):
#   * Spawn the target binary with stdin = "SELECT 1;\n" against :memory:.
#   * Wall-clock from process start to process exit (binary must print the
#     result and exit; no REPL). This captures: dlopen + heap init + catalog
#     scan + parser warmup + VDBE warmup + emit 1 row.
#   * Repeat 30 times with 3 warmup runs, report the median in seconds.
#   * Uses hyperfine --warmup 3 --runs 30 when available; falls back to a
#     Python monotonic-clock median loop.
#
# Per CLAUDE.md the public target is <= 40 microseconds. This lane must
# therefore resolve single-digit microseconds cleanly; hyperfine is strongly
# preferred and warned-about-if-missing at publication time.
#
# Target bindings:
#   * sqlite-leap-c/rust: invoke <bin> with `SELECT 1;` piped on stdin.
#   * sqlite-mainline:    echo 'SELECT 1;' | sqlite3 :memory:
#   * turso:              turso :memory: via stdin
#
# Output: cold-start,<target>,<median_seconds>,seconds,<iso8601>

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/../_lib.sh"

LANE_NAME="cold-start"
parse_target_flag "$@"

bin="$(binary_for_target "$TARGET" || true)"
[[ -z "$bin" ]] && emit_missing "$LANE_NAME" "$TARGET" && exit 1

# Build the command line per target. Every target ends up running a
# trivial SELECT against an in-memory DB from a fresh process.
SQL='SELECT 1;'
tmpin="$(mktemp)"
printf '%s\n' "$SQL" > "$tmpin"
trap 'rm -f "$tmpin"' EXIT

case "$TARGET" in
    sqlite-mainline|turso)
        # These speak SQL on stdin; pass :memory: as the DB.
        cmd=(bash -c "$bin :memory: < $tmpin")
        ;;
    turso-core)
        # Library-variant harness; no stdin plumbing needed — cold-start
        # mode runs its own "SELECT 1;" against a fresh :memory: engine.
        cmd=("$bin" --mode=cold-start)
        ;;
    sqlite-leap-c|sqlite-leap-rust)
        # sqllogictest harness reads a test file; feed it a one-line file.
        tmptest="$(mktemp)"
        printf 'statement ok\n%s\n\nquery I\n%s\n----\n1\n' "$SQL" "$SQL" > "$tmptest"
        trap 'rm -f "$tmpin" "$tmptest"' EXIT
        cmd=("$bin" "$tmptest")
        ;;
esac

median="$(time_median 30 3 -- "${cmd[@]}")"
emit_csv "$LANE_NAME" "$TARGET" "$median" "seconds"
