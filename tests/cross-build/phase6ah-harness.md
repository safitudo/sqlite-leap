# Phase 6ah harness — IN (subquery) predicate

Extends the existing IN (expr-list) form (Phase 6v) with an IN (SELECT …) form. Uncorrelated only in v1 — the subquery is evaluated once, its result set is materialized, then each outer-row LHS value is tested for membership.

Gate: 8 fixtures green both targets. `SUMMARY phase=6ah target=<c|rust> passed=8 failed=0 total=8`.

Notes:

- Grammar: `comparison-rhs := ... | [ KEYWORD_NOT ] KEYWORD_IN LPAREN select-stmt RPAREN` (extends 6v's `IN LPAREN expr-list RPAREN`).
- **Arity check**: the subquery MUST return exactly one column → `COMPILE_SUBQUERY_WRONG_ARITY` otherwise.
- **Uncorrelated only** in v1: the subquery does not reference outer-scope names. Correlated IN-subquery is deferred (requires the same outer-scope threading as 6ag correlated subqueries; future phase).
- **Evaluation**: materialize the subquery result into an ephemeral set (or sorter). For each outer row, probe the set for membership.
- **3VL / NULL semantics** (inheriting the 6v / 6bc-reconciled rules):
  - `x IN (SELECT …)` — standard 3VL. If the set is empty → 0 (no match, regardless of x including NULL). If x is NULL → NULL. If x matches → 1. If x doesn't match and the set contains NULL → NULL (poison).
  - `x NOT IN (SELECT …)` — NEVER true when any row in the subquery is NULL. If set is empty → 1 (vacuously true). Otherwise standard 3VL.
- **Implementation hint**: desugar `x IN (SELECT …)` to something like:
  ```
  materialize subquery to ephemeral cursor
  for each outer row:
      probe cursor: was x found? was any NULL seen?
      apply 3VL reduction
  ```
- No new opcodes needed if you reuse 9be range-seek / ephemeral-table machinery. If you do need a new opcode, flag it.
- Compile-time desugar to an EXISTS-over-join shape is also acceptable (SQLite's internal path). Either implementation produces byte-identical output; the choice is yours.
