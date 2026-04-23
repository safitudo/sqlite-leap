# File-format bidirectional roundtrip fuzz — 2026-04-21

- Campaign seed: `4276994061`

- Workloads: 100
- Rows per workload: 100
- Elapsed: 38.7s

## Matrix: byte-identical SELECT results

Each cell shows `identical / diverge / produce_err / read_err / read_crash`.

Oracle = mainline writes, mainline reads, so `(mainline, mainline)` counts the number of workloads where the oracle pipeline itself succeeded.

| producer \ reader | mainline | leap-c | leap-rust |
|---|---|---|---|
| mainline | 100 / 0 / 0 / 0 / 0 | 100 / 0 / 0 / 0 / 0 | 100 / 0 / 0 / 0 / 0 |
| leap-c | 100 / 0 / 0 / 0 / 0 | 100 / 0 / 0 / 0 / 0 | 100 / 0 / 0 / 0 / 0 |
| leap-rust | 100 / 0 / 0 / 0 / 0 | 100 / 0 / 0 / 0 / 0 | 100 / 0 / 0 / 0 / 0 |

## Totals

- Byte-identical cells: **900**
- Divergent cells: **0**
- Producer errors (counted per-reader): 0
- Reader engine errors: 0
- Reader crashes: 0

## Divergences

None.

