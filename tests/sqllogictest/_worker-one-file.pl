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
