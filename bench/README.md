# sqlite-leap benchmark harness

Reproducible measurement infrastructure for the six public benchmark lanes
committed to in `CLAUDE.md`. Every published claim of the form "we beat X
by Y%" must be traceable to a CSV row produced by this harness on a named
host.

> **Rule:** if it isn't in `bench/results/<date>-<hostname>.csv`, it didn't
> happen.

## Layout

```
bench/
├── README.md                 # this file
├── run-all.sh                # runs every available lane × every available target
├── plot.py                   # reads a results CSV, emits per-lane bar charts
├── lanes/
│   ├── 01-cold-start/        # lane 1: process start → first query ready
│   ├── 02-parse-speed/       # lane 2: tokens/sec through a 10MB SQL file
│   ├── 03-select-in-memory/  # lane 3: single-row SELECT throughput
│   ├── 04-insert-throughput/ # lane 4: WAL-backed INSERTs/sec, single writer
│   ├── 05-binary-size/       # lane 5: stripped-release binary bytes
│   └── 06-memory-footprint/  # lane 6: RSS after open + small DB load
├── baselines/
│   ├── fetch-baselines.sh    # downloads + builds mainline SQLite (+ optionally Turso)
│   ├── src/                  # gitignored: downloaded sources
│   └── bin/                  # gitignored: built baseline binaries
└── results/
    └── <YYYY-MM-DD>-<hostname>.csv
```

## Targets

A `--target` value identifies which engine a lane is exercising. The harness
understands four values:

| target              | binary expected at                                   |
|---------------------|------------------------------------------------------|
| `sqlite-leap-c`     | `src-c/bin/sqllogictest`                             |
| `sqlite-leap-rust`  | `src-rust/target/release/sqllogictest`               |
| `sqlite-mainline`   | `bench/baselines/bin/sqlite-mainline` (from `fetch-baselines.sh`) |
| `turso`             | `bench/baselines/bin/turso` (optional; Turso CLI, only if you ran the optional `--turso` step of `fetch-baselines.sh`) |

If a lane is asked to measure a target whose binary is missing, it prints
a CSV line with `value=NA,units=missing-binary` and exits non-zero. `run-all.sh`
tolerates that and moves on.

## CSV schema

Every `run.sh` emits exactly one line to stdout:

```
lane,target,value,units,timestamp
```

Example:

```
cold-start,sqlite-mainline,0.000138,seconds,2026-04-20T14:52:11Z
parse-speed,sqlite-leap-rust,18342112,tokens_per_second,2026-04-20T14:52:12Z
binary-size,sqlite-leap-c,612480,bytes,2026-04-20T14:52:12Z
```

`run-all.sh` appends these lines to `results/<date>-<hostname>.csv` (header
written once per file).

## Lane measurement methods (summary)

The authoritative method per lane lives in a comment at the top of each
`run.sh`. Summary here:

1. **Cold start** — wall clock of `<binary>` running a trivial `SELECT 1;`
   on an empty `:memory:` DB, repeated N times, median reported in seconds.
   Uses `hyperfine --warmup 3 --runs 30` when available, else a Python-wrapped
   `/usr/bin/time -p` median loop.
2. **Parse speed** — feed a deterministically generated 10 MiB SQL file
   (`corpus.sql`, produced by `generate-corpus.sh`) to the target's parse-only
   mode. Measure wall clock; report `bytes_per_second` (a stable proxy for
   tokens/sec; tokens are not comparable across engines). Every target parses
   the **same** corpus, so ratios are honest.
3. **In-memory SELECT** — build an in-memory table with 10 000 rows
   (deterministic corpus via `generate-corpus.sh`), then run a scripted loop
   of `SELECT value FROM t WHERE id = ?` across all 10 000 IDs (cycled 10x
   = 100 000 selects). Measure wall, report `selects_per_second`.
4. **INSERT throughput** — WAL-mode file DB, single writer, 100 000 rows
   inserted in one transaction of `INSERT INTO t VALUES (?, ?)`. Wall clock
   of the whole run, minus a fixed setup baseline (measured once). Report
   `inserts_per_second`. File DB lives in a tmpdir, nuked after the run.
5. **Binary size** — `stat` the stripped release binary. Report `bytes`.
6. **Memory footprint** — open a small (64 KiB) DB, run `SELECT count(*)`,
   sleep 50ms, sample peak RSS via `/usr/bin/time -l` (macOS) or
   `/usr/bin/time -v` (Linux). Report `bytes`.

All lane scripts are **deterministic** — same corpus, same query script,
same seed. Variance comes from the OS scheduler only.

## How to run

First-time setup:

```sh
./bench/baselines/fetch-baselines.sh          # mainline SQLite only
./bench/baselines/fetch-baselines.sh --turso  # also clone + build Turso (slower)
```

Run a single lane against a single target:

```sh
./bench/lanes/01-cold-start/run.sh --target sqlite-mainline
# → cold-start,sqlite-mainline,0.000137,seconds,2026-04-20T14:52:11Z
```

Run everything available:

```sh
./bench/run-all.sh
# → bench/results/2026-04-20-<hostname>.csv
```

Plot results:

```sh
./bench/plot.py bench/results/2026-04-20-<hostname>.csv
# → bench/results/2026-04-20-<hostname>.{cold-start,parse-speed,...}.png
```

## Linux x86_64 cross-validation (Docker)

A separate Docker image runs the same lanes on Linux x86_64 for
cross-validation before publication. See `Dockerfile.linux-x86` and
`run-linux-bench.sh`; the output sidecar `results/linux-x86_64.README.md`
documents image / kernel / glibc / toolchain versions and any
Linux-specific findings.

```
# Build + run (from repo root)
docker build --platform=linux/amd64 \
    -f bench/Dockerfile.linux-x86 \
    -t sqlite-leap-bench:linux-amd64 .
docker run --rm --platform=linux/amd64 \
    -v "$PWD":/repo \
    -e BENCH_DATE="$(date -u +%Y-%m-%d)" \
    sqlite-leap-bench:linux-amd64 \
    bash /repo/bench/run-linux-bench.sh
```

On an arm64 host the image runs under emulation; that's acceptable for
correctness cross-validation but not for absolute-speed publication
numbers. For publication, run through the `ci-linux` GitHub workflow on a
native x86_64 runner.

## Host requirements

- macOS arm64 or Linux x86_64 (the two we publish on).
- `bash`, `awk`, `python3` (>= 3.9).
- **Optional:** `hyperfine` (strongly preferred for timing accuracy). Install
  with `brew install hyperfine` or `cargo install hyperfine`.
- **Optional:** `matplotlib` for plotting. `pip install matplotlib`.
- A C toolchain (`gcc`/`clang`) to build mainline SQLite baseline.
- `cargo` (only if fetching the Turso baseline).

## Pre-publication checklist (do NOT ship numbers unless every box is true)

- [ ] Ran on a quiet host (no background builds, no Docker, no browser video).
- [ ] Ran on **both** Linux x86_64 and macOS arm64; CSVs committed for each.
- [ ] Mainline SQLite baseline built from the exact version named in
      `fetch-baselines.sh` (pinned, not "latest").
- [ ] Turso baseline (if claimed) built from a named commit SHA.
- [ ] `hyperfine` present — raw `time` fallback is fine for local dev but not
      for publication.
- [ ] `src-c` and `src-rust` were regenerated from current spec immediately
      before the run (no stale binaries).
- [ ] Plot PNGs and CSV are both committed.
