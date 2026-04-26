---
name: compiler/subqueries
kind: leaf
inherits:
  - /parts/compiler/parts/expressions/master.md
  - /parts/compiler/parts/name-resolution/master.md
  - /parts/compiler/parts/statements/select/master.md
emits:
  c: { path: src-c/compiler/subqueries.c, headers: [src-c/compiler/subqueries.h] }
  rust: { path: src-rust/src/compiler/subqueries.rs }
---

# Part: compiler/subqueries

Compiles subqueries in their four forms:

- **Scalar** — `(SELECT col FROM …)` returning exactly one row,
  one column. Embedded in an expression.
- **IN (subquery)** — `x IN (SELECT …)`. Embedded in an
  expression.
- **EXISTS (subquery)** — boolean test.
- **Derived table** — `FROM (SELECT …) AS t`. A FROM source, not
  an expression embed.

## Public interface

```
compile_scalar_subquery(select, ctx, dest_reg, program_out) -> Result<()>
compile_in_subquery(select, ctx, left_reg, result_reg, program_out) -> Result<()>
compile_exists_subquery(select, ctx, dest_reg, program_out) -> Result<()>
compile_derived_table(select, ctx, program_out) -> Result<DerivedSource>
```

## Correlated subqueries

A subquery that references outer-scope columns is **correlated**.
This sub-part:

1. Detects correlation by walking the inner AST with the outer
   scope's name-resolution. If name-resolution falls back to outer
   scope for any ColumnRef, the subquery is correlated.
2. For correlated subqueries, compiles into a nested-loop inner
   program that re-runs per outer row. The outer loop re-binds
   the outer-scope register slots; the inner program reads them
   via `Column` opcodes against the outer cursor.
3. For uncorrelated subqueries, compiles once and either
   materializes (IN, EXISTS) or substitutes the single result
   (scalar).

### Lowering strategies (target-neutral observable contract)

The contract above is the observable semantics. Two lowering
strategies are both spec-conformant, picked per target by its
generation pragmatics:

- **Inline-program (Rust/C/Zig/Go)**: emit the inner program inline
  at the expression-evaluation point inside the outer loop body.
  The inner program reads outer-scope values via Copy ops from
  outer-cursor-bound registers (see select-compile §α23 outer
  scope frames). Cheap; one inner program emission per call site.
- **Clone-with-extra-column (Python)**: when the outer FROM is a
  single named base table, run the inner SELECT once per outer row
  at compile time, with outer-col references in the inner AST
  substituted as literals; install a clone of the outer table with
  one extra column carrying the per-row results, and rewrite the
  outer SELECT to reference that synth column. Equivalent
  observable semantics; trade-off is O(outer_rows × inner_cost) at
  compile time. Targets with a pre-execute model (where opcodes do
  not see per-iteration outer-cursor state) may use this path. Outer
  shapes outside single-named-table (JOIN, derived FROM, CTE-as-
  outer) clean-stop with a more specific deferral. Correlated
  EXISTS / IN-subquery deferral is permitted in the clone path but
  must surface a more specific deferral message.

## Phase 6n sentinel

When a subquery appears inside an expression, the expression
compiler emits a placeholder register reference with a high-bit
sentinel encoding the subquery ID. After outer compilation, a
resolution pass walks the emitted opcodes and replaces each
placeholder with the concrete dest_reg allocated to that subquery.
This is the v1 "Phase 6n" mechanism, carried into v2 unchanged.

## Cursor-id allocation invariant (v2 pin)

When the outer SELECT body opens its own table cursor(s), every
subquery — both **materialized-once** (uncorrelated scalar / EXISTS /
IN whose body is rewritten to BufferAppend in a prelude that runs
before the outer scan) and **correlated-inline** (per-row, with
OpenRead in the prelude and Rewind in the body) — MUST allocate
cursor ids strictly **above** the outer's reserved cursor count. The
allocation algorithm is:

```
outer_cursors = (buffered_source ? 0 : 1)        // outer's own scan
next_subquery_cid = outer_cursors + cursors_added_so_far
cursors_added_so_far += 1
```

Concretely: if the outer reserves cursor 0 for its scan of the named
FROM table, the first subquery (whether materialized or correlated)
takes cursor 1; the second takes cursor 2; and so on. The shift
applied to a materialized inner SELECT's compiled opcodes (whose
inner cursors start at 0 in their own compile scope) must be
`outer_cursors + cursors_added_so_far`, not just `cursors_added_so_far`.

Why: a materialized inner SELECT typically emits its own
`Close cursor=0` at scan tail (mirror of its `OpenRead cursor=0` at
scan head). After cursor-shifting, that Close lands at cursor id
`outer_cursors + cursors_added_so_far - 1`. If the shift baseline
omits `outer_cursors`, the Close collides with the cursor id a
sibling correlated subquery already opened in the prelude — the
sibling's cursor is silently closed, and the per-row body's next
Rewind on it raises `CursorClosed` at runtime.

This bug surfaces only when **two or more subqueries co-occur** with
**at least one correlated** (its prelude opens a long-lived cursor)
and **at least one materialized** (its prelude scans + closes its
own cursor). A single subquery in isolation, of either flavor, runs
clean because there is no sibling cursor for the Close to collide
with.

Spec rule for every target generator: the SubCtx (or equivalent
per-outer-row subquery accumulator) must record the outer's cursor
count at construction time and use it as the shift baseline for
both correlated-cursor allocation and materialized-cursor shifting.

## Allocator-counter monotonicity (v2 pin)

The §"Cursor-id allocation invariant" rule above covers cursor ids
allocated by *direct* subquery prelude emission. A second class of
bugs appears when an inner subquery's WHERE itself contains nested
sub-IN / EXISTS / scalar-subqueries, and the outer post-recursion
bookkeeping CLOBBERS (assigns to) the shared SubCtx's allocator
counters. The deeper recursion has already advanced
`expr_next_cursor` and `expr_reg_offset` past the outer's
"primary FROM" tally, but the outer code path's post-recurse
fixup writes back the smaller value, "forgetting" the deeper
bumps. The next sibling subquery then collides with cursor ids /
register lanes the deep recursion already claimed → silent
overwrite of an outer-expression result register, or
`CursorClosed` halt.

Spec rule for every target generator: every SubCtx allocator
counter (cursor count, expr-register offset, scratch-lane base)
MUST advance **monotonically** across nested subquery emissions.
Post-recursion fixups must use `max(old, new)` semantics, never
plain assignment. Concretely:

```
// WRONG (clobbers deeper recursion's bumps):
g_subctx.expr_next_cursor = cur_off + inner_ok.num_cursors
g_subctx.expr_reg_offset  = reg_off + used_regs

// RIGHT (monotonic):
g_subctx.expr_next_cursor = max(g_subctx.expr_next_cursor,
                                cur_off + inner_ok.num_cursors)
g_subctx.expr_reg_offset  = max(g_subctx.expr_reg_offset,
                                reg_off + used_regs)
```

A related, sibling rule covers WHERE-expression compilation that
produces a **destination register** AND THEN inlines a subquery
program: the subquery's `reg_offset` shift baseline must be
strictly **above** the destination register the outer expression
already wrote to. Otherwise the inner program's column reads
trample the outer's BinOp result before the outer Combinator
reads it. Concretely, on entry to
`compile_{scalar,exists,in}_subquery`, bump `ctx.reg_offset` to
at least `dest_reg + 1` before calling
`materialize_inner_select`.

This bug surfaces only when an outer Binary expression compiles
LHS first (writing into some R(k)), then RHS contains a
correlated EXISTS / IN-subquery whose inner column reads land at
R(k) and overwrite it. The visible symptom is a WHERE filter
silently dropped — extra rows materialize, often producing an
`got(8)=[...] expected(3)=[...]`-shape FAIL at the runner.

## Phase pins

- **Phase 6ag** — correlated subqueries.
- **Phase 6ah** — IN (subquery) form.
- **Phase 6ae** — EXISTS / NOT EXISTS.
- **Phase 6br** — subquery-in-FROM (derived tables).
- **Phase v2-cursor-baseline** — cursor-id allocation invariant
  (above) covers materialized + correlated co-occurrence. Verified
  on Go select1.test 2026-04-26 (CursorClosed: 61 → 0).
- **Phase v2-allocator-monotonic** — SubCtx allocator counters
  advance monotonically (max, never assign) across nested
  subquery emissions; subquery `reg_offset` bumped past outer
  expression's destination register before recursion. Verified
  2026-04-26: C `halt rc=2` 80 → 0 (-87 FAILs); Rust extra-rows
  cluster 218 → 141 (-77 FAILs).

## Regeneration envelope

- Target leaf size: 500–800 lines per target.
- Spec < 200 lines.
