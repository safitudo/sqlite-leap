---
name: compiler/statements/select
kind: leaf
inherits:
  - /parts/compiler/parts/expressions/master.md
  - /parts/compiler/parts/name-resolution/master.md
  - /parts/compiler/parts/aggregates/master.md
  - /parts/compiler/parts/joins/master.md
  - /parts/compiler/parts/subqueries/master.md
  - /parts/compiler/parts/cte/master.md
  - /parts/compiler/parts/window/master.md
  - /parts/compiler/parts/views/master.md
emits:
  c: { path: src-c/compiler/statements/select.c, headers: [src-c/compiler/statements/select.h] }
  rust: { path: src-rust/src/compiler/statements/select.rs }
---

# Part: compiler/statements/select

Top-level compiler for `SELECT` and `VALUES` statements. Walks the
SelectCore, dispatches to feature sub-parts (joins, aggregates,
subqueries, CTEs, windows, views), and emits the scan+project+filter
pipeline.

## Public interface

```
compile_select(
    select:      &SelectCore<'src>,
    ctx:         &CompileContext,
    program_out: &mut ProgramBuilder,
) -> Result<(), CompileError>
```

## Pipeline

1. **CTE binding** — delegate `WITH` bindings to `parts/cte/`.
2. **Source compilation** — for each FROM source: open cursor
   (delegate JOIN chain to `parts/joins/`; expand views via
   `parts/views/`; materialize derived tables via
   `parts/subqueries/`).
3. **Aggregate detection** — if aggregate, delegate the entire
   scan+project to `parts/aggregates/`.
4. **Non-aggregate path:**
   - Emit the scan loop (outermost cursor Rewind/Next).
   - Emit WHERE filter (expression → JumpIfNot past ResultRow).
   - Emit projection (`parts/expressions/` for each SELECT-list
     item into result registers).
   - Emit `ResultRow(start, count)`.
5. **DISTINCT** — if DISTINCT, wrap step 4 in a dedup buffer
   (sort+unique or hash set).
6. **Compound operators** — UNION, UNION ALL, INTERSECT, EXCEPT:
   compile each branch, concatenate and optionally dedup.
7. **ORDER BY** — if present, buffer all result rows and sort
   before emission.
8. **LIMIT / OFFSET** — gate emission count and skip.

## Phase pins

- **Phase 6ba** — positional ORDER BY + SELECT * + ORDER BY N
  (Rust fix #84).
- **Phase 6as** — UNION ALL with heterogeneous column types.
- **Phase 6bp** — no-FROM SELECT (`SELECT 1+1`).
- **Phase 6bd** — SELECT ALL keyword (explicit non-DISTINCT).
- **Phase 6ax** — sqlite_master / sqlite_schema introspection.

## Regeneration envelope

- Target leaf size: 800–1200 lines per target.
- Spec < 200 lines.
