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

## Scalar-context dispatch (FROM-topology coverage)

The "scalar-context aggregate" trigger — projection or HAVING
contains an aggregate call when GROUP BY is absent — MUST be
detected and routed to the single-group aggregate path on every
FROM topology the compiler accepts for non-aggregate SELECT. That
includes, at minimum:

- **No FROM** — `SELECT COUNT(*)`, `SELECT MAX(5)`. Synthetic
  single empty-group; `AggReset` → `AggFinal` yields the per-kind
  empty-group value (Count* → 0, Sum/Avg/Min/Max/GroupConcat →
  Null, Total → Real(0.0)).
- **Single named table** — `SELECT COUNT(*) FROM t`.
- **Joined sources (CROSS / INNER / explicit ON / USING)** —
  `SELECT COUNT(*) FROM t1 CROSS JOIN t2`. Scan emission is the
  same nested-loop topology as a non-aggregate JOIN, but with
  `AggStep` at the innermost loop body and one post-loop
  `AggFinal` + projection + `ResultRow` (single output row).
- **Derived-table / CTE / view-materialized FROM** — the buffered
  outer compiler treats the materialized source as an opaque
  cursor and applies the same single-group dispatch.

Detection is a pre-walk of projection + HAVING for any
`AggregateCall`; if found (and GROUP BY is empty), aggregate-mode
is selected before the non-aggregate row-by-row path is entered.
**No expression-compiler walker may emit a runtime row for an
aggregate call** — every reachable dispatch site (single-table
walker, JOIN multi-source walker, derived-source walker, no-FROM
walker) must either (a) route to an aggregate-aware compile path,
or (b) surface `AGGREGATE_IN_SCALAR_CONTEXT` so the parent SELECT
compiler can re-route. Targets that omit the dispatch fork on any
of these topologies leak the routing condition out as a runtime
DEFER, which is a spec-conformance failure, not a feature gap.

## Bare column in GROUP BY

`SELECT a, COUNT(*) FROM t GROUP BY a` — `a` is a "bare column,"
resolved to the same column that appears in GROUP BY.

`SELECT a, b, COUNT(*) FROM t GROUP BY a` — `b` is a bare column
NOT in GROUP BY. SQLite's permissive behavior: `b` takes the value
from an arbitrary row in the group (first or last row). Phase 6bo
owner: emit `Column` reading from the cursor state at group-finalize
time. This is non-standard SQL but matches SQLite.

### Phase 6bo* — star-in-aggregate projection (regen-safe)

`SELECT *, COUNT(*) FROM t` and `SELECT * FROM t GROUP BY ...`
are well-formed in SQLite. `*` (and `t.*`) expand to the table's
column list at compile time, **before** the aggregate compiler
classifies projection items. After expansion, each expanded
`Expr::Col` is processed by the same rule as any other bare-
column projection:

- If the column is textually equal to a GROUP BY expression: it
  resolves to the grouping key (legal under standard SQL).
- Otherwise: it is a bare-non-grouped column and follows the
  Phase 6bo rule above (value from arbitrary row in the group).
- For an implicit single-group aggregate (no GROUP BY): all
  expanded columns follow the Phase 6bo rule for the single
  group (value from an arbitrary row across the whole table).

The expansion is performed by the same helper that the non-
aggregate SELECT compiler uses (the projection-expand helper
that maps `Star`/`TableStar` to `[Expr::Col {table: None, name}]`
for each schema column). Targets MUST run star expansion at the
top of the aggregate compile path — before classifying projection
items as `Star` vs `Expr` — so that the Star case is unreachable
inside the aggregate dispatch. Emitting `deferred: star projection
in aggregate query` from any aggregate compile fork is a
spec-conformance failure (no separate dispatch needed).

For aggregate JOIN topology, the same expansion applies: `*`
expands to the concatenation of all sources' columns in source
order; `t.*` expands to that single source's columns. Same Phase
6bo rule for non-grouped columns.

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

**Pin 35 — closed enumeration of DISTINCT-aggregated kinds.** Per
SQLite (sqlite.org/lang_aggfunc.html): "in any aggregate function
that takes a single argument, that argument can be preceded by
the keyword DISTINCT." The closed enumeration here therefore
covers all single-argument aggregates:

```
{count_distinct, sum_distinct, total_distinct,
 avg_distinct, min_distinct, max_distinct,
 group_concat_distinct}
```

`group_concat_distinct` is the 1-arg form only (SQLite disallows
the custom-separator 2-arg form with DISTINCT; raise parser error
"DISTINCT call argument must be a single expression" when
`group_concat(DISTINCT a, sep)` is encountered).

Step semantics (uniform across the enumeration): per-slot
distinct-set gate; on first observation insert into set and
delegate to the base accumulator's step (`sum`, `total`, `avg`,
`min`, `max`, `group_concat`); on repeat observation, no-op. Set
is reset on group change. Finalize is identical to the base kind.

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

  **Pin (AST-equal qualifier rule).** For column references, an
  absent table-qualifier on either side is a wildcard match: bare
  `col0` AST-equals `t.col0` and vice versa, as long as the column
  names are equal (case-insensitively). Two qualified refs match
  only when the qualifiers are equal (case-insensitively).
  Rationale: SQL bare-column references resolve against the FROM
  clause; for GROUP-BY-key matching, `t.col0` and bare `col0` (or
  `cor0.col0` and `col0`) refer to the same expression because
  multi-source ambiguity is already rejected by column resolution
  before this rewrite runs. Targets that compare AST nodes by
  strict (qualifier-present-on-both-or-neither) equality silently
  drop the projection-side rewrite, leaving non-grouped column
  paths active for what is actually a group-key expression — the
  surface symptom is unary minus / arithmetic dropped from
  projections like `- cor0.col0 * col0` over `GROUP BY cor0.col0`.
- **Scalar-dispatch routing invariant.** Every scalar-function
  dispatch site (in any expression compiler — projection, WHERE,
  HAVING, ORDER BY, scalar-subquery, no-FROM SELECT, derived
  contexts) MUST first check the closed aggregate-name set above
  before consulting the scalar-function table. If the call name
  matches an aggregate, the dispatch MUST surface the routing
  condition `AGGREGATE_IN_SCALAR_CONTEXT` (one diagnostic bucket,
  not "unknown function"). Callers that have access to an aggregate
  evaluator route to it; callers that do not (e.g. a context-free
  expression compiler) defer with the routing-aware condition so
  the parent SELECT compiler can re-route. Rationale: keeps every
  dispatch site in agreement on the closed enumeration and prevents
  aggregate names from leaking into scalar-function diagnostics.

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
