---
name: compiler/cte
kind: leaf
inherits:
  - /parts/compiler/parts/expressions/master.md
  - /parts/compiler/parts/name-resolution/master.md
  - /parts/compiler/parts/statements/select/master.md
  - /parts/vdbe/parts/opcodes-rows/master.md
emits:
  c: { path: src-c/compiler/cte.c, headers: [src-c/compiler/cte.h] }
  rust: { path: src-rust/src/compiler/cte.rs }
---

# Part: compiler/cte

Compiles `WITH` and `WITH RECURSIVE` bindings. Non-recursive CTEs
are compiled as derived tables materialized once per statement.
Recursive CTEs use an iterative materialization with a UNION
[ALL] accumulator.

## Public interface

```
bind_cte(
    cte:         &CteBinding<'src>,
    scope:       &mut NameScope<'src>,
    ctx:         &CompileContext,
    program_out: &mut ProgramBuilder,
) -> Result<(), CompileError>
```

After binding, downstream statement compilation sees the CTE as an
additional named source in its NameScope.

## Non-recursive CTE (WITH name AS (SELECT ...))

1. Compile the inner SELECT into its own Program (or opcode
   sub-sequence with a materialization buffer).
2. Register the CTE name + column list in NameScope.
3. Downstream references resolve as FROM-source references and
   drive a cursor over the materialized buffer.

## Recursive CTE (WITH RECURSIVE name(cols) AS (base UNION [ALL] recursive))

1. Compile the base case. Emit its rows into the accumulator.
2. Compile the recursive case, which may reference `name` itself.
   The reference to `name` inside the recursive body scans the
   accumulator's current contents.
3. Iterate: on each pass, compute new rows from the recursive
   body; add to accumulator (UNION deduplication or UNION ALL
   append); stop when no new rows are produced.
4. An iteration-limit safeguard raises
   `RUNTIME_RECURSIVE_CTE_LIMIT` if the bound is exceeded. Bound
   is configurable via a compile-time constant; default `1_000_000`
   rows.

## Self-reference detection

A WITH RECURSIVE body that references the CTE name in a position
that would dispatch without the recursion structure (e.g., inside
a scalar expression without the UNION structure) is ill-formed.
Detection: walk the recursive side's AST; if `name` appears outside
the UNION's right arm, raise `COMPILE_RECURSIVE_CTE_MALFORMED`.

The engine side also detects runtime self-reference cycles via the
`ast_references_name` helper; on cycle detection with no progress,
raises `RUNTIME_RECURSIVE_CTE_LIMIT`. This is the Phase 9h-related
runtime pin (CTE part).

## Phase pins

- **Phase 6aa** — non-recursive CTEs.
- **Phase 6bl** — WITH RECURSIVE CTE.

## Regeneration envelope

- Target leaf size: 400–600 lines per target.
- Spec < 200 lines.
