# Full sqllogictest corpus — leap-rust — v4 → v5 diff

**Headline:** v4 615/622 (98.87%) → v5 **620/622 (99.68%)**. +5 files, +0.81 pp. **Zero FAIL remaining** — the only residuals are the two known VDBE-dispatch-perf TIMEOUTs (`select4.test`, `select5.test`), out of scope.

- v4 log: `tests/sqllogictest/results/2026-04-21-rust-full-v4.log`
- v5 log: `tests/sqllogictest/results/2026-04-23-rust-full-v5.log` (2026-04-23)
- Runner: `tests/sqllogictest/run-full-corpus-parallel.sh --target rust --timeout 90 --jobs 6`
- Binary: `src-rust/target/release/sqllogictest` (release build, clean compile)
- Corpus: `tests/sqllogictest/upstream/test` (622 `.test` files)

## Transitions

| | count |
|---|---|
| FAIL → PASS | 5 |
| PASS → FAIL | 0 |
| PASS → TIMEOUT | 0 |
| PASS → PANIC | 0 |
| TIMEOUT → PASS | 0 |
| Unchanged PASS | 615 |
| Unchanged FAIL | 0 |
| Unchanged TIMEOUT | 2 |

Zero regressions.

### FAIL → PASS (5)

- `random/groupby/slt_good_8.test`
- `random/groupby/slt_good_10.test`
- `random/groupby/slt_good_11.test`
- `random/groupby/slt_good_12.test`
- `evidence/slt_lang_update.test`

## What closed the gap since v4

### Phase 6cd — HAVING / GROUP BY shadow rule (base column wins)

Closed the four `random/groupby/slt_good_{8,10,11,12}.test` residuals. Each file mixed three error surfaces: `COMPILE_AMBIGUOUS_ALIAS`, `COMPILE_AGGREGATE_IN_NON_PROJECTION_CONTEXT` (nested aggregate from substituted alias), and plain row-count / row-value mismatches — all rooted in the same compiler behaviour.

**Root cause.** Phase 6aj/6cc resolved a bare identifier in GROUP BY / HAVING / ORDER BY by preferring the output alias over the underlying base column. Phase 6cc added a *multiple-alias tiebreak* (if two projections share the name AND a base column also shares it → base wins, no AMBIGUOUS_ALIAS). But for a single-alias shadow (one `AS col0` with base column `col0`), the alias still won. This diverged from mainline SQLite in HAVING / GROUP BY and had two failure modes:

1. *Row-count / row-value mismatch.* `SELECT -col2 AS col0 FROM tab2 GROUP BY col0, col2 HAVING NOT col2 <= -col0` — alias substitution made `-col0` → `-(-col2) = col2`, giving `HAVING NOT col2 <= col2` (always false, empty output). Mainline binds `col0` to the base column → 3 rows.
2. *Nested-aggregate compile error.* `SELECT -col2 * AVG(-col2) AS col0 FROM tab0 GROUP BY col2 HAVING (-col2 + AVG(col0)) IS NULL` — alias substitution places `(-col2 * AVG(-col2))` inside `AVG(...)`, producing a nested aggregate which the compiler rightly rejects. Mainline binds the inner `col0` to the base column → legal SQL → empty HAVING match → empty output.

**Fix.** `rewrite_alias_refs_in_expr` now takes a `prefer_base_on_shadow: bool`. Call sites:
- GROUP BY, HAVING → `true` (Phase 6cd): when a base column shares the name, base column wins regardless of alias count.
- ORDER BY → `false`: alias wins on single-alias shadow (preserves `ORDER BY <alias>` idiom). The Phase 6cc multiple-alias tiebreak still fires in ORDER BY to suppress AMBIGUOUS_ALIAS when duplicate aliases collide with a real column.

**Spec.** `spec/sql-grammar.spec.md` § "Phase 6aj semantics" and "Phase 6aj compile" — clarified resolution rule, added Phase 6cd clause-specific behaviour.

**Fixture.** `tests/cross-build/phase6aj.json::non-distinct-having-base-col-wins` replaces the old `non-distinct-having-alias-still-wins` (which memorialised leap-c's non-DISTINCT quirk, now known to diverge from mainline). Cross-build equivalence on phase 6aj: Rust 11/11 green; C 10/11 (will flip on C regen by parity agent).

### UPDATE duplicate-column rightmost-wins (SQL evidence R-34751-18293)

Closed `evidence/slt_lang_update.test`.

**Root cause.** `compile_update` raised `STORAGE_DUPLICATE_COLUMN` on a repeated column in the SET list. Mainline SQLite behaviour (evidence R-34751-18293): "If a single column-name appears more than once in the list of assignment expressions, all but the rightmost occurrence is ignored."

**Fix.** `compile_update` now de-duplicates the assignment list rightmost-wins while preserving original left-to-right column ordering. Downstream codegen (Phase 9c index maintenance, `UpdateRow`, etc.) operates on the de-duplicated list. Ignored (non-rightmost) `value` expressions are NOT traversed for `ColumnRef` resolution or evaluated at runtime — side effects of repeat assignments are elided, matching mainline.

**Spec.** `spec/sql-grammar.spec.md` § "Phase 2c-3 evaluation semantics" and "Phase 2c-3 compile-time checks" — duplicate-column rejection replaced with dedup rule. `spec/vdbe-opcodes.spec.md` § `UpdateRow` note updated: `column_names` reaching the VDBE for UPDATE is always dedup'd.

**Fixture.** `tests/cross-build/phase2c3.json::update-duplicate-column-rightmost-wins` replaces the old error-expecting `update-duplicate-column-in-set`.

## Regression guard

- Phase tests: **86/86 green** on Rust (all `src-rust/target/release/phase*-test` bins against their `tests/cross-build/phase*.json` fixtures).
- Smoke: **203/203 byte-identical C ↔ Rust** on `tests/sqllogictest/smoke/`.
- Full corpus: **620/622** on Rust, zero PASS→FAIL transitions.

## C parity follow-up

The two fixture changes (phase6aj, phase2c3) introduce a spec-level rule that C does not yet implement — C currently fails both fixtures. This is the expected cross-target equivalence signal: when a spec change lands, both generators must converge. The C parity agent running in parallel will regenerate C to match.

## Residual (2 TIMEOUT, 0 FAIL)

- `select4.test` — 90s timeout. VDBE dispatch perf; out of scope for task #143.
- `select5.test` — same.

Neither indicates a correctness gap; both tests do converge on mainline SQLite values, they just run past the 90s budget on our un-tuned VDBE.
