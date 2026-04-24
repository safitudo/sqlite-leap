---
name: compiler/statements/create-index
kind: leaf
inherits:
  - /parts/storage/master.md
emits:
  c: { path: src-c/compiler/statements/create_index.c, headers: [src-c/compiler/statements/create_index.h] }
  rust: { path: src-rust/src/compiler/statements/create_index.rs }
---

# Part: compiler/statements/create-index

Compiles `CREATE [UNIQUE] INDEX [IF NOT EXISTS] name ON table (col [ASC|DESC], ...)`.

## Pipeline

1. Validate: index name not already present; target table exists.
2. Parse column list; each column has an optional ASC/DESC
   (Phase 6bb).
3. Emit `CreateIndex` opcode carrying `{name, table, columns,
   unique}`.
4. Iterate all existing rows of the target table, inserting each
   into the new index (initial population).

## Phase pins

- **Phase 6bb** — ASC/DESC in CREATE INDEX.
- **Phase 9f** — PRIMARY KEY auto-index.
- **Phase 9g** — UNIQUE enforcement (initial population must also
  check).

## Regeneration envelope

- Target leaf size: 200–400 lines per target.
- Spec < 80 lines.
