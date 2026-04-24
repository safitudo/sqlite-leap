---
name: parser/statements/insert
kind: leaf
inherits:
  - /parts/parser/parts/expressions/master.md
  - /parts/parser/parts/clauses/master.md
emits:
  c: { path: src-c/parser/statements/insert.c, headers: [src-c/parser/statements/insert.h] }
  rust: { path: src-rust/src/parser/statements/insert.rs }
---

# Part: parser/statements/insert

Parses INSERT / REPLACE / INSERT OR {...} INTO.

## Grammar

```
Insert := [WITH ...] (INSERT [OR ConflictStrategy] | REPLACE)
          INTO table [(column_list)]
          InsertSource
          [ON CONFLICT (col_list) DO {NOTHING | UPDATE SET ...}]
          [RETURNING ReturningList]

InsertSource := VALUES (tuple)(, tuple)*
             | DEFAULT VALUES
             | select
```

## Phase pins

- **Phase 6w** — multi-row INSERT VALUES.
- **Phase 6ab** — INSERT OR REPLACE / OR IGNORE (syntax).
- **Phase 6be** — INSERT INTO SELECT.
- **Phase 6bg** — RETURNING.
- **Phase 6bh** — ON CONFLICT / UPSERT syntax.
- **Phase 6al** — INSERT DEFAULT VALUES.

## Regeneration envelope

- Target leaf size: 250–400 lines per target.
- Spec < 80 lines.
