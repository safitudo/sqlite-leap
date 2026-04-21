#!/usr/bin/env bash
# Run the full upstream sqllogictest corpus against a given target build.
#
# Usage:
#   tests/sqllogictest/run-full-corpus.sh [--target <rust|c>] [--timeout <seconds>] \
#                                         [--query-timeout <seconds>] [--root <dir>]
#
# Default target: rust. Default per-file timeout: 120 seconds.
# Default per-query timeout (diagnostic localisation): 30 seconds.
#
# Per-query timeout note
# ----------------------
# --query-timeout <N> enables a *diagnostic* follow-up pass on any file that
# times out at the file level: the wrapper re-runs just that file via
# run-per-query-timeout.sh with an N-second per-record budget, localising
# the wedging record and emitting FAIL-TIMEOUT: lines with query numbers.
# The default (0) disables the follow-up; use a positive integer (commonly
# 30) to enable. True in-process per-query kills are not possible without
# runner cooperation (the engine source is generator output); see
# run-per-query-timeout.sh for the rationale.
#
# Per-file SUMMARY lines are appended to
#   tests/sqllogictest/results/<YYYY-MM-DD>-<target>.log
# and an aggregate is printed on stdout at the end.
#
# Exit 0 iff (passed_files / executed_files) >= 0.95, else 1. Skipped and
# timed-out files count as NOT-passed in that ratio. `executed_files` =
# `total_files - skipped_files` so a corpus with 0 executed files exits 1.

set -u

# -----------------------------------------------------------------------------
# Argument parsing
# -----------------------------------------------------------------------------

TARGET="rust"
PER_FILE_TIMEOUT=120
PER_QUERY_TIMEOUT=0   # 0 = disabled; positive integer enables the per-query
                      # diagnostic follow-up for file-level timeouts
REPO_ROOT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --target=*)
      TARGET="${1#*=}"
      shift
      ;;
    --timeout)
      PER_FILE_TIMEOUT="${2:-}"
      shift 2
      ;;
    --timeout=*)
      PER_FILE_TIMEOUT="${1#*=}"
      shift
      ;;
    --query-timeout)
      PER_QUERY_TIMEOUT="${2:-}"
      shift 2
      ;;
    --query-timeout=*)
      PER_QUERY_TIMEOUT="${1#*=}"
      shift
      ;;
    --root)
      REPO_ROOT="${2:-}"
      shift 2
      ;;
    --root=*)
      REPO_ROOT="${1#*=}"
      shift
      ;;
    -h|--help)
      sed -n '2,16p' "$0"
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

case "$TARGET" in
  rust|c) ;;
  *)
    echo "invalid --target: $TARGET (expected rust or c)" >&2
    exit 2
    ;;
esac

if ! [[ "$PER_FILE_TIMEOUT" =~ ^[0-9]+$ ]]; then
  echo "invalid --timeout: $PER_FILE_TIMEOUT (expected positive integer seconds)" >&2
  exit 2
fi

if ! [[ "$PER_QUERY_TIMEOUT" =~ ^[0-9]+$ ]]; then
  echo "invalid --query-timeout: $PER_QUERY_TIMEOUT (expected non-negative integer seconds)" >&2
  exit 2
fi

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

if [ -z "$REPO_ROOT" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
fi

CORPUS_DIR="$REPO_ROOT/tests/sqllogictest/upstream/test"
RESULTS_DIR="$REPO_ROOT/tests/sqllogictest/results"

case "$TARGET" in
  rust) BIN="$REPO_ROOT/src-rust/target/release/sqllogictest" ;;
  c)    BIN="$REPO_ROOT/src-c/bin/sqllogictest" ;;
esac

if [ ! -x "$BIN" ]; then
  echo "sqllogictest binary not found or not executable: $BIN" >&2
  echo "build the $TARGET target first" >&2
  exit 2
fi

if [ ! -d "$CORPUS_DIR" ]; then
  echo "upstream corpus not found: $CORPUS_DIR" >&2
  exit 2
fi

mkdir -p "$RESULTS_DIR"

DATE_STAMP="$(date +%Y-%m-%d)"
LOG_FILE="$RESULTS_DIR/${DATE_STAMP}-${TARGET}.log"

: > "$LOG_FILE"

# -----------------------------------------------------------------------------
# Timeout wrapper — prefer GNU `timeout`, then BSD `gtimeout`, else perl alarm.
# -----------------------------------------------------------------------------

TIMEOUT_MODE=""
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_MODE="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_MODE="gtimeout"
elif command -v perl >/dev/null 2>&1; then
  TIMEOUT_MODE="perl"
else
  echo "no timeout utility available (need timeout, gtimeout, or perl)" >&2
  exit 2
fi

run_with_timeout() {
  # $1 = seconds, $2... = command
  local secs="$1"; shift
  case "$TIMEOUT_MODE" in
    timeout)
      timeout --foreground "$secs" "$@"
      ;;
    gtimeout)
      gtimeout --foreground "$secs" "$@"
      ;;
    perl)
      # Exits 124 on timeout, mimicking GNU timeout.
      perl -e '
        my $secs = shift;
        my $pid = fork();
        die "fork: $!" unless defined $pid;
        if ($pid == 0) {
          exec { $ARGV[0] } @ARGV or die "exec: $!";
        }
        local $SIG{ALRM} = sub {
          kill "TERM", $pid;
          sleep 1;
          kill "KILL", $pid;
          waitpid($pid, 0);
          exit 124;
        };
        alarm $secs;
        waitpid($pid, 0);
        alarm 0;
        my $rc = $?;
        exit ($rc >> 8) if ($rc & 0xff) == 0;
        exit 128 + ($rc & 0x7f);
      ' "$secs" "$@"
      ;;
  esac
}

# -----------------------------------------------------------------------------
# Iterate every .test file under the corpus (lexicographic, recursive)
# -----------------------------------------------------------------------------

TOTAL_FILES=0
PASSED_FILES=0
FAILED_FILES=0
SKIPPED_FILES=0
TIMEDOUT_FILES=0

TOTAL_RECORDS_PASS=0
TOTAL_RECORDS_FAIL=0
TOTAL_RECORDS_SKIP=0
TOTAL_RECORDS=0

echo "# sqllogictest full-corpus run" >> "$LOG_FILE"
echo "# date=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG_FILE"
echo "# target=$TARGET" >> "$LOG_FILE"
echo "# binary=$BIN" >> "$LOG_FILE"
echo "# corpus=$CORPUS_DIR" >> "$LOG_FILE"
echo "# per_file_timeout_s=$PER_FILE_TIMEOUT" >> "$LOG_FILE"
echo "# per_query_timeout_s=$PER_QUERY_TIMEOUT  (0 = disabled)" >> "$LOG_FILE"
echo "# format: RESULT <rel-path> passed=N failed=N skipped=N total=N [status]" >> "$LOG_FILE"
echo "# timeouts also emit: FAIL-TIMEOUT: <rel> (file-level|<qnum>) <elapsed-ms>" >> "$LOG_FILE"

# Collect files, lexicographically sorted, NUL-delimited for path safety.
FILE_LIST="$(cd "$CORPUS_DIR" && find . -type f -name '*.test' | LC_ALL=C sort)"

while IFS= read -r rel; do
  [ -z "$rel" ] && continue
  rel="${rel#./}"
  abs="$CORPUS_DIR/$rel"
  TOTAL_FILES=$((TOTAL_FILES + 1))

  # Capture only the SUMMARY line (one per invocation) — ignore per-record PASS/FAIL
  # chatter; that noise is already the sqllogictest binary's job, not ours.
  output="$(run_with_timeout "$PER_FILE_TIMEOUT" "$BIN" "$abs" 2>&1)"
  rc=$?

  if [ $rc -eq 124 ]; then
    TIMEDOUT_FILES=$((TIMEDOUT_FILES + 1))
    echo "RESULT $rel passed=0 failed=0 skipped=0 total=0 TIMEOUT" >> "$LOG_FILE"
    # Back-compat structured marker: one line per timed-out file so tooling
    # that greps for FAIL-TIMEOUT: sees a consistent token even when the
    # per-query diagnostic is disabled.
    echo "FAIL-TIMEOUT: $rel file-level $((PER_FILE_TIMEOUT * 1000))" >> "$LOG_FILE"

    if [ "$PER_QUERY_TIMEOUT" -gt 0 ]; then
      # Re-run just this file with per-record granularity to localise the
      # wedging query. This is slow (O(records) process spawns), so it's
      # only invoked on files that already tripped the file-level timeout.
      SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
      "$SCRIPT_DIR/run-per-query-timeout.sh" \
        --target "$TARGET" \
        --file   "$abs" \
        --query-timeout "$PER_QUERY_TIMEOUT" \
        --out    "$LOG_FILE" \
        || true
    fi
    continue
  fi

  summary="$(printf '%s\n' "$output" | grep '^SUMMARY ' | tail -n 1 || true)"

  if [ -z "$summary" ]; then
    # Binary produced no SUMMARY line — treat as a failure of the runner for this file.
    FAILED_FILES=$((FAILED_FILES + 1))
    echo "RESULT $rel passed=0 failed=0 skipped=0 total=0 NO_SUMMARY" >> "$LOG_FILE"
    continue
  fi

  # Parse "SUMMARY sqllogictest target=<x> passed=N failed=N skipped=N total=N"
  p="$(printf '%s' "$summary" | sed -n 's/.*passed=\([0-9][0-9]*\).*/\1/p')"
  f="$(printf '%s' "$summary" | sed -n 's/.*failed=\([0-9][0-9]*\).*/\1/p')"
  s="$(printf '%s' "$summary" | sed -n 's/.*skipped=\([0-9][0-9]*\).*/\1/p')"
  t="$(printf '%s' "$summary" | sed -n 's/.*total=\([0-9][0-9]*\).*/\1/p')"
  : "${p:=0}"; : "${f:=0}"; : "${s:=0}"; : "${t:=0}"

  TOTAL_RECORDS_PASS=$((TOTAL_RECORDS_PASS + p))
  TOTAL_RECORDS_FAIL=$((TOTAL_RECORDS_FAIL + f))
  TOTAL_RECORDS_SKIP=$((TOTAL_RECORDS_SKIP + s))
  TOTAL_RECORDS=$((TOTAL_RECORDS + t))

  if [ "$t" -eq 0 ]; then
    # Empty/skipped file (no records executed).
    SKIPPED_FILES=$((SKIPPED_FILES + 1))
    echo "RESULT $rel passed=$p failed=$f skipped=$s total=$t SKIP" >> "$LOG_FILE"
  elif [ "$f" -eq 0 ]; then
    PASSED_FILES=$((PASSED_FILES + 1))
    echo "RESULT $rel passed=$p failed=$f skipped=$s total=$t PASS" >> "$LOG_FILE"
  else
    FAILED_FILES=$((FAILED_FILES + 1))
    echo "RESULT $rel passed=$p failed=$f skipped=$s total=$t FAIL" >> "$LOG_FILE"
  fi
done <<EOF
$FILE_LIST
EOF

# -----------------------------------------------------------------------------
# Aggregate
# -----------------------------------------------------------------------------

EXECUTED_FILES=$((TOTAL_FILES - SKIPPED_FILES))
NON_PASS=$((FAILED_FILES + TIMEDOUT_FILES))

if [ "$EXECUTED_FILES" -gt 0 ]; then
  # Percentage with one decimal place, without bc.
  PCT="$(awk -v p="$PASSED_FILES" -v e="$EXECUTED_FILES" 'BEGIN { printf "%.1f", (p*100.0)/e }')"
else
  PCT="0.0"
fi

{
  echo
  echo "# aggregate"
  echo "# total_files=$TOTAL_FILES"
  echo "# passed_files=$PASSED_FILES"
  echo "# failed_files=$FAILED_FILES"
  echo "# skipped_files=$SKIPPED_FILES"
  echo "# timedout_files=$TIMEDOUT_FILES"
  echo "# executed_files=$EXECUTED_FILES"
  echo "# pass_rate_pct=$PCT"
  echo "# total_records=$TOTAL_RECORDS records_passed=$TOTAL_RECORDS_PASS records_failed=$TOTAL_RECORDS_FAIL records_skipped=$TOTAL_RECORDS_SKIP"
} >> "$LOG_FILE"

echo
echo "=== sqllogictest full-corpus aggregate (target=$TARGET) ==="
printf "total files        : %d\n" "$TOTAL_FILES"
printf "passed             : %d\n" "$PASSED_FILES"
printf "failed             : %d\n" "$FAILED_FILES"
printf "skipped (no recs)  : %d\n" "$SKIPPED_FILES"
printf "timed out (>%ss)  : %d\n" "$PER_FILE_TIMEOUT" "$TIMEDOUT_FILES"
printf "executed           : %d\n" "$EXECUTED_FILES"
printf "file pass rate     : %s%% (%d/%d executed)\n" "$PCT" "$PASSED_FILES" "$EXECUTED_FILES"
printf "record pass/fail   : %d / %d (skipped=%d total=%d)\n" \
  "$TOTAL_RECORDS_PASS" "$TOTAL_RECORDS_FAIL" "$TOTAL_RECORDS_SKIP" "$TOTAL_RECORDS"
printf "log                : %s\n" "$LOG_FILE"

# Gate: >= 95% of executed files must pass.
if [ "$EXECUTED_FILES" -eq 0 ]; then
  exit 1
fi

# Compare PCT as an integer: pass iff passed*100 >= 95*executed.
LHS=$((PASSED_FILES * 100))
RHS=$((95 * EXECUTED_FILES))
if [ "$LHS" -ge "$RHS" ]; then
  exit 0
else
  exit 1
fi
