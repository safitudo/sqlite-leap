# Phase 6bp harness — no-FROM SELECT + Rust dedup-slot regression

Two narrow gaps surfaced during post-6bn/6bo random-corpus investigation. Each is localized; combined they unblock the bulk of remaining random/expr and random/aggregates files that previously appeared to "time out" but were actually crashing or errorring on specific query shapes.

No new opcodes. No new reserved keywords. `max_invariant` unchanged. Gate: 11 fixtures green both targets.

## Gap 1 — SELECT without FROM (expressions and aggregates)

SQLite accepts `SELECT <expression-list>` with no `FROM` clause. Semantics:

- The statement produces exactly **one result row**, computed from exactly **one synthetic input row** (no columns, but its existence is what lets aggregates operate).
- Aggregates are applied over the one-element set `{ argument evaluated against the synthetic row }`, with standard NULL-skipping:
  - `COUNT(*)` → `1`
  - `COUNT(expr)` → `1` if `expr` is non-NULL, else `0`
  - `SUM(expr)` → `expr` (or `NULL` if `expr` is NULL)
  - `TOTAL(expr)` → `expr` as REAL (or `0.0` if `expr` is NULL, per 6ap SQLite-compat)
  - `MIN(expr)` / `MAX(expr)` → `expr` (or `NULL` if `expr` is NULL)
  - `AVG(expr)` → `expr` as REAL (or `NULL` if `expr` is NULL)
  - `GROUP_CONCAT(expr)` → `expr` as TEXT (or `NULL` if `expr` is NULL)
- Non-aggregate scalar expressions evaluate normally — literals, arithmetic, CASE, COALESCE, function calls over constants. Bare column references still raise `EVAL_COLUMN_WITHOUT_TABLE` (no table to resolve against).

**Rationale:** corpus evidence — upstream sqllogictest has `SELECT SUM(79)` expecting `79`; `SELECT SUM(DISTINCT 11)` expecting `11`; the random/expr label-6 query expects `MIN(-30) = -30`. These inputs require one-synthetic-row semantics, not zero-row.

**Convergent-contradiction history:** the initial version of this harness specified zero-row semantics (COUNT* = 0, MIN = NULL). Both C and Rust generator agents implemented it correctly per the spec and both failed the two corpus-shape fixtures (coalesce-agg-no-from, case-agg-no-from) with exactly the same pass/fail pattern. That cross-corroboration signal surfaced the spec bug, which was corrected to one-synthetic-row. Per project methodology: when both agents independently converge on the same failing implementation, fix the spec, not the generators.

Compiler:
- When AST SELECT has `from: None` (or target-language equivalent):
  - No cursor open. No scan loop. Do not dereference any table name.
  - For non-aggregate projections: single-shot eval + `ResultRow` + `Halt`.
  - For aggregate projections: initialize accumulators; emit **exactly one** aggregate-update step applying the projection's aggregate args against the synthetic (no-column) row; finalize accumulators per usual; emit the projection list; `ResultRow`; `Halt`.
- In C, replace the current `sl_strdup(ast->sel_table)` call (the segfault when `sel_table == NULL`) with a no-FROM code path that skips cursor setup entirely.

Grammar unchanged — `SELECT` without `FROM` is already accepted at the parser level.

## Gap 2 — Rust dedup-slot allocation in joined-aggregated-no-GROUP-BY path

Bug: `SELECT SUM(DISTINCT x) FROM a, b` (any multi-table FROM with at least one DISTINCT aggregate and no GROUP BY) panics in Rust at `vdbe.rs:1034` with "index out of bounds: len is 0 but index is 0". Root cause: `compile_joined_aggregated_no_group_by` (src-rust/src/compiler.rs) returns `num_dedup_sets: 0` unconditionally, but `emit_accumulator_init` emits `AggDedupReset { dedup_slot }` for each DISTINCT aggregate — those slot indices then index out-of-bounds at VDBE startup.

Fix: match the three other sites that compute this correctly:

```rust
num_dedup_sets: if aggregates.iter().any(|(_, _, d)| *d) {
    aggregates.len()
} else {
    0
},
```

C target is already correct for this case — single-line Rust-only fix, flagged here so the cross-build gate covers it.

### Non-goals

- No-FROM DML (`INSERT ... VALUES (SELECT 1)` edge cases) — existing 6w covers the general shape.
- No-FROM subqueries in scalar context (`SELECT (SELECT 1) FROM t`) — unchanged.
- VALUES keyword as a row constructor (`VALUES (1,2), (3,4)` as a top-level statement) — separate phase.
