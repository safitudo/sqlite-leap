---
name: parser/statements/create-index
kind: leaf
inherits:
  - /parts/parser/parts/expressions/master.md
emits:
  c: { path: src-c/parser/statements/create_index.c, headers: [src-c/parser/statements/create_index.h] }
  rust: { path: src-rust/src/parser/statements/create_index.rs }
---

# Part: parser/statements/create-index

Parses CREATE [UNIQUE] INDEX [IF NOT EXISTS] name ON table (cols).

## Grammar

```
CreateIndex := CREATE [UNIQUE] INDEX [IF NOT EXISTS] name
               ON table (IndexedColumn (, IndexedColumn)*)
               [WHERE Expression]
IndexedColumn := (name | Expression) [COLLATE name] [ASC | DESC]
```

## Phase pins

- **Phase 6bb** — ASC/DESC in CREATE INDEX.

## Regeneration envelope

- Target leaf size: 100–200 lines per target.
- Spec < 50 lines.
