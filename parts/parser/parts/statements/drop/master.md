---
name: parser/statements/drop
kind: leaf
emits:
  c: { path: src-c/parser/statements/drop.c, headers: [src-c/parser/statements/drop.h] }
  rust: { path: src-rust/src/parser/statements/drop.rs }
---

# Part: parser/statements/drop

Parses DROP {TABLE | INDEX | VIEW} [IF EXISTS] name.

## Phase pins

- **Phase 6ak** — IF EXISTS.
- **Phase 9f** — DROP INDEX.

## Regeneration envelope

- Target leaf size: 50–100 lines per target.
- Spec < 30 lines.
