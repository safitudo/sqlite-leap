---
name: compiler/statements/create-view
kind: leaf
inherits:
  - /parts/compiler/parts/statements/select/master.md
  - /parts/storage/master.md
emits:
  c: { path: src-c/compiler/statements/create_view.c, headers: [src-c/compiler/statements/create_view.h] }
  rust: { path: src-rust/src/compiler/statements/create_view.rs }
---

# Part: compiler/statements/create-view

Compiles `CREATE [TEMPORARY] VIEW [IF NOT EXISTS] name [(cols)] AS SELECT ...`.

## Pipeline

1. Validate the inner SELECT compiles cleanly (drop compiled
   program; we only need to confirm legality — view body is stored
   as text).
2. Compute column names: either from the `(cols)` list if given,
   or from the inner SELECT's projection.
3. Emit `CreateView` opcode carrying `{name, column_names,
   sql_text}`.

The view's SELECT is NOT pre-compiled at CREATE time. Expansion
happens at each reference, via `parts/compiler/parts/views/`.

## Phase pins

- **Phase 6ac** — CREATE VIEW / DROP VIEW.

## Regeneration envelope

- Target leaf size: 100–200 lines per target.
- Spec < 60 lines.
