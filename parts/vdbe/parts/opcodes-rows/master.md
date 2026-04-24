---
name: vdbe/opcodes-rows
kind: leaf
inherits:
  - /schema/opcode.schema.json
  - /schema/value.schema.json
  - /parts/storage/master.md
  - /parts/vdbe/parts/opcodes-core/master.md
emits:
  c: { path: src-c/vdbe/opcodes_rows.c, headers: [src-c/vdbe/opcodes_rows.h] }
  rust: { path: src-rust/src/vdbe/opcodes_rows.rs }
---

# Part: vdbe/opcodes-rows

Row-level cursor operations: insert, update, delete, column read,
position stepping.

## Opcodes owned here

| Name | Semantics |
|---|---|
| `InsertRow(cursor, column_names, start, count)` | Insert row `regs[start..start+count]` into the cursor's table under the given column names. `column_names = null` means positional. On UNIQUE violation: `RUNTIME_CONSTRAINT_UNIQUE` (unless conflict resolution says otherwise). |
| `UpdateRow(cursor, column_names, row_regs)` | Update the cursor's current row — only the columns listed in `column_names` take new values from `row_regs`. Unlisted columns retain their existing values. `column_names` is ALWAYS pre-deduplicated by the compiler (Phase 2c-3). |
| `DeleteRow(cursor)` | Delete the cursor's current row. Cursor advances to next row. |
| `Column(cursor, col_idx, dest_reg)` | Read column `col_idx` of the cursor's current row into `regs[dest_reg]`. |
| `Rewind(cursor)` | Move cursor to first row (or EOF marker if empty). |
| `Next(cursor, jump_if_eof)` | Advance cursor; if past last row, jump to `jump_if_eof`. |
| `Prev(cursor, jump_if_eof)` | Reverse of Next. |
| `SeekRowid(cursor, rowid_reg, jump_if_miss)` | Position cursor at rowid; jump to miss branch if not found. |

## Invariants

- Cursor must be open before any row op (validated by compiler).
- `InsertRow` on a read-only cursor → `RUNTIME_CURSOR_NOT_WRITABLE`.
- `Column` reads after Rewind without any Next may yield the first
  row or EOF depending on whether the table is empty — callers
  must check EOF state first (via the Next-returned branch logic).

## Constraint emission

Constraint violations during `InsertRow` / `UpdateRow` route to:

- `RUNTIME_CONSTRAINT_NOT_NULL` — NOT NULL column has NULL value.
- `RUNTIME_CONSTRAINT_UNIQUE` — UNIQUE index probe hit.
- `RUNTIME_CONSTRAINT_CHECK` — CHECK expression false.
- `RUNTIME_CONSTRAINT_TYPE` — STRICT table type mismatch.

## Regeneration envelope

- Target leaf size: 400–600 lines per target.
- Spec < 150 lines.
