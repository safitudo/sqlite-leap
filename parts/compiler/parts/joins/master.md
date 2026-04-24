---
name: compiler/joins
kind: leaf
inherits:
  - /parts/compiler/parts/expressions/master.md
  - /parts/compiler/parts/name-resolution/master.md
  - /parts/vdbe/parts/opcodes-scan/master.md
emits:
  c: { path: src-c/compiler/joins.c, headers: [src-c/compiler/joins.h] }
  rust: { path: src-rust/src/compiler/joins.rs }
---

# Part: compiler/joins

Emits nested-loop join opcode sequences over two or more FROM
sources. Covers INNER, LEFT OUTER, CROSS, NATURAL, and USING joins.

## Public interface

```
compile_join_chain(
    sources:      &[FromSource<'src>],
    on_conditions: &[Expression<'src>],     // one per join-pair, NULL for CROSS
    join_kinds:   &[JoinKind],              // one per join-pair
    ctx:          &CompileContext,
    program_out:  &mut ProgramBuilder,
) -> Result<JoinPlan, CompileError>
```

Returns a `JoinPlan` describing:
- Cursor allocations per source.
- The generated scan-loop structure (outer cursor Rewind/Next,
  inner cursor(s) Rewind/Next per outer row).
- The WHERE / ON condition opcode sequence that filters per row
  combination.
- LEFT-OUTER null-filling branches (for unmatched outer rows).

## Join-kind semantics

- **INNER JOIN / JOIN** — cross-product filtered by ON condition.
  Only matching pairs emit.
- **LEFT [OUTER] JOIN** — like INNER, but if no inner row matches
  the outer, emit the outer with NULLs for the inner columns.
- **CROSS JOIN** — cross-product with no ON filter.
- **NATURAL JOIN** — equivalent to INNER JOIN with ON built from
  common column names. This sub-part desugars NATURAL at compile
  time into an ON list.
- **USING (col1, col2)** — equivalent to INNER JOIN ON
  `left.colN = right.colN AND ...`. Desugared here.

## Multi-way joins

Three-or-more-table joins emit left-deep nested loops by default:
`((a JOIN b) JOIN c)`. This matches SQLite's default shape. No
join reordering, no cost-based planning in v2.

## Phase pins

- **Phase 6ay** — 3+ way JOINs (multi-table).
- **Phase 6aq** — NATURAL JOIN + USING desugar.
- **Phase 6bo** — CROSS JOIN supported without ON condition.
- **Phase 6bq** — parenthesized FROM expressions (parser accepts;
  this sub-part flattens into the join chain).

## What this part does NOT own

- Index selection for the inner scan. For v2 the inner scan is
  always a full table scan unless the compiler's statement sub-part
  injects a different cursor kind. Cost-based index selection is
  out of scope.
- Join-order optimization. Statements land with the user-declared
  order.

## Regeneration envelope

- Target leaf size: 400–700 lines per target.
- Spec < 200 lines.
