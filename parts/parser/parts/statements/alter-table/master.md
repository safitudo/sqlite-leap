---
name: parser/statements/alter-table
kind: leaf
inherits:
  - /parts/parser/parts/statements/create-table/master.md
emits:
  c: { path: src-c/parser/statements/alter_table.c, headers: [src-c/parser/statements/alter_table.h] }
  rust: { path: src-rust/src/parser/statements/alter_table.rs }
---

# Part: parser/statements/alter-table

Parses ALTER TABLE table {RENAME TO name | RENAME [COLUMN] old TO new | ADD [COLUMN] ColumnDef}.

## Phase pins

- **Phase 6bf** — ALTER TABLE subset.

## Regeneration envelope

- Target leaf size: 80–150 lines per target.
- Spec < 40 lines.
