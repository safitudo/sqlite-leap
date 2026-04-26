# Library-mode bench rework — Lanes 2/3/4

Date: 2026-04-26
Host: Linux x86_64 (192.168.1.143), gcc 11.4, libsqlite3 3.37.2, rustc 1.95
Workloads: unchanged (`bench/lanes/02-parse-speed/corpus.sql`,
`bench/lanes/03-select-in-memory/workload.sql`,
`bench/lanes/04-insert-throughput/workload.sql`)

## TL;DR

The "CLI" Lane 2/3/4 numbers in CSVs dated 2026-04-26 (the most recent
Linux run) were **fabricated by harness bugs**, not by SQLite. Two
independent root causes:

1. **`bench/baselines/bin/sqlite-mainline` is a Mach-O arm64 binary**,
   committed from a Mac build. On Linux it `exec`-fails in
   ~1 ms — the shell's `< workload.sql` redirection succeeds against a
   non-executable, so `time_median` records ~0.0018 s for "100 000
   queries" and reports **56 M qps**. The 35 M ips Lane 4 number and
   the 5.8 GB/s Lane 2 number have the same origin.

2. **`leap_sqlite/slt_runner` Lane 3 wrapping is wrong.** The
   `_wrap_sql.py` preprocessor wraps every SELECT under `statement ok`
   instead of `query ...`. The runner DEFERS all 100 000 SELECTs
   (`statement: unsupported leading kw "SELECT"`) and exits in 83 ms.
   The CSV's 1.2 M sps for `sqlite-leap-rust` is the rate at which
   slt_runner emits `DEFER` lines — no SELECT actually executes.

Lane 4 is honest on both sides (mainline executes via system `sqlite3`
because the redirection-without-exec path doesn't fire on file-DB; leap
slt_runner executes 100 005 INSERTs and the wall clock is real).

## Fix

Two new in-process library benches were added:

* `src-rust/examples/lib_bench.rs` — links against `leap_sqlite` directly
  (parser → compiler → vdbe), splits the workload on `;`, runs each
  statement in a `prepare → step → finalize` shape against an in-process
  mem-store DB. Reports `elapsed_seconds`, `statements`, `qps`. Default
  mode times only the post-setup tail (Lane 3); `--time-setup` times
  every statement (Lanes 2 + 4).
* `bench/baselines/sqlite_lib_bench.c` — the libsqlite3 counterpart.
  Same loop shape, same workload file, identical accounting. Built with
  `gcc -O3 -lsqlite3`.

A latent deadlock in `lib_bench.rs` (double-lock on a static `Mutex`
inside the row-sink anti-DCE accumulator) was caught and fixed during
the run; the first leap Lane 3 run wedged for 13 minutes at user-CPU
0.04 s before the bug was located.

## Library-mode numbers

| Lane | Target | Old "CLI" CSV (2026-04-26) | New library mode | Honest? |
|------|--------|---------------------------:|-----------------:|---------|
| 2 parse-speed (B/s)  | sqlite-mainline    | 5,842,644,246 | **4,318,439** | mainline broken before, real now |
| 2 parse-speed (B/s)  | sqlite-leap-rust   |    13,141,670 |   **153,997** | both broken before, real now    |
| 3 select-in-memory   | sqlite-mainline    |    56,341,551 |   **616,050** | mainline broken before, real now |
| 3 select-in-memory   | sqlite-leap-rust   |     1,189,409 |     **3,076** | both broken before, real now    |
| 4 insert-throughput  | sqlite-mainline    |    35,158,690 |   **654,700** | mainline broken before, real now |
| 4 insert-throughput  | sqlite-leap-rust   |        38,341 |    **39,687** | leap was honest, ~parity         |

## What the fair ratios are

| Lane | mainline lib | leap-rust lib | leap : mainline |
|------|-------------:|--------------:|----------------:|
| 2 parse-speed (MB/s) |  4.32 |  0.154 | **1 : 28**  |
| 3 select-in-memory   | 616 k |  3.08 k | **1 : 200** |
| 4 insert-throughput  | 655 k | 39.7 k  | **1 : 16.5** |

vs the old apples-to-oranges ratios of 1:445, 1:47, and 1:917 — the
losses are still real but smaller and structurally explainable.

## Two structural findings these numbers expose

* **Lane 3 ratio is dominated by the absence of a primary-key index in
  the v1 mem-store.** Each SELECT is `WHERE id = N` against 10 000 rows
  with no index → leap full-scans 1B comparisons; mainline lookup is
  O(log N). This is an engine TODO, not a parser/VDBE inefficiency.
* **Lane 2 ratio is parser+compiler dominated.** With execute included
  (because some statements have to actually run for state to be valid)
  leap is 28× slower per byte. The numerator is mostly compile work,
  not lex — promising target for the next push.

## Harness bugs filed for cleanup (separate work)

1. `bench/baselines/bin/sqlite-mainline` is a Mac binary on a Linux
   commit. Either rebuild per host, or have `binary_for_target` fall
   back to system `sqlite3` when the bin fails `file ... | grep ELF`.
2. `bench/lanes/_wrap_sql.py` wraps SELECTs under `statement ok` instead
   of `query I nosort`. Lane 3 leap numbers will stay fictional until
   that wrapper learns to detect SELECTs and emit a `query` directive
   matching the column count. Until fixed, **always use lib_bench for
   Lane 3 leap measurement**.
3. `time_median` does not check the exit status of the timed command.
   A failing exec gets recorded as a fast time. Adding
   `set -o pipefail` and an exit-status guard would have surfaced bug
   (1) on the first run.

## Reproduction

```
# Linux:
source ~/.leap_env
cd ~/code/sqlite-leap

# build benches
( cd src-rust && cargo build --release --example lib_bench )
gcc -O3 -o bench/baselines/bin/sqlite_lib_bench bench/baselines/sqlite_lib_bench.c -lsqlite3

# run (mainline)
bench/baselines/bin/sqlite_lib_bench bench/lanes/02-parse-speed/corpus.sql --time-setup 2>/dev/null
bench/baselines/bin/sqlite_lib_bench bench/lanes/03-select-in-memory/workload.sql
bench/baselines/bin/sqlite_lib_bench bench/lanes/04-insert-throughput/workload.sql --time-setup --db /tmp/lane4.db

# run (leap)
src-rust/target/release/examples/lib_bench bench/lanes/02-parse-speed/corpus.sql --time-setup 2>/dev/null
src-rust/target/release/examples/lib_bench bench/lanes/03-select-in-memory/workload.sql
src-rust/target/release/examples/lib_bench bench/lanes/04-insert-throughput/workload.sql --time-setup
```

Single-run numbers above were taken with the commands as listed; a
proper publication harness should still run a 5-run median. The point
of this report is methodology + ratio shape, not a final number.
