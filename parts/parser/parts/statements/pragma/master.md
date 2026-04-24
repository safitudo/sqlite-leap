---
name: parser/statements/pragma
kind: leaf
inherits:
  - /parts/parser/parts/expressions/master.md
emits:
  c: { path: src-c/parser/statements/pragma.c, headers: [src-c/parser/statements/pragma.h] }
  rust: { path: src-rust/src/parser/statements/pragma.rs }
---

# Part: parser/statements/pragma

Parses PRAGMA name [= value | (arg)].

## Grammar

```
Pragma := PRAGMA [schema.] name [= Expression | ( Expression )]
```

## Phase pins

- **Phase 6aw** — PRAGMA core subset (shared with compiler).

## Regeneration envelope

- Target leaf size: 50–100 lines per target.
- Spec < 30 lines.
