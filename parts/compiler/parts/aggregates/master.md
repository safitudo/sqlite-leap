---
name: compiler/aggregates
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /schema/ast.schema.json
  - /schema/program.schema.json
  - /parts/vdbe/parts/opcodes-agg/master.md
  - /parts/compiler/parts/expressions/master.md
  - /parts/compiler/parts/name-resolution/master.md
emits:
  c:
    path: src-c/compiler/aggregates.c
    headers: [src-c/compiler/aggregates.h]
  rust:
    path: src-rust/src/compiler/aggregates.rs
---

# Part: compiler/aggregates

Compiles aggregate queries: SELECT statements with aggregate
functions and/or GROUP BY clauses. Also the HAVING filter. Owns
DISTINCT on aggregates and the bare-column-in-GROUP-BY rule.

This is the hardest cross-cutting sub-part. It interacts with
expressions (for aggregate arguments), name-resolution (alias
shadow rules in GROUP BY / HAVING / ORDER BY), and vdbe/opcodes-agg
(for the AggStep/AggFinal lifecycle).

## Public interface

```
compile_aggregate_query(
    select:        &SelectCore<'src>,
    ctx:           &CompileContext,
    program_out:   &mut ProgramBuilder,
) -> Result<(), CompileError>
```

Called by `parts/statements/select/` when it determines the query
is aggregate (presence of aggregate functions or GROUP BY). Fully
replaces the non-aggregate compile path for that statement.

## Detection rule

A SelectCore is aggregate if ANY of:

- The SELECT list contains a bare `AggregateCall` in any projection.
- The HAVING clause is present.
- The GROUP BY clause is non-empty.

Otherwise it is non-aggregate; `parts/statements/select/` takes the
default path.

## Compilation recipe

The emitted Program follows this state machine:

1. **Cursor setup.** Open read cursors for all tables in FROM
   (delegated to parts/statements/select/ via shared helper).
2. **Group initialization.** Allocate an "aggregate accumulator
   array" — one slot per (aggregate function, argument tuple)
   appearing in the query. Reset via `AggReset`.
3. **Scan loop.** `Rewind`; for each row:
   - Compute WHERE (if present). Skip on false.
   - Compute grouping key (GROUP BY expression list → register
     tuple).
   - If group changed since last row (or first row), finalize the
     previous group's aggregates and emit its output row (HAVING +
     SELECT list projection), then reset accumulators.
   - Accumulate this row's contribution via `AggStep` for each
     aggregate call.
   - `Next`.
4. **Final group.** After loop end, finalize and emit the last
   group.
5. **ORDER BY / LIMIT / OFFSET.** If present, the output rows from
   step 4 feed into an ORDER BY buffer (sort) then paginate. (Shared
   ORDER BY helper owned by parts/statements/select/.)

Implicit single-group aggregates (no GROUP BY) skip the group-
change check: all rows accumulate into one group, finalized once at
end.

## Bare column in GROUP BY

`SELECT a, COUNT(*) FROM t GROUP BY a` — `a` is a "bare column,"
resolved to the same column that appears in GROUP BY.

`SELECT a, b, COUNT(*) FROM t GROUP BY a` — `b` is a bare column
NOT in GROUP BY. SQLite's permissive behavior: `b` takes the value
from an arbitrary row in the group (first or last row). Phase 6bo
owner: emit `Column` reading from the cursor state at group-finalize
time. This is non-standard SQL but matches SQLite.

## Aggregate functions (closed set)

Each function has a compilation recipe + a runtime lifecycle
(AggStep + AggFinal) owned by `parts/vdbe/parts/opcodes-agg/`. The
compiler emits the lifecycle opcodes; runtime owns the
accumulator.

- `COUNT(*)` — accumulator = integer, step: `acc++`, final: `acc`.
- `COUNT(expr)` — accumulator = integer, step: `if expr NOT NULL:
  acc++`, final: `acc`.
- `COUNT(DISTINCT expr)` — accumulator = (integer, set-of-seen),
  step: `if expr NOT NULL and not in seen: acc++, seen.add(expr)`,
  final: `acc`. DISTINCT accumulator state is per-group; reset on
  group change.
- `SUM(expr)` — accumulator = numeric; NULLs skipped; empty group →
  NULL (not 0). Phase 6bd: INTEGER + INTEGER stays INTEGER, with
  overflow promoting to REAL.
- `TOTAL(expr)` — like SUM but empty group → 0.0 (REAL, always).
  Phase 6ap.
- `AVG(expr)` — accumulator = (sum, count); empty group → NULL.
- `MIN(expr)` / `MAX(expr)` — accumulator = current best; NULLs
  skipped. Phase 6ai: MIN/MAX on strings uses BINARY collation by
  default unless column collation differs.
- `GROUP_CONCAT(expr [, sep])` — accumulator = (string, first-flag);
  separator default is `','`. Phase 6ap.

## DISTINCT on aggregates

`SELECT COUNT(DISTINCT x)` — the aggregates sub-part emits a
per-group deduplication buffer. Implementation: sort+unique on
group close, or hash-set during step. Decision: hash-set during
step (lower memory for typical group sizes, predictable cost).

Phase 6ai pin: COUNT(DISTINCT) and MIN/MAX on strings interact;
both paths go through the same dedup/compare logic with BINARY
collation.

## HAVING compilation

HAVING is an expression compiled in `ctx.aggregate_mode = Grouped`.
In this mode:

- Aggregate functions are legal and emit accumulator reads (`AggValue`
  opcode reads the accumulator at finalize time).
- Bare column references obey the same "some row in group" rule as
  in the SELECT list. Same Phase 6bo path.
- Grouping columns are legal at their GROUP BY position.

The HAVING expression is evaluated at group-finalize time, BEFORE
the SELECT projection is emitted. False HAVING → skip the group's
output.

## GROUP BY / ORDER BY / HAVING name-resolution

This is where Phase 6aj + Phase 6cd (base-column-wins-on-alias-
shadow) live. Delegated fully to `parts/name-resolution/` — this
sub-part only passes the clause identity (GROUP BY / ORDER BY /
HAVING) as context so name-resolution can apply the correct
alias-visibility rule:

- **SELECT list**: aliases not yet visible (own list being
  constructed).
- **GROUP BY**: aliases visible; **base column wins on single-alias
  shadow collision** (Phase 6cd).
- **HAVING**: aliases visible; **base column wins on shadow** (same
  as GROUP BY). Aggregates legal.
- **ORDER BY**: aliases visible; **alias wins on shadow** (standard
  SQL: `ORDER BY <alias>` is the canonical idiom).

Name-resolution takes a `prefer_base_on_shadow: bool` flag per
clause identity. This sub-part passes it per the table above.

## Cross-sub-part invariants (enforced here)

- No aggregate function may appear inside another aggregate's
  argument. Compile-time check: walk aggregate args, raise
  `COMPILE_NESTED_AGGREGATE` on any nested AggregateCall.
- Every non-aggregate expression in the SELECT list of a GROUP BY
  query must either (a) be a bare column reference, or (b) appear
  textually equal to an item in GROUP BY. Rule (a) is Phase 6bo.
  Rule (b) is enforced via an "AST-equal" check.

## Phase pins owned here

- **Phase 6ai** — COUNT(DISTINCT) + MIN/MAX on strings.
- **Phase 6ap** — GROUP_CONCAT + TOTAL aggregates.
- **Phase 6bd** — SELECT ALL keyword (no-op at aggregate level).
- **Phase 6bo** — bare-column-in-GROUP-BY (non-standard SQLite
  permissive behavior).
- **Phase 6cd** — base-column-wins-on-alias-shadow (joint with
  name-resolution).
- **Phase 6bk** — WINDOW functions (related but delegated to
  `parts/window/`; aggregates calls into window compiler when it
  sees a WindowSpec).

## What this part does NOT do

- Resolve identifiers alone — delegates to name-resolution.
- Compile non-aggregate expressions — delegates to expressions.
- Run the aggregation — that is VDBE's opcodes-agg sub-part.
- Plan index use for group elimination — no cost-based
  optimization in v2.

## Regeneration envelope

- Target leaf size: 800–1200 lines per target.
- Spec size budget: this file < 400 lines.
- Test ownership: `tests/` holds per-aggregate-function fixtures and
  GROUP BY edge cases. Phase 6aj, 6bo, 6cd fixtures are primary
  here; cross-build fixtures naming this part run on regen.
