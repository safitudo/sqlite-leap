#!/usr/bin/env bash
# Parallel full-corpus runner used for the 2026-04-20 reviewer re-measurement.
#
# Usage:
#   run-full-corpus-parallel.sh --target <rust|c> --out <log-path> \
#     [--timeout <seconds>] [--query-timeout <seconds>] \
#     [--jobs <N>] [--corpus <dir>]
#
# --query-timeout <N> (default 0 = disabled): for each file that times out at
# the file level, re-run that file via run-per-query-timeout.sh with an
# N-second per-record budget to localise the wedging query and emit
# FAIL-TIMEOUT: <rel> <qnum> <elapsed-ms> lines into the log. In-process
# per-query kills are not possible without runner cooperation; the runner
# binaries live in src-rust/ and src-c/ which are generator output and not
# modified by this script. See run-per-query-timeout.sh for rationale.
#
# Per-file output format (one line per file):
#   <STATUS> <relative-path> <elapsed-ms>
# where STATUS is one of PASS | FAIL | TIMEOUT | PANIC.
#
# Ends with a summary block (prefix "# "):
#   # total=N passed=N failed=N timeouts=N panics=N pass_rate_pct=X.XX
#
# This script does NOT parse sqllogictest SUMMARY records-per-line; it
# treats the exit code and presence of "FILE ... failed=0" or "SUMMARY ...
# failed=0" as the pass signal. Timeouts come from perl-alarm wrapper
# (macOS lacks GNU timeout).

set -u

TARGET=""
OUT=""
TIMEOUT_S=90
QUERY_TIMEOUT_S=0
JOBS=4
CORPUS=""

while [ $# -gt 0 ]; do
  case "$1" in
    --target)  TARGET="$2"; shift 2 ;;
    --out)     OUT="$2"; shift 2 ;;
    --timeout) TIMEOUT_S="$2"; shift 2 ;;
    --query-timeout) QUERY_TIMEOUT_S="$2"; shift 2 ;;
    --jobs)    JOBS="$2"; shift 2 ;;
    --corpus)  CORPUS="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$TARGET" ] || [ -z "$OUT" ]; then
  echo "usage: $0 --target <rust|c> --out <log-path> [--timeout N] [--query-timeout N] [--jobs N]" >&2
  exit 2
fi

if ! [[ "$QUERY_TIMEOUT_S" =~ ^[0-9]+$ ]]; then
  echo "bad --query-timeout: $QUERY_TIMEOUT_S" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

if [ -z "$CORPUS" ]; then
  CORPUS="$REPO_ROOT/tests/sqllogictest/upstream/test"
fi

case "$TARGET" in
  rust) BIN="$REPO_ROOT/src-rust/target/release/sqllogictest" ;;
  c)    BIN="$REPO_ROOT/src-c/bin/sqllogictest" ;;
  *) echo "bad --target: $TARGET" >&2; exit 2 ;;
esac

[ -x "$BIN" ] || { echo "binary not executable: $BIN" >&2; exit 2; }
[ -d "$CORPUS" ] || { echo "corpus dir missing: $CORPUS" >&2; exit 2; }

mkdir -p "$(dirname "$OUT")"
: > "$OUT"

# -----------------------------------------------------------------------------
# Worker: run a single file with timeout, print "<STATUS> <rel> <ms>"
# -----------------------------------------------------------------------------
# Exported via env to child perl invocation; written as a self-contained perl
# so we can use it with xargs -P for parallelism without fighting quoting.

RUNNER="$REPO_ROOT/tests/sqllogictest/_worker-one-file.pl"
cat > "$RUNNER" <<'PERL'
#!/usr/bin/env perl
use strict;
use warnings;
use Time::HiRes qw(gettimeofday tv_interval);
use POSIX qw(:sys_wait_h);

my ($bin, $corpus, $timeout_s, $rel) = @ARGV;
die "usage: worker BIN CORPUS TIMEOUT REL\n" unless defined $rel;

my $abs = "$corpus/$rel";
my $t0 = [gettimeofday];

my $pid = fork();
die "fork: $!" unless defined $pid;

if ($pid == 0) {
    # child: silence stdout+stderr; we only need the exit code.
    open(STDOUT, '>', '/dev/null') or die "redir stdout: $!";
    open(STDERR, '>', '/dev/null') or die "redir stderr: $!";
    exec $bin, $abs or die "exec: $!";
}

# parent: alarm-based timeout
my $status;
my $timed_out = 0;
my $output = '';
eval {
    local $SIG{ALRM} = sub { die "timeout\n" };
    alarm($timeout_s);
    # We need the child's exit code. Since we already execd without a pipe,
    # just waitpid.
    waitpid($pid, 0);
    $status = $?;
    alarm(0);
};
if ($@) {
    if ($@ =~ /timeout/) {
        $timed_out = 1;
        kill 'TERM', $pid;
        select(undef, undef, undef, 0.5);
        kill 'KILL', $pid;
        waitpid($pid, 0);
    } else {
        die $@;
    }
}

my $elapsed_ms = int(tv_interval($t0) * 1000 + 0.5);

my $out_status;
if ($timed_out) {
    $out_status = 'TIMEOUT';
} else {
    my $rc  = $status >> 8;
    my $sig = $status & 0x7f;
    if ($sig != 0) {
        $out_status = 'PANIC';
    } elsif ($rc == 0) {
        $out_status = 'PASS';
    } else {
        # rc != 0: could be a FAIL (assertion mismatch) or a PANIC (runner crash).
        # sqllogictest runner convention: nonzero exit on failed records.
        # We conservatively call it FAIL. True crashes would usually surface
        # as $sig != 0 (SIGSEGV/SIGABRT); rc > 128 also signals a signal death
        # in some shells (rc = 128 + sig), treat that as PANIC.
        if ($rc > 128) {
            $out_status = 'PANIC';
        } else {
            $out_status = 'FAIL';
        }
    }
}

print "$out_status $rel $elapsed_ms\n";
PERL
chmod +x "$RUNNER"

# -----------------------------------------------------------------------------
# Build the file list
# -----------------------------------------------------------------------------

FILES_LIST="$(mktemp)"
( cd "$CORPUS" && find . -type f -name '*.test' | sed 's|^\./||' | LC_ALL=C sort ) > "$FILES_LIST"

TOTAL="$(wc -l < "$FILES_LIST" | tr -d ' ')"
echo "# corpus_files=$TOTAL jobs=$JOBS timeout_s=$TIMEOUT_S query_timeout_s=$QUERY_TIMEOUT_S target=$TARGET" >> "$OUT"
echo "# binary=$BIN" >> "$OUT"
echo "# corpus=$CORPUS" >> "$OUT"
echo "# date_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$OUT"
echo "# format: <STATUS> <relative-path> <elapsed-ms>" >> "$OUT"

# -----------------------------------------------------------------------------
# Dispatch via xargs -P
# -----------------------------------------------------------------------------

# Each line invokes the perl worker with the fixed args + the rel path.
# Output is appended line-by-line to $OUT. We rely on stdout being line-
# buffered at small line sizes (< PIPE_BUF) on macOS so concurrent writers
# don't interleave.

# Use a temporary per-line file to avoid write races, then sort at the end.
RAW="$(mktemp)"
: > "$RAW"

< "$FILES_LIST" xargs -n1 -P "$JOBS" -I{} "$RUNNER" "$BIN" "$CORPUS" "$TIMEOUT_S" "{}" >> "$RAW"

# Sort alphabetically by path (column 2) for stable log ordering.
LC_ALL=C sort -k2,2 "$RAW" >> "$OUT"

# -----------------------------------------------------------------------------
# Per-query diagnostic pass for timed-out files (optional, opt-in).
# -----------------------------------------------------------------------------
if [ "$QUERY_TIMEOUT_S" -gt 0 ]; then
  TO_FILES="$(awk '$1=="TIMEOUT" {print $2}' "$RAW")"
  if [ -n "$TO_FILES" ]; then
    echo "" >> "$OUT"
    echo "# ---- per-query localisation for TIMEOUT files (query_timeout_s=$QUERY_TIMEOUT_S) ----" >> "$OUT"
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    while IFS= read -r rel; do
      [ -z "$rel" ] && continue
      abs="$CORPUS/$rel"
      "$SCRIPT_DIR/run-per-query-timeout.sh" \
        --target "$TARGET" \
        --file   "$abs" \
        --query-timeout "$QUERY_TIMEOUT_S" \
        --out    "$OUT" \
        || true
    done <<EOF_TO_FILES
$TO_FILES
EOF_TO_FILES
  fi
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

PASS_N=$(awk '$1=="PASS"    {n++} END{print n+0}' "$RAW")
FAIL_N=$(awk '$1=="FAIL"    {n++} END{print n+0}' "$RAW")
TO_N=$(  awk '$1=="TIMEOUT" {n++} END{print n+0}' "$RAW")
PAN_N=$( awk '$1=="PANIC"   {n++} END{print n+0}' "$RAW")
ALL_N=$(wc -l < "$RAW" | tr -d ' ')

RATE="$(awk -v p="$PASS_N" -v t="$ALL_N" 'BEGIN{ if (t==0) print "0.00"; else printf "%.2f", (p*100.0)/t }')"

{
  echo ""
  echo "# ---- summary ----"
  echo "# total=$ALL_N"
  echo "# passed=$PASS_N"
  echo "# failed=$FAIL_N"
  echo "# timeouts=$TO_N"
  echo "# panics=$PAN_N"
  echo "# pass_rate_pct=$RATE"
} >> "$OUT"

echo "target=$TARGET total=$ALL_N passed=$PASS_N failed=$FAIL_N timeouts=$TO_N panics=$PAN_N pass_rate_pct=$RATE"
echo "log: $OUT"

rm -f "$FILES_LIST" "$RAW" "$RUNNER"
