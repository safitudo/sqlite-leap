---
name: compiler/statements/delete
kind: leaf
inherits:
  - /parts/compiler/parts/expressions/master.md
  - /parts/compiler/parts/name-resolution/master.md
  - /parts/compiler/parts/returning/master.md
emits:
  c: { path: src-c/compiler/statements/delete.c, headers: [src-c/compiler/statements/delete.h] }
  rust: { path: src-rust/src/compiler/statements/delete.rs }
---

# Part: compiler/statements/delete

Compiles `DELETE FROM table [WHERE pred] [RETURNING]`.

## Public interface

```
compile_delete(delete, ctx, program_out) -> Result<(), CompileError>
```

## Pipeline

1. Open write cursor on target table.
2. Rewind cursor; for each row:
   - Evaluate WHERE (if present); skip if false.
   - If RETURNING: delegate to `parts/returning/` with
     `RowState::OldRow` BEFORE emitting DeleteRow.
   - Emit `DeleteRow(cursor)`.
3. Close cursor.

## Index maintenance

Any indexes on the table receive their own `DeleteRow` opcodes
generated per the constraints sub-part's index-maintenance rules
(Phase 9c).

## Phase pins

- **Phase 6bg** — RETURNING on DELETE.
- **Phase 9c** — DML maintenance keeps indexes live.

## Regeneration envelope

- Target leaf size: 200–400 lines per target.
- Spec < 80 lines.
