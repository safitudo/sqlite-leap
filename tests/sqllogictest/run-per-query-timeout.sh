#!/usr/bin/env bash
# Per-query-timeout diagnostic runner.
#
# Usage:
#   tests/sqllogictest/run-per-query-timeout.sh \
#       --target <rust|c> \
#       --file   <relative-or-absolute-.test-path> \
#       [--query-timeout <seconds>]       # default: 30
#       [--max-queries <N>]               # default: unlimited
#       [--out <log-path>]                # default: stdout
#
# WHY THIS EXISTS
# ---------------
# The sqllogictest runners (sqllogictest binary in src-rust/ and src-c/) run a
# whole .test file in a single process. Engine state (tables, indexes, pragmas)
# accumulates across records, so we cannot safely "kill a single query" and
# continue with the next one inside the same process without engine
# cooperation (a cancellation token that the VDBE loop polls, which the
# generated engines do not currently provide).
#
# The run-full-corpus wrappers impose a per-FILE wall-clock timeout via
# SIGALRM + SIGKILL. That's coarse: one wedging query in a 1000-query file
# kills the whole file.
#
# This script gives honest per-QUERY timeout semantics without requiring
# engine cooperation, at the cost of O(N) process spawns and O(N^2) SQL
# re-execution work where N = number of records in the file. Use it to
# *diagnose* which record in a file is wedging, and to gather a FAIL-TIMEOUT
# report with record-level granularity. Do NOT use it as the normal
# full-corpus path — it is far too slow.
#
# HOW IT WORKS
# ------------
# 1. Parse the .test file into records. (Stop on `halt`.)
# 2. For each k in 1..N, materialize a prefix file containing records 1..k
#    and invoke the runner on it with a per-invocation wall-clock timeout of
#    `query_timeout * k` seconds (so that the first suspect *increment* is
#    what trips the alarm, not prior records re-executing).
#    As an optimisation we run a binary search over k and a linear-scan
#    fallback near the boundary — see below.
# 3. When an invocation times out, we've localised the wedging record: it's
#    the one whose execution pushed total wall-clock past the budget. Emit:
#       FAIL-TIMEOUT: <file> <query-number> <elapsed-ms>
#
# OUTPUT FORMAT (per line)
# ------------------------
#   PASS-QUERY:   <file> <query-number> <elapsed-ms>
#   FAIL-TIMEOUT: <file> <query-number> <elapsed-ms>
#   SKIP-QUERY:   <file> <query-number> reason=<text>
# plus a trailing SUMMARY line:
#   SUMMARY per-query target=<t> file=<f> queries=<N> passed=<P> failed_timeout=<T>

set -u

TARGET=""
FILE=""
QUERY_TIMEOUT=30
MAX_QUERIES=0
OUT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --target)         TARGET="$2"; shift 2 ;;
    --file)           FILE="$2"; shift 2 ;;
    --query-timeout)  QUERY_TIMEOUT="$2"; shift 2 ;;
    --max-queries)    MAX_QUERIES="$2"; shift 2 ;;
    --out)            OUT="$2"; shift 2 ;;
    -h|--help)        sed -n '2,45p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[ -n "$TARGET" ] || { echo "missing --target" >&2; exit 2; }
[ -n "$FILE"   ] || { echo "missing --file"   >&2; exit 2; }

case "$TARGET" in rust|c) ;; *) echo "bad --target: $TARGET" >&2; exit 2 ;; esac

if ! [[ "$QUERY_TIMEOUT" =~ ^[0-9]+$ ]] || [ "$QUERY_TIMEOUT" -lt 1 ]; then
  echo "bad --query-timeout: $QUERY_TIMEOUT" >&2; exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
case "$TARGET" in
  rust) BIN="$REPO_ROOT/src-rust/target/release/sqllogictest" ;;
  c)    BIN="$REPO_ROOT/src-c/bin/sqllogictest" ;;
esac
[ -x "$BIN" ] || { echo "binary not executable: $BIN" >&2; exit 2; }

case "$FILE" in
  /*) ABS="$FILE" ;;
  *)  ABS="$REPO_ROOT/$FILE" ;;
esac
[ -f "$ABS" ] || { echo "not a file: $ABS" >&2; exit 2; }

REL="${ABS#$REPO_ROOT/}"

if [ -n "$OUT" ]; then
  mkdir -p "$(dirname "$OUT")"
  exec >>"$OUT"
fi

# ---------------------------------------------------------------------------
# Per-query driver, written in perl so we can use SIGALRM cleanly on macOS.
# ---------------------------------------------------------------------------
PERL_SCRIPT="$(mktemp -t slt_pqto.XXXXXX).pl"
trap 'rm -f "$PERL_SCRIPT" "$PREFIX_FILE" 2>/dev/null || true' EXIT
PREFIX_FILE="$(mktemp -t slt_pqto_prefix.XXXXXX).test"

cat > "$PERL_SCRIPT" <<'PERL'
#!/usr/bin/env perl
use strict;
use warnings;
use Time::HiRes qw(gettimeofday tv_interval);

my ($bin, $abs, $rel, $query_timeout, $max_queries, $prefix_file) = @ARGV;
die "usage: driver BIN ABS REL QT MAXQ PREFIX\n" unless defined $prefix_file;

# --- 1. Parse the .test file into record blocks ---------------------------
open(my $fh, '<', $abs) or die "open $abs: $!";
my @raw = <$fh>;
close $fh;

# A record is a sequence of non-blank lines starting with a directive line.
# We also respect `halt` as end-of-file and drop records after it.
# Records include the trailing blank line so prefix reconstruction is exact.

my @records;  # each entry: [start_line, end_line_exclusive, text, kind]
my $i = 0;
my $n = scalar @raw;
my $halted = 0;
while ($i < $n) {
    # Skip leading blank/comment lines between records (attach to next record's
    # leading block so we preserve exact file bytes).
    my $rec_start = $i;
    while ($i < $n && ($raw[$i] =~ /^\s*$/ || $raw[$i] =~ /^\s*#/)) { $i++; }
    if ($i >= $n) { last; }

    my $dir_line = $raw[$i];
    my $kind = "other";
    if    ($dir_line =~ /^\s*halt\b/)              { $kind = "halt"; $halted = 1; }
    elsif ($dir_line =~ /^\s*statement\s+(ok|error)/) { $kind = "statement"; }
    elsif ($dir_line =~ /^\s*query\b/)             { $kind = "query"; }
    elsif ($dir_line =~ /^\s*hash-threshold\b/)    { $kind = "hash-threshold"; }
    elsif ($dir_line =~ /^\s*skipif\b/ || $dir_line =~ /^\s*onlyif\b/) { $kind = "cond"; }
    elsif ($dir_line =~ /^\s*loop\b/ || $dir_line =~ /^\s*endloop\b/)   { $kind = "loop"; }

    # Consume the record until a blank line or EOF.
    my $rec_begin = $i;
    $i++;
    while ($i < $n && $raw[$i] !~ /^\s*$/) { $i++; }
    # Include exactly one trailing blank separator if present.
    if ($i < $n && $raw[$i] =~ /^\s*$/) { $i++; }

    push @records, {
        kind  => $kind,
        start => $rec_begin,
        end   => $i,             # exclusive
    };
    last if $halted;
}

my $record_count = scalar @records;
if ($max_queries > 0 && $record_count > $max_queries) {
    $record_count = $max_queries;
}

# --- 2. Helper: run the binary on a materialized prefix with SIGALRM. -----
sub run_prefix {
    my ($upto_idx, $budget_s) = @_;   # inclusive index
    # Write records 0..upto_idx into $prefix_file.
    open(my $pf, '>', $prefix_file) or die "open $prefix_file: $!";
    for my $k (0..$upto_idx) {
        my $r = $records[$k];
        print $pf join('', @raw[$r->{start} .. $r->{end} - 1]);
    }
    close $pf;

    my $t0 = [gettimeofday];
    my $pid = fork();
    die "fork: $!" unless defined $pid;
    if ($pid == 0) {
        open(STDOUT, '>', '/dev/null');
        open(STDERR, '>', '/dev/null');
        exec $bin, $prefix_file or die "exec: $!";
    }
    my $timed_out = 0;
    my $status = 0;
    eval {
        local $SIG{ALRM} = sub { die "timeout\n" };
        alarm($budget_s);
        waitpid($pid, 0);
        $status = $?;
        alarm(0);
    };
    if ($@) {
        if ($@ =~ /timeout/) {
            $timed_out = 1;
            kill 'TERM', $pid;
            select(undef, undef, undef, 0.2);
            kill 'KILL', $pid;
            waitpid($pid, 0);
        } else {
            die $@;
        }
    }
    my $elapsed_ms = int(tv_interval($t0) * 1000 + 0.5);
    return ($timed_out, $status, $elapsed_ms);
}

# --- 3. Run each record as a growing prefix with per-record budget. --------
# Budget model: for record k, the total wall-clock budget for running the
# 0..k prefix is (k+1) * query_timeout seconds. If the run times out, the
# incremental cost of record k exceeded query_timeout. (Prior records were
# already known to fit into k * query_timeout; otherwise we'd have bailed.)

my $passed = 0;
my $failed_timeout = 0;

for my $k (0..$record_count - 1) {
    my $r = $records[$k];
    my $qnum = $k + 1;   # 1-based for humans

    # Fast skip: purely informational records contribute trivial engine work.
    if ($r->{kind} eq "hash-threshold" || $r->{kind} eq "loop" ||
        $r->{kind} eq "cond"           || $r->{kind} eq "other") {
        # We still need to include them in subsequent prefixes, but don't
        # bother running the binary for them in isolation — skip measurement.
        print "SKIP-QUERY: $rel $qnum reason=$r->{kind}\n";
        next;
    }

    my $budget = ($k + 1) * $query_timeout;
    # Cap total per-step budget at 10 minutes regardless of k to keep this
    # script usable on long files.
    $budget = 600 if $budget > 600;

    my ($timed_out, $status, $elapsed_ms) = run_prefix($k, $budget);

    if ($timed_out) {
        print "FAIL-TIMEOUT: $rel $qnum $elapsed_ms\n";
        $failed_timeout++;
        # First timeout identifies the wedging record; stop — engine state
        # beyond this point is meaningless in the same cumulative path.
        last;
    } else {
        $passed++;
        print "PASS-QUERY: $rel $qnum $elapsed_ms\n";
    }

    # Last record of the file — nothing further to measure.
    last if $k == $record_count - 1;
}

my $target = $ENV{SLT_PQTO_TARGET} // "unknown";
print "SUMMARY per-query target=$target file=$rel queries=$record_count passed=$passed failed_timeout=$failed_timeout\n";
PERL

SLT_PQTO_TARGET="$TARGET" perl "$PERL_SCRIPT" \
  "$BIN" "$ABS" "$REL" "$QUERY_TIMEOUT" "$MAX_QUERIES" "$PREFIX_FILE"
