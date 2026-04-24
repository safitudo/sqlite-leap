---
name: parser/statements/create-view
kind: leaf
inherits:
  - /parts/parser/parts/statements/select/master.md
emits:
  c: { path: src-c/parser/statements/create_view.c, headers: [src-c/parser/statements/create_view.h] }
  rust: { path: src-rust/src/parser/statements/create_view.rs }
---

# Part: parser/statements/create-view

Parses CREATE [TEMPORARY] VIEW [IF NOT EXISTS] name [(cols)] AS SelectStatement.

## Phase pins

- **Phase 6ac** — CREATE VIEW / DROP VIEW.

## Regeneration envelope

- Target leaf size: 80–150 lines per target.
- Spec < 40 lines.
