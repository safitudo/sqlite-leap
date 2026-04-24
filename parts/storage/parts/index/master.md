---
name: storage/index
kind: leaf
inherits:
  - /parts/storage/parts/btree/master.md
  - /parts/storage/parts/file-format/master.md
emits:
  c: { path: src-c/storage/index.c, headers: [src-c/storage/index.h] }
  rust: { path: src-rust/src/storage/index.rs }
---

# Part: storage/index

Index management: creation, per-row maintenance on DML, uniqueness
enforcement at index probe time.

## Public interface

```
fn index_create(table, name, columns, unique) -> Result<IndexHandle>
fn index_drop(name) -> Result<()>
fn index_insert(idx, key_tuple, rowid) -> Result<()>
fn index_delete(idx, key_tuple, rowid) -> Result<()>
fn index_seek(idx, key_tuple) -> Result<Option<Cursor>>
fn index_scan(idx, range, direction) -> Cursor
```

## Maintenance on DML (Phase 9c)

Every `InsertRow` / `UpdateRow` / `DeleteRow` on a table updates
all indexes on that table. The compiler emits the maintenance
opcodes; this sub-part implements the storage-side primitives.

## Unique enforcement (Phase 9g)

`index_insert` on a unique index raises `RUNTIME_CONSTRAINT_UNIQUE`
on duplicate key. Compiler handles the conflict-resolution
strategy (ABORT / IGNORE / REPLACE).

## PRIMARY KEY auto-index (Phase 9f)

Non-INTEGER PRIMARY KEY implicitly creates a unique index named
`sqlite_autoindex_<table>_1`. INTEGER PRIMARY KEY is aliased to
the rowid; no separate index is created.

## Phase pins

- **Phase 9c** — DML maintenance keeps indexes live.
- **Phase 9f** — PRIMARY KEY auto-index + DROP INDEX.
- **Phase 9g** — UNIQUE enforcement.
- **Phase 6bb** — ASC/DESC in CREATE INDEX affects scan direction.

## Regeneration envelope

- Target leaf size: 400–700 lines per target.
- Spec < 150 lines.
