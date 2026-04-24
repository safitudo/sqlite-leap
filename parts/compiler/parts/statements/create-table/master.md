---
name: compiler/statements/create-table
kind: leaf
inherits:
  - /parts/compiler/parts/expressions/master.md
  - /parts/storage/master.md
emits:
  c: { path: src-c/compiler/statements/create_table.c, headers: [src-c/compiler/statements/create_table.h] }
  rust: { path: src-rust/src/compiler/statements/create_table.rs }
---

# Part: compiler/statements/create-table

Compiles `CREATE TABLE [IF NOT EXISTS] name (col_defs, table_constraints)`.

## Pipeline

1. Validate uniqueness: if IF NOT EXISTS, no-op on existing table.
   Otherwise, raise `STORAGE_DUPLICATE_TABLE`.
2. Parse column defs: name, type (affinity), per-column
   constraints (NOT NULL, DEFAULT, PRIMARY KEY, UNIQUE, CHECK,
   GENERATED).
3. Parse table-level constraints (Phase 6au).
4. Emit `CreateTable` opcode carrying the full schema payload.
5. If `INTEGER PRIMARY KEY AUTOINCREMENT` (Phase 6ar): mark for
   autoinc tracking, emit sqlite_sequence maintenance.
6. If `STRICT` (Phase 6bi): mark table as strict.

## Phase pins

- **Phase 6al** — DEFAULT expressions in CREATE TABLE.
- **Phase 6am** — NOT NULL column constraints.
- **Phase 6at** — CHECK constraints.
- **Phase 6au** — multi-column table-level constraints.
- **Phase 6ar** — INTEGER PRIMARY KEY AUTOINCREMENT.
- **Phase 6bi** — STRICT tables.
- **Phase 6bj** — GENERATED virtual columns.

## Regeneration envelope

- Target leaf size: 400–600 lines per target.
- Spec < 100 lines.
