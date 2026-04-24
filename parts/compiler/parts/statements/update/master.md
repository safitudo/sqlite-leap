---
name: compiler/statements/update
kind: leaf
inherits:
  - /parts/compiler/parts/expressions/master.md
  - /parts/compiler/parts/name-resolution/master.md
  - /parts/compiler/parts/constraints/master.md
  - /parts/compiler/parts/returning/master.md
emits:
  c: { path: src-c/compiler/statements/update.c, headers: [src-c/compiler/statements/update.h] }
  rust: { path: src-rust/src/compiler/statements/update.rs }
---

# Part: compiler/statements/update

Compiles `UPDATE table SET col = expr, ... [WHERE pred] [RETURNING]`.

## Public interface

```
compile_update(update, ctx, program_out) -> Result<(), CompileError>
```

## Pipeline

1. Open write cursor on target table.
2. Rewind cursor; for each row:
   - Evaluate WHERE (if present); skip if false.
   - Compute new values for assigned columns (compile each RHS
     expression). Unassigned columns retain old values.
   - Apply constraints (`parts/constraints/`).
   - Emit `UpdateRow(cursor, column_names, row_regs)`.
   - If RETURNING present → delegate to `parts/returning/`.
3. Close cursor.

## Duplicate-column rightmost-wins (Phase 2c-3)

If the SET list has a duplicate column, the rightmost value wins.
Non-rightmost value expressions are NOT evaluated (their side
effects are not triggered). Implementation: dedup the assignment
list left-to-right during compilation, keeping the rightmost
expression per column.

The SQL evidence for this behavior is R-34751-18293; it is
consistent with mainline SQLite.

## Phase pins

- **Phase 2c-3** — UPDATE duplicate-column rightmost-wins.
- **Phase 6bg** — RETURNING on UPDATE.

## Regeneration envelope

- Target leaf size: 400–600 lines per target.
- Spec < 100 lines.
