# Full sqllogictest corpus — leap-rust — v3 → v4 diff

**Headline:** v3 614/622 (98.71%) → v4 **615/622 (98.87%)**. +1 file, +0.16 pp.

- v3 log: `tests/sqllogictest/results/2026-04-21-rust-full-v3.log`
- v4 log: `tests/sqllogictest/results/2026-04-21-rust-full-v4.log` (2026-04-21T09:36Z)
- Runner: `tests/sqllogictest/run-full-corpus-parallel.sh --target rust --timeout 90 --jobs 6`
- Binary: `src-rust/target/release/sqllogictest` (release build, clean compile)
- Corpus: `tests/sqllogictest/upstream/test` (622 `.test` files)

## Transitions

| | count |
|---|---|
| FAIL → PASS | 1 |
| PASS → FAIL | 0 |
| PASS → TIMEOUT | 0 |
| PASS → PANIC | 0 |
| TIMEOUT → PASS | 0 |
| Unchanged PASS | 614 |
| Unchanged FAIL | 5 |
| Unchanged TIMEOUT | 2 |

Zero regressions.

### FAIL → PASS (1)

- `random/groupby/slt_good_9.test` (was COMPILE_AMBIGUOUS_ALIAS cluster)

## What closed the gap since v3

- **#140** — COMPILE_AMBIGUOUS_ALIAS tiebreak: when the same alias shadows a
  base column name, mainline SQLite accepts the reference and resolves to the
  base column. The fix added `base_cols` parameter to
  `rewrite_alias_refs_in_expr` on `src-rust/src/compiler.rs` and pinned the
  semantics in `spec/sql-grammar.spec.md` as Phase 6cc. Closed one file from
  the 5-file `random/groupby/slt_good_{8..12}.test` cluster (the one where the
  ambiguity was the sole residual bug; the remaining 4 still have other
  residual issues — row-count and record-value mismatches independent of the
  alias tiebreak).

## Residual failures (7)

See `2026-04-21-rust-full-v3-diff.md` §Residual failures for full list and
kinds. 4 residual `random/groupby/slt_good_{8,10,11,12}.test` (interleaved
alias + row-count errors — slt_good_9 was the one fully closed by #140), 1
`evidence/slt_lang_update.test` (STORAGE_DUPLICATE_COLUMN + 2 UPDATE
mismatches), 2 large-SELECT timeouts (`select4.test`, `select5.test`).
