# Benchmark results

This directory holds CSVs produced by `bench/run-all.sh`. One file per run,
named `<UTC-date>-<hostname>.csv` (or `<date>-<host>-validated.csv` when a
run was explicitly vetted — see "Validation history" below).

## How to read a CSV

Every row is `lane,target,value,units,timestamp`. One row per `(lane, target)`
pair. Missing targets emit `value=NA,units=missing-binary`.

```
lane,target,value,units,timestamp
cold-start,sqlite-leap-rust,0.003515,seconds,2026-04-20T22:45:35Z
parse-speed,sqlite-mainline,6421897,bytes_per_second,2026-04-20T22:45:49Z
```

The full measurement method per lane is documented in the comment block at
the top of each `bench/lanes/NN-<lane>/run.sh`. A condensed summary is below.

## Lane summary

| # | Lane name           | Unit                  | Workload                                                                                                                       |
|---|---------------------|-----------------------|--------------------------------------------------------------------------------------------------------------------------------|
| 1 | cold-start          | `seconds`             | Process invocation running `SELECT 1;` against `:memory:`. Median of 30 runs, 3 warmup. Captures startup + parser + VDBE warm. |
| 2 | parse-speed         | `bytes_per_second`    | Stream a deterministic 10 MiB mixed-statement SQL file. Wall clock through the whole corpus. Median of 5 runs, 1 warmup.        |
| 3 | select-in-memory    | `selects_per_second`  | Populate a 10 000-row table in-memory then issue 100 000 point-SELECTs by primary key. Median of 5 runs, 1 warmup.             |
| 4 | insert-throughput   | `inserts_per_second`  | 100 000 INSERTs in one transaction against a fresh file DB. Median of 5 runs, 1 warmup.                                        |
| 5 | binary-size         | `bytes`               | `stat` of the stripped release binary. No variance.                                                                             |
| 6 | memory-footprint    | `bytes`               | Peak RSS via `/usr/bin/time -l` (macOS) / `-v` (Linux) on a small open+SELECT. Single sample — noisy.                           |

## Targets

`sqlite-leap-c`, `sqlite-leap-rust`, `sqlite-mainline`, `turso`. The two leap
targets are exercised through their `sqllogictest` runner binary, because
that is the same interface the correctness suite uses — one binary, two
modes (bench mode is just "run a file, ignore PASS/FAIL, measure wall
time"). Mainline and Turso are exercised through their stock CLI (`sqlite3`
/ `turso`), reading raw SQL from stdin.

## Known asymmetries (what the numbers do NOT say)

Do not read the CSV as a like-for-like engine comparison without accounting
for these:

1. **Lane 2 (parse-speed) uses a self-inconsistent random corpus.** The
   generator emits statements referencing tables that are created only
   sometimes, so most statements fail at execution. Engines are compared on
   "how fast do you parse + attempt + report-error per statement." Mainline
   has verbose stderr for every error (redirected to `/dev/null` during
   timing, but the work is still done). The leap runner reports PASS/FAIL
   through its own fast-error path. A self-consistent corpus would tighten
   this lane; until that's addressed, treat lane 2 ratios with a wide grain
   of salt.

2. **Lane 3/4 ingest path is not identical.** Mainline / Turso read raw SQL
   on stdin. leap-c / leap-rust read a sqllogictest `.slt` file where each
   statement is wrapped with a `statement ok` directive (see
   `bench/lanes/_wrap_sql.py`). The wrapper adds ~35 % bytes but the
   per-statement parse work is equivalent; no execution path is skipped.

3. **Lane 4 does not measure file-backed WAL throughput for leap.** The
   leap sqllogictest runner opens a fresh `:memory:` database per file per
   `spec/sqllogictest-runner.spec.md § Isolation`. Mainline / Turso, given a
   file path on the CLI, write to disk. So lane 4 compares leap's in-memory
   insert path against mainline's WAL path. This is a methodology TODO; the
   current numbers over-state leap's disk-write performance (because we
   aren't measuring a disk write).

4. **Lane 6 (memory footprint) is a single sample, macOS-only.** The number
   is dominated by the allocator's initial reservation and does not reflect
   steady-state growth. Good for ballpark, not for regression tracking.

5. **No Linux numbers yet.** Everything in this directory is macOS arm64
   (M-series). The stunt commitment is Linux x86_64 + macOS arm64; a Linux
   run is a prerequisite for any public claim.

6. **No Turso comparison published.** The Turso binary is fetched by
   `bench/baselines/fetch-baselines.sh --turso` and measurements may appear
   in the CSV, but they should be treated as engineering-only signal until
   the Turso comparison is reviewed against a pinned Turso version and
   documented in the publication write-up.

## Validation history

Runs get renamed to `*-INVALID-*.csv` when we discover a harness bug that
invalidates them. Those files are kept, not deleted, so the history of what
was reported and when is auditable.

| Date       | Status                                         | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
|------------|------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 2026-04-20 | INVALID (`2026-04-20-*-INVALID-bench-had-wrapper-bug.csv`) | Lanes 2/3/4 wrapped the whole multi-statement corpus with a single `statement ok` header; leap runner failed fast on the second statement and exited in ~50 ms. Reported lane-2 and lane-3 numbers measured how fast the leap binary rejects malformed input, not actual throughput. Fixed in `bench/lanes/_wrap_sql.py` (Option A — preprocess each statement into its own `statement ok` record). Lane 1 / 5 / 6 in those CSVs were unaffected and remain valid.    |
| 2026-04-20 | validated                                      | First clean post-fix run. All 6 lanes executed actual work; mainline comparisons are honest modulo the asymmetries listed above.                                                                                                                                                                                                                                                                                                                                       |

## Disclaimers — read before quoting any number

- **These are internal numbers.** Nothing here is a publication claim. The
  pre-publication checklist in `bench/README.md` must be green before any
  external claim is made.
- **Single-host, single-OS, single-architecture.** macOS arm64 on one Mac
  Studio. No Linux validation, no repeat across hosts, no thermal-pinning.
- **Generated binaries, mid-stunt.** The leap implementations are
  pre-commitment prototypes. Lane numbers will move substantially as the
  spec and generators evolve.
- **If a leap target beats mainline by more than 2×**, sanity-check before
  reporting it: recheck the harness for any asymmetry in what work is being
  done, not just in wall-clock measurement. 32× headline numbers almost
  always mean "we're not measuring what we think we're measuring."
- **Binary-size ratios are the only measurement here that can be quoted
  at face value** — `stat` is unambiguous.
