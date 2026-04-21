#!/usr/bin/env bash
# Read a results log produced by run-full-corpus-parallel.sh, re-invoke the
# runner on every FAIL file (serial, short timeout), extract the FIRST
# "FAIL ... " message line, and print:  <category> <rel-path>
#
# Categories are heuristic buckets derived from the failure message text:
#   PARSE_*     -- couldn't parse the test file itself
#   QUERY_HASH_MISMATCH
#   QUERY_ROWS_MISMATCH
#   STMT_EXPECTED_ERROR_GOT_OK
#   STMT_EXPECTED_OK_GOT_ERROR
#   QUERY_EXPECTED_ROWS_GOT_ERROR
#   QUERY_EXPECTED_ERROR_GOT_ROWS
#   RUNTIME_<ERROR_KIND>
#   OTHER

set -u

LOG="$1"
BIN="$2"    # absolute path to sqllogictest binary
CORPUS="$3" # absolute path to corpus root
TIMEOUT_S="${4:-30}"

[ -f "$LOG" ] || { echo "log not found: $LOG" >&2; exit 2; }
[ -x "$BIN" ] || { echo "bin not found: $BIN" >&2; exit 2; }

categorize_line() {
  # $1 = raw FAIL line from runner
  local line="$1"
  case "$line" in
    *expected-hash=*got-hash=*)   echo "QUERY_HASH_MISMATCH" ;;
    *expected-rows*got-error=*)
      # Extract the error name after got-error=
      local errkind
      errkind="$(printf '%s' "$line" | sed -n 's/.*got-error=\([A-Z_][A-Z0-9_]*\).*/\1/p')"
      if [ -n "$errkind" ]; then
        echo "RUNTIME_$errkind"
      else
        echo "QUERY_EXPECTED_ROWS_GOT_ERROR"
      fi
      ;;
    *expected-error*got-ok*)     echo "STMT_EXPECTED_ERROR_GOT_OK" ;;
    *expected-ok*got-error=*)
      local errkind
      errkind="$(printf '%s' "$line" | sed -n 's/.*got-error=\([A-Z_][A-Z0-9_]*\).*/\1/p')"
      if [ -n "$errkind" ]; then
        echo "RUNTIME_$errkind"
      else
        echo "STMT_EXPECTED_OK_GOT_ERROR"
      fi
      ;;
    *expected-error*got-rows*)   echo "QUERY_EXPECTED_ERROR_GOT_ROWS" ;;
    *expected-rows*got-rows*)    echo "QUERY_ROWS_MISMATCH" ;;
    *row=*expected=*got=*)       echo "QUERY_VALUE_MISMATCH" ;;
    *expected-values=*got-values=*) echo "QUERY_ROWCOUNT_MISMATCH" ;;
    *PARSE*)                     echo "PARSE_ERROR" ;;
    *)                           echo "OTHER" ;;
  esac
}

while IFS= read -r logline; do
  case "$logline" in
    FAIL\ *)
      rel="$(printf '%s' "$logline" | awk '{print $2}')"
      abs="$CORPUS/$rel"
      # Capture ALL output, find the first FAIL line emitted by the runner.
      out="$(perl -e '
        use strict; use warnings;
        my ($secs, @cmd) = @ARGV;
        my $pid = fork();
        die unless defined $pid;
        if ($pid == 0) {
          exec @cmd or die;
        }
        eval {
          local $SIG{ALRM} = sub { die "to\n" };
          alarm($secs);
          waitpid($pid, 0);
          alarm 0;
        };
        if ($@) { kill "KILL", $pid; waitpid($pid,0); exit 124; }
        exit ($? >> 8);
      ' "$TIMEOUT_S" "$BIN" "$abs" 2>&1 | grep -m1 '^FAIL ' || true)"
      if [ -z "$out" ]; then
        echo "OTHER $rel"
      else
        cat="$(categorize_line "$out")"
        echo "$cat $rel"
      fi
      ;;
  esac
done < "$LOG"
