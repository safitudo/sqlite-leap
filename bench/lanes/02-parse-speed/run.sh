#!/usr/bin/env bash
# Lane 2 — Parse speed.
#
# Measurement method (deterministic, reproducible):
#   * A 10 MiB mixed-statement SQL file (corpus.sql) generated once by
#     generate-corpus.sh from a fixed RNG seed (0xDEADBEEF). Same bytes on
#     every host; every target parses exactly the same input.
#   * Feed the whole file to the target's driver. We intentionally include
#     execution cost in the measured wall clock — isolating "parse only" is
#     not portable across engines and would favor whichever target exposes
#     a parse-and-discard mode. What we report is steady-state SQL throughput
#     in bytes/sec on a parse-heavy workload (most statements are trivial
#     so execution is cheap compared to parse).
#   * Median of 5 runs, 1 warmup, via hyperfine or Python fallback.
#
# Because "tokens" is not directly comparable across lexers, we publish
# bytes/sec (stable, language-neutral). Conversion to tokens/sec is left
# for narrative copy; the CSV value is always bytes/sec.
#
# Output: parse-speed,<target>,<bytes_per_second>,bytes_per_second,<iso8601>

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/../_lib.sh"

LANE_NAME="parse-speed"
parse_target_flag "$@"

CORPUS="$SCRIPT_DIR/corpus.sql"
if [[ ! -f "$CORPUS" ]]; then
    "$SCRIPT_DIR/generate-corpus.sh" >&2
fi
bytes=$(wc -c < "$CORPUS" | tr -d ' ')

bin="$(binary_for_target "$TARGET" || true)"
[[ -z "$bin" ]] && emit_missing "$LANE_NAME" "$TARGET" && exit 1

case "$TARGET" in
    sqlite-mainline|turso)
        cmd=(bash -c "$bin :memory: < $CORPUS")
        ;;
    sqlite-leap-c|sqlite-leap-rust|sqlite-leap-zig|sqlite-leap-go|sqlite-leap-python)
        # The sqllogictest format requires one directive per SQL
        # statement; wrapping the whole corpus in a single `statement ok`
        # header (as we did before 2026-04-20) caused the runner to
        # reject the second statement with PARSE_UNEXPECTED_TOKEN and
        # exit in ~50 ms — the reported "parse speed" was measuring how
        # fast the binary rejects malformed input, not throughput on
        # the corpus. See bench/lanes/_wrap_sql.py for the preprocessor.
        #
        # Cache the wrapped .slt next to the corpus so repeat runs
        # don't re-split 10 MiB of SQL on every invocation.
        wrapped="$SCRIPT_DIR/corpus.slt"
        if [[ ! -f "$wrapped" || "$CORPUS" -nt "$wrapped" ]]; then
            python3 "$BENCH_ROOT/lanes/_wrap_sql.py" "$CORPUS" "$wrapped" >&2
        fi
        cmd=("$bin" "$wrapped")
        ;;
esac

median_seconds="$(time_median 5 1 -- "${cmd[@]}")"
# bytes/sec = total_bytes / seconds
bps="$(python3 -c "print(int(${bytes}/${median_seconds}))")"
emit_csv "$LANE_NAME" "$TARGET" "$bps" "bytes_per_second"
