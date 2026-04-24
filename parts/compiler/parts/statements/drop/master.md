---
name: compiler/statements/drop
kind: leaf
inherits:
  - /parts/storage/master.md
emits:
  c: { path: src-c/compiler/statements/drop.c, headers: [src-c/compiler/statements/drop.h] }
  rust: { path: src-rust/src/compiler/statements/drop.rs }
---

# Part: compiler/statements/drop

Compiles `DROP TABLE | DROP INDEX | DROP VIEW [IF EXISTS] name`.

## Pipeline

1. Resolve name in storage.
2. If not found:
   - With `IF EXISTS`: no-op, halt.
   - Without: raise `STORAGE_TABLE_NOT_FOUND` / `STORAGE_INDEX_NOT_FOUND`
     / `STORAGE_VIEW_NOT_FOUND`.
3. Emit the matching drop opcode (`DropTable`, `DropIndex`,
   `DropView`).
4. Cascade: DROP TABLE cascades to its indexes (Phase 9f) and
   views referencing it (view cascade is a future item; v2
   currently leaves referencing views broken).

## Phase pins

- **Phase 6ak** — DROP TABLE/INDEX IF EXISTS.
- **Phase 9f** — DROP INDEX.

## Regeneration envelope

- Target leaf size: 150–300 lines per target.
- Spec < 60 lines.
