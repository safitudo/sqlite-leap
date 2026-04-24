---
name: parser/statements/delete
kind: leaf
inherits:
  - /parts/parser/parts/expressions/master.md
  - /parts/parser/parts/clauses/master.md
emits:
  c: { path: src-c/parser/statements/delete.c, headers: [src-c/parser/statements/delete.h] }
  rust: { path: src-rust/src/parser/statements/delete.rs }
---

# Part: parser/statements/delete

Parses DELETE FROM table [WHERE] [RETURNING].

## Grammar

```
Delete := [WITH ...] DELETE FROM table
          [WHERE Expression]
          [RETURNING ReturningList]
```

## Phase pins

- **Phase 6bg** — RETURNING.

## Regeneration envelope

- Target leaf size: 100–200 lines per target.
- Spec < 50 lines.
