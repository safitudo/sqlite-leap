---
name: compiler/statements/insert
kind: leaf
inherits:
  - /parts/compiler/parts/expressions/master.md
  - /parts/compiler/parts/name-resolution/master.md
  - /parts/compiler/parts/constraints/master.md
  - /parts/compiler/parts/upsert/master.md
  - /parts/compiler/parts/returning/master.md
  - /parts/compiler/parts/statements/select/master.md
emits:
  c: { path: src-c/compiler/statements/insert.c, headers: [src-c/compiler/statements/insert.h] }
  rust: { path: src-rust/src/compiler/statements/insert.rs }
---

# Part: compiler/statements/insert

Compiles `INSERT INTO table [(cols)] VALUES (...) | SELECT ...`.
Also handles `REPLACE INTO`, `INSERT OR {REPLACE|IGNORE|ABORT|FAIL|ROLLBACK}`.

## Public interface

```
compile_insert(insert, ctx, program_out) -> Result<(), CompileError>
```

## Pipeline

1. Open write cursor on target table.
2. If source is `VALUES`: for each tuple, compile values into row
   registers. For multi-row (Phase 6w), loop.
3. If source is `SELECT`: compile inner SELECT; for each output
   row, copy into row registers.
4. Apply constraints (`parts/constraints/`).
5. Emit `InsertRow` with column_names metadata.
6. If ON CONFLICT present → delegate to `parts/upsert/`.
7. If RETURNING present → delegate to `parts/returning/`.
8. Close cursor. Halt.

## Duplicate-column handling

INSERT with a duplicate column in the column list → compile-time
`STORAGE_DUPLICATE_COLUMN` (mirrors mainline; preferred over
runtime detection).

## Phase pins

- **Phase 6w** — multi-row INSERT VALUES.
- **Phase 6ab** — INSERT OR REPLACE / OR IGNORE.
- **Phase 6be** — INSERT INTO SELECT.
- **Phase 6al** — DEFAULT in CREATE TABLE + INSERT DEFAULT VALUES.

## Regeneration envelope

- Target leaf size: 400–600 lines per target.
- Spec < 100 lines.
