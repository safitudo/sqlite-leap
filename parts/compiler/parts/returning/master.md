---
name: compiler/returning
kind: leaf
inherits:
  - /parts/compiler/parts/expressions/master.md
  - /parts/compiler/parts/name-resolution/master.md
emits:
  c: { path: src-c/compiler/returning.c, headers: [src-c/compiler/returning.h] }
  rust: { path: src-rust/src/compiler/returning.rs }
---

# Part: compiler/returning

Compiles the `RETURNING` clause of INSERT / UPDATE / DELETE
statements. After each row is inserted / updated / deleted, emit
projections from the new row (INSERT/UPDATE) or the old row
(DELETE).

## Public interface

```
compile_returning(
    returning:     &ReturningClause<'src>,
    row_state:     RowState,           // NewRow | OldRow
    ctx:           &CompileContext,
    program_out:   &mut ProgramBuilder,
) -> Result<(), CompileError>
```

Called by the owning DML statement sub-part after it emits the
row-level opcode (InsertRow / UpdateRow / DeleteRow).

## Projection semantics

- `RETURNING *` expands to all columns of the target table.
- `RETURNING expr [, expr ...]` projects each expression per row.
- Aliases in the RETURNING list are legal (`RETURNING col AS x`).
- Expressions may reference any column of the target table. They
  may NOT reference unrelated tables — the name scope is restricted
  to the DML target.

## RowState meaning

- `NewRow` (INSERT, UPDATE) — projections read the post-operation
  row state. A newly inserted row reads its inserted values;
  UPDATE reads post-update values.
- `OldRow` (DELETE) — projections read the pre-deletion state of
  the row being removed.

## Phase pins

- **Phase 6bg** — RETURNING clause on INSERT/UPDATE/DELETE.

## Regeneration envelope

- Target leaf size: 200–400 lines per target.
- Spec < 100 lines.
