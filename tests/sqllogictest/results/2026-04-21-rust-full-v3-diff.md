# Full sqllogictest corpus — leap-rust — v2 → v3 diff

**Headline:** v2 584/622 (93.89%) → v3 **614/622 (98.71%)**. +30 files, +4.82pp.

- v2 log: `tests/sqllogictest/results/2026-04-20-rust-full-v2.log` (2026-04-21T01:31:05Z)
- v3 log: `tests/sqllogictest/results/2026-04-21-rust-full-v3.log` (2026-04-21T04:03:51Z)
- Runner: `tests/sqllogictest/run-full-corpus-parallel.sh --target rust --timeout 90 --jobs 8`
- Binary: `src-rust/target/release/sqllogictest` (release build, clean compile)
- Corpus: `tests/sqllogictest/upstream/test` (622 `.test` files)

## Transitions

| | count |
|---|---|
| FAIL → PASS | 30 |
| PASS → FAIL | 0 |
| PASS → TIMEOUT | 0 |
| PASS → PANIC | 0 |
| TIMEOUT → PASS | 0 |
| Unchanged PASS | 584 |
| Unchanged FAIL | 6 |
| Unchanged TIMEOUT | 2 |

Zero regressions.

### FAIL → PASS (30)

```
index/random/10/slt_good_0.test
index/random/10/slt_good_1.test
index/random/10/slt_good_10.test
index/random/10/slt_good_11.test
index/random/10/slt_good_12.test
index/random/10/slt_good_13.test
index/random/10/slt_good_14.test
index/random/10/slt_good_2.test
index/random/10/slt_good_3.test
index/random/10/slt_good_4.test
index/random/10/slt_good_5.test
index/random/10/slt_good_6.test
index/random/10/slt_good_7.test
index/random/10/slt_good_8.test
index/random/10/slt_good_9.test
index/random/100/slt_good_0.test
index/random/100/slt_good_1.test
index/random/1000/slt_good_0.test
index/random/1000/slt_good_5.test
index/random/1000/slt_good_6.test
index/random/1000/slt_good_7.test
index/random/1000/slt_good_8.test
random/aggregates/slt_good_126.test
random/aggregates/slt_good_47.test
random/aggregates/slt_good_7.test
random/groupby/slt_good_0.test
random/groupby/slt_good_1.test
random/groupby/slt_good_13.test
random/groupby/slt_good_6.test
random/groupby/slt_good_7.test
```

## Residual failures (8)

### FAIL (6)

| File | Dominant error kind(s) |
|---|---|
| `random/groupby/slt_good_8.test`  | `COMPILE_AMBIGUOUS_ALIAS` on GROUP BY / ORDER BY alias resolution; 1 row-count mismatch |
| `random/groupby/slt_good_9.test`  | `COMPILE_AMBIGUOUS_ALIAS` cluster |
| `random/groupby/slt_good_10.test` | `COMPILE_AMBIGUOUS_ALIAS` cluster; 1 row-count mismatch |
| `random/groupby/slt_good_11.test` | `COMPILE_AMBIGUOUS_ALIAS` cluster |
| `random/groupby/slt_good_12.test` | `COMPILE_AMBIGUOUS_ALIAS` cluster |
| `evidence/slt_lang_update.test`   | `STORAGE_DUPLICATE_COLUMN` on a DDL statement; 2 UPDATE row-value mismatches |

### TIMEOUT (2, 90s wall budget)

| File | Elapsed |
|---|---|
| `select4.test` | 90519 ms |
| `select5.test` | 90512 ms |

Both are the large VDBE SELECT stress files; carried over from v2 unchanged.

## Residual-failure kinds (grouped)

- **Compile-time alias resolution** (`COMPILE_AMBIGUOUS_ALIAS`) — drives all 5 residual `random/groupby/slt_good_{8..12}.test`. Parser/planner rejects queries where SQLite resolves the alias without ambiguity. Single spec fix likely closes the cluster.
- **Row-value correctness residue** in the alias-heavy files (a handful of `expected-values`/`expected-rows` mismatches interleaved with the compile errors).
- **UPDATE + DDL edge case** in `evidence/slt_lang_update.test`: one `STORAGE_DUPLICATE_COLUMN` on a `statement ok` line and two UPDATE result mismatches; narrow, isolated.
- **Large-SELECT timeouts** on `select4.test` / `select5.test`: performance, not correctness; unchanged since v2.

## What closed the gap since v2

Fixes landed between v2 (01:31Z) and v3 (04:03Z):

- **#126 cluster**
  - `HASH_MISMATCH` typechar-coercion fix (numeric/text affinity alignment at hash time) — unblocked the `index/random/*` block and several `random/aggregates/*` / `random/groupby/*` files.
  - Star-in-GROUP-BY handling (`SELECT *, agg(...) ... GROUP BY ...` / `GROUP BY *` surface forms) — finished off the remaining `random/groupby/slt_good_{0,1,6,7,13}.test`.
  - LEFT-join-tail nested null-fill — corrected right-side NULL padding on nested LEFT chains, relevant across the `index/random/*` families.
- **#130 runner → engine port** — sqllogictest runner now drives the engine through the in-process API rather than the CLI path, eliminating a class of whitespace / type-coercion discrepancies in the harness.

Consistency note: the live in-memory measurement reported at commit time (614/622, 98.71%) matches this on-disk log byte-for-byte on the summary, confirming the claim with a durable artifact.
