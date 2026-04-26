# Lane 3 — 5-target in-memory SELECT throughput

Generated 2026-04-26T18:51:08Z on Darwin arm64.

Each engine is sampled on **two** fixtures, 5 samples each, median reported.
Resolution: `time.perf_counter()`.

## Fixtures

| fixture | rows | SELECTs | predicate | what it measures |
|---|---:|---:|---|---|
| amortized | 1000 | 100 | `id > 500` (500 rows) | full pipeline (startup + INSERT setup amortized over 100 SELECTs) |
| pure-loop | 1000 | 10000 | `id = 750` (1 row) | engine inner-loop (setup is ~5-10% of total at 10:1 SELECT:INSERT) |

## Amortized (full pipeline)

Wallclock divided by 100 SELECTs.

| target | wallclock (ms) | queries/sec | vs mainline |
|---|---:|---:|---:|
| c | 22.226 | 4499 | 0.54x |
| rust | 17.598 | 5682 | 0.68x |
| zig | 16.297 | 6136 | 0.73x |
| go | 27.256 | 3669 | 0.44x |
| python | 1498.690 | 67 | 0.01x |
| sqlite3 (mainline) | 11.970 | 8354 | 1.00x |

## Pure-loop (engine inner-loop)

Wallclock divided by 10000 SELECTs. Setup amortizes to ~5-10%.

| target | wallclock (ms) | queries/sec | vs mainline |
|---|---:|---:|---:|
| c | 822.453 | 12159 | 0.24x |
| rust | 362.141 | 27614 | 0.55x |
| zig | 520.682 | 19206 | 0.38x |
| go | 910.646 | 10981 | 0.22x |
| python | 104683.022 | 96 | 0.00x |
| sqlite3 (mainline) | 200.156 | 49961 | 1.00x |

Ratio convention: mainline-wallclock / leap-wallclock. >1.0x means
leap is **faster**.

## Caveats

- The amortized number shares a fraction of the table-setup cost
  (1000 INSERTs / 100 SELECTs = 10x setup overhead).
  The pure-loop number flips the ratio (1:10) and uses a lean
  predicate so render cost is negligible — closer to true engine
  SELECT throughput.
- The two predicates differ. Amortized returns 500 rows per query;
  pure-loop returns 1 row. Both perform a full table scan over
  1000 rows (no index).
- The mainline number reflects the `sqlite3` CLI parsing the .sql
  script — its line-by-line statement loop is not zero-cost either.
- macOS arm64 only.

Fixtures: `bench/fixtures/select_throughput.{test,sql}` and
`bench/fixtures/select_throughput_pure.{test,sql}`.
