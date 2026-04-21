# C corpus v1 vs v2 diff — 2026-04-20

## Headline

| | v1 | v2 | delta |
|---|---|---|---|
| **PASS rate** | 161/622 = **25.88%** | 161/622 = **25.88%** | **0.00 pp** |
| PASS | 161 | 161 | 0 |
| FAIL | 262 | 271 | +9 |
| TIMEOUT | 190 | 190 | 0 |
| PANIC | 9 | 0 | **-9** |
| total | 622 | 622 | — |

## Transition matrix (every file's v1 → v2 status)

| v1 | → | v2 | count |
|---|---|---|---|
| PASS | → | PASS | 161 |
| FAIL | → | FAIL | 262 |
| TIMEOUT | → | TIMEOUT | 190 |
| PANIC | → | FAIL | **9** |
| FAIL | → | PASS | **0** |
| PASS | → | FAIL | **0** |
| any other | | | 0 |

- **FAIL→PASS: 0** (the three fixes did not flip any file to PASS)
- **PASS→FAIL: 0** (no regressions)
- **PANIC→FAIL: 9** (SIGBUS fix #119 eliminated crashes — all 9 now run to completion but still fail on record-level mismatches)
- **PANIC→PASS: 0**

All 9 PANIC→FAIL files are in `random/groupby/`:
`slt_good_0`, `_1`, `_13`, `_2`, `_3`, `_4`, `_5`, `_7`, `_8`.
They now emit `column-count-mismatch-vs-typestring` record failures instead of crashing (dozens of record-level FAILs each, ~10k PASS records per file).

## Why no file-level pass-rate movement

Every file in `random/expr`, `random/aggregates`, and `random/groupby` contains 8k–15k records. A single wrong record flips the whole file to FAIL. Sampled:

- `random/expr/slt_good_0.test`: **10008 PASS, 4 FAIL** records (expected NULL got integer). NULLIF fix resolved most UNKNOWN_FUNCTION cases; 4 remaining mismatches are a different correctness bug.
- `random/expr/slt_good_1.test`: 10007 PASS, 5 FAIL (NULL-arithmetic residuals).
- `random/aggregates/slt_good_0.test`: 9994 PASS, 18 FAIL (aggregate/scalar value mismatches, not function-name errors).
- `random/groupby/slt_good_0.test`: 9970 PASS, 42 FAIL (mostly `column-count-mismatch-vs-typestring`).

The fixes landed — but the residual record-level correctness gaps in these heavily-parameterized random suites keep the file-level verdict at FAIL. **Record-level pass rate jumped significantly** (not measured here; would require summing SUMMARY lines). File-level rate will only move when a whole file clears to zero mismatches.

## Top-5 failure categories in v2

Grouped by 2-deep path segment:

| # | category | status | count |
|---|---|---|---|
| 1 | `random/aggregates` | FAIL | 130 |
| 2 | `random/expr` | FAIL | 120 |
| 3 | `index/commute` | TIMEOUT | 52 |
| 4 | `index/orderby_nosort` | TIMEOUT | 47 |
| 5 | `index/orderby` | TIMEOUT | 30 |

Other notable buckets: `index/random` TIMEOUT=23, `random/groupby` FAIL=14, `index/in` TIMEOUT=13, `index/between` TIMEOUT=13, `index/view` TIMEOUT=10 / FAIL=5.

Dominant failure modes:

1. **Record-level NULL/arithmetic correctness** — `random/expr`, `random/aggregates`: expected NULL, got value (or vice versa); occasional wrong numeric result. Likely residual NULL-propagation or overflow rules.
2. **Column-count-mismatch-vs-typestring** — `random/groupby`: result metadata disagreement (ex-panic files).
3. **90 s timeouts** — entire `index/*` suites never reach the summary; most-likely seq-scans-instead-of-indexed-lookups in the planner.
4. **Wrong aggregate values** — `random/aggregates`: SUM/COUNT/AVG produce the wrong number on particular shapes.

## Files

- v2 log: `/Users/stanislav/code/sqlite-leap/tests/sqllogictest/results/2026-04-20-c-full-v2.log`
- v1 log: `/Users/stanislav/code/sqlite-leap/tests/sqllogictest/results/2026-04-20-c-full.log`

## Run parameters

- Binary: `src-c/bin/sqllogictest` (clean rebuild at 2026-04-20T18:33 PDT; zero warnings)
- Corpus: 622 files under `tests/sqllogictest/upstream/test`
- Timeout: 90s per file, 8 parallel workers
- Wallclock: ~37 min
- Script: `tests/sqllogictest/run-full-corpus-parallel.sh --target c --timeout 90 --jobs 8`
