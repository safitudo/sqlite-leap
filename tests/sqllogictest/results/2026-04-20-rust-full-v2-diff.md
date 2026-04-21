# leap-rust corpus pass-rate: v1 → v2

Two back-to-back full-corpus runs against `tests/sqllogictest/upstream/test`
(622 `.test` files), 8-way parallel, 90 s per-file timeout, leap-rust
`sqllogictest` release binary. v1 ran before the 2026-04-20 session fixes;
v2 ran after them.

## Headline

| run | passed | failed | timeouts | panics | pass_rate |
|-----|--------|--------|----------|--------|-----------|
| v1 (2026-04-20-rust-full.log)    | 402 | 218 | 2 | 0 | **64.63 %** |
| v2 (2026-04-20-rust-full-v2.log) | 584 |  36 | 2 | 0 | **93.89 %** |
| delta                            | +182 | −182 | 0 | 0 | **+29.26 pp** |

Projected 85–93 % before the run. Actual 93.89 % — at the top end.

## Transition table (v1 → v2)

| v1 → v2 | count |
|--------|-------|
| PASS → PASS       | 402 |
| FAIL → PASS       | 182 |
| FAIL → FAIL       |  36 |
| TIMEOUT → TIMEOUT |   2 |
| PASS → FAIL       |   **0** |
| PASS → TIMEOUT    |   0 |
| PASS → PANIC      |   0 |

**Zero regressions.** The two timeouts (`select4.test`, `select5.test`) are
the same files as v1; they are known wedging queries, not new damage.

## Fixes that landed and what flipped

Four Rust-side fixes landed this session:

1. **NULLIF scalar builtin** (spec + engine, issues #117/#118)
2. **DIV-zero → NULL** (issue #120)
3. **VIEW runtime wiring** (`view_subst.rs`, issue #122)
4. **Derived-table runtime wiring** (`(SELECT …) AS alias`, issue #123)

FAIL → PASS by top-level subdirectory (all 182 files):

| subdir              | files flipped |
|---------------------|---------------|
| `random/expr/`      | 120 |
| `random/aggregates/`|  41 |
| `index/view/`       |  15 |
| `random/groupby/`   |   4 |
| `evidence/`         |   2 |

The breakdown matches the fix set:

- `random/expr/` (120) — these were the `UNKNOWN_FUNCTION: nullif` failures
  noted in the session preamble; NULLIF fix turns them all on.
- `random/aggregates/` (41 of 44 in v1) and some `random/groupby/` — DIV-zero
  and derived-table/aggregate-over-subquery wiring.
- `index/view/` (all 15) — VIEW runtime wiring, exactly as predicted.
- `evidence/` (2) — language-coverage files gated on the above.

## Residual failures (36 files, 6.11 %)

Top error kinds by first-failure from the file:

| kind                          | files | notes |
|-------------------------------|-------|-------|
| `hash-mismatch` (query result hash differs) | **21** | All in `index/random/*` |
| `row-count-mismatch` (`expected-values=N got-values=M`) | **9**  | 6 × `random/groupby/`, 3 × `random/aggregates/` |
| `COMPILE_AMBIGUOUS_ALIAS`     |  4    | `random/groupby/slt_good_{9,10,11,12}.test` |
| `value-mismatch` (scalar expected vs got)  |  1    | `index/random/10/slt_good_10.test` (`expected=0 got=qbrdd` — type-coercion) |
| `STORAGE_DUPLICATE_COLUMN`    |  1    | `evidence/slt_lang_update.test:88` — UPDATE-with-ALTER-added-column |

Residual-failure subdirectories:

```
22 index/random      <- 21 hash-mismatch + 1 value-mismatch
10 random/groupby    <- 6 row-count + 4 ambiguous-alias
 3 random/aggregates <- all row-count (expected=81 got=27)
 1 evidence
```

### Reading the residuals

- The `index/random/*` hash-mismatch cluster (21/36) almost certainly points
  at a single root cause: an ORDER BY / index-ordering or collation edge case
  that makes a specific 3-column `b833e3a3…` / `2ed57cb9…` / `322178de…` hash
  reproducibly wrong. All 21 files emit the *same* expected-hash prefixes —
  one spec/query-planner bug, fanned out across generated random cases.
- The `random/aggregates` `expected=81 got=27` pattern is suspiciously
  uniform across 3 files — likely one aggregate/GROUP-BY-over-subquery shape
  still under-counting (27 = 81/3, so possibly collapsing three group keys).
- `COMPILE_AMBIGUOUS_ALIAS` (4) is a genuine new category surfaced by the
  derived-table wiring — previously these errored earlier in the pipeline;
  now the parser gets far enough to flag the ambiguity. Candidate for a
  spec-level disambiguation rule.
- `STORAGE_DUPLICATE_COLUMN` (1) is an ALTER TABLE ADD COLUMN interaction
  with an UPDATE on the new column.

None of the residuals look like they require a new subsystem — they look
like ~3 spec/engine bug classes fanned out across generated test variants.

## Run metadata

- host: darwin arm64 (macOS)
- jobs: 8
- per-file timeout: 90 s
- corpus: `tests/sqllogictest/upstream/test` (622 files)
- binary: `src-rust/target/release/sqllogictest`
- logs:
  - v1 `tests/sqllogictest/results/2026-04-20-rust-full.log`
  - v2 `tests/sqllogictest/results/2026-04-20-rust-full-v2.log`
