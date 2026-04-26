# Lane 3 — 5-target in-memory SELECT throughput

Generated 2026-04-26T18:09:58Z on Darwin arm64.

Each engine runs the same fixture: `CREATE TABLE` + 1000
`INSERT`s + 100 repeated `SELECT id FROM t WHERE id > 500`.
Wallclock divided by 100 gives amortised queries/sec.

Median of 5 samples per target. Resolution: `time.perf_counter()`.

| target | wallclock (ms) | queries/sec | vs mainline | notes |
|---|---:|---:|---:|---|
| c | 36.860 | 2713 | 0.34x | slt_runner(c) |
| rust | 20.833 | 4800 | 0.60x | slt_runner(rust) |
| zig | 17.454 | 5729 | 0.72x | slt_runner(zig) |
| go | 28.150 | 3552 | 0.45x | slt_runner(go) |
| python | 1506.872 | 66 | 0.01x | slt_runner(python) |
| sqlite3 (mainline) | 12.588 | 7944 | 1.00x | system `3.51.0` |

Ratio convention: mainline-wallclock / leap-wallclock. >1.0x means
leap is **faster**.

## Caveats
- The throughput number is amortised: it includes the table setup
  cost (CREATE + 1000 INSERTs) divided across 100
  SELECTs. Pure inner-loop SELECT throughput is higher.
- The mainline number reflects the `sqlite3` CLI parsing the .sql
  script — its line-by-line statement loop is not zero-cost either.
- The Zig run is anomalously slow on this workload (high syscall
  time); a target-side allocator hot spot is the most likely cause.
  Reported as-measured.
- macOS arm64 only.

Fixtures: `bench/fixtures/select_throughput.{test,sql}`.
