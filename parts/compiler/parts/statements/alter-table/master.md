---
name: compiler/statements/alter-table
kind: leaf
inherits:
  - /parts/storage/master.md
emits:
  c: { path: src-c/compiler/statements/alter_table.c, headers: [src-c/compiler/statements/alter_table.h] }
  rust: { path: src-rust/src/compiler/statements/alter_table.rs }
---

# Part: compiler/statements/alter-table

Compiles `ALTER TABLE table { RENAME TO newname | RENAME COLUMN old TO new | ADD COLUMN colDef }`.

## Supported operations (Phase 6bf subset)

- **RENAME TABLE** — update the table's schema entry.
- **RENAME COLUMN** — update the column name in the schema; update
  any indexes/views referring to it (within scope; view text is
  NOT automatically rewritten — consistent with mainline SQLite
  legacy behavior).
- **ADD COLUMN** — append a new column to the schema with optional
  DEFAULT. Existing rows acquire the default (or NULL if none).

## Out of scope for v2

- DROP COLUMN
- Column type change
- Dropping/adding constraints after creation (for anything beyond
  the column-level defaults noted above)

## Phase pins

- **Phase 6bf** — ALTER TABLE subset (RENAME TABLE, RENAME COLUMN,
  ADD COLUMN).

## Regeneration envelope

- Target leaf size: 200–400 lines per target.
- Spec < 80 lines.
