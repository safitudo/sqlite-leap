---
name: parser/statements/update
kind: leaf
inherits:
  - /parts/parser/parts/expressions/master.md
  - /parts/parser/parts/clauses/master.md
emits:
  c: { path: src-c/parser/statements/update.c, headers: [src-c/parser/statements/update.h] }
  rust: { path: src-rust/src/parser/statements/update.rs }
---

# Part: parser/statements/update

Parses UPDATE [OR ConflictStrategy] table SET ... [WHERE] [RETURNING].

## Grammar

```
Update := [WITH ...] UPDATE [OR ConflictStrategy] table
          SET AssignmentList
          [FROM FromSource]
          [WHERE Expression]
          [RETURNING ReturningList]
```

## Assignment list

Column names may repeat; duplicate handling is a compiler concern
(Phase 2c-3 rightmost-wins). The parser accepts duplicates and
preserves source order.

## Phase pins

- **Phase 6bg** — RETURNING.
- Phase 2c-3 — parser accepts duplicates; rightmost-wins dedup is
  in compiler/statements/update.

## Regeneration envelope

- Target leaf size: 150–250 lines per target.
- Spec < 60 lines.
