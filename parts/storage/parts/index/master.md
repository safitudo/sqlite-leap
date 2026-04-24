---
name: storage/index
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /parts/core/master.md
  - /parts/storage/master.md
  - /parts/storage/parts/btree/master.md
  - /parts/storage/parts/file-format/master.md
emits:
  c:    { path: src-c-v2/storage/index.c, headers: [src-c-v2/storage/index.h] }
  rust: { path: src-rust-v2/storage/index.rs }
---

# Part: storage/index

Index management: creation, per-row maintenance on DML, uniqueness
enforcement, and the **VDBE-facing index cursor surface** consumed
by `parts/vdbe/parts/opcodes-scan/`.

## Schema operations

```
fn index_create(db, table, name, columns, unique) -> Result<IndexHandle, StorageCondition>
fn index_drop(db, name) -> Result<(), StorageCondition>
```

## Per-row maintenance (called from DML opcodes)

```
fn index_insert(db, idx, key_tuple, rowid) -> Result<(), StorageCondition>
fn index_delete(db, idx, key_tuple, rowid) -> Result<(), StorageCondition>
```

Unique-index `index_insert` on duplicate key returns
`STORAGE_CONSTRAINT_UNIQUE`, which the VDBE wraps as
`RuntimeCondition::ConstraintUnique`.

## VDBE index-cursor surface (canonical)

These are the functions `parts/vdbe/parts/opcodes-scan/` calls to
drive `OpenIdxRead`, `SeekGE`/`SeekGT`/`SeekLE`/`SeekLT`, `IdxNext`,
`IdxRowid`. Both emissions must match these signatures exactly.

### Rust

```rust
use crate::core::{Value, RuntimeCondition};
use crate::storage::CursorHandle;

/// Open a read-only cursor on an index by name.
/// On missing index: RuntimeCondition::TableNotFound (shared with table
/// miss; see parts/core/master.md § RuntimeCondition note — v2 does
/// NOT introduce IndexNotFound).
pub fn open_index_cursor(
    db: &crate::storage::Database,
    index_name: &str,
) -> Result<CursorHandle, RuntimeCondition>;

/// Seek to the first index entry >= / > / <= / < key.
/// Returns Ok(true) if such an entry exists; Ok(false) if the cursor
/// ends up past the edge (caller interprets as "miss" → jump).
pub fn cursor_seek_ge(cursor: &mut CursorHandle, key: &Value) -> Result<bool, RuntimeCondition>;
pub fn cursor_seek_gt(cursor: &mut CursorHandle, key: &Value) -> Result<bool, RuntimeCondition>;
pub fn cursor_seek_le(cursor: &mut CursorHandle, key: &Value) -> Result<bool, RuntimeCondition>;
pub fn cursor_seek_lt(cursor: &mut CursorHandle, key: &Value) -> Result<bool, RuntimeCondition>;

/// Advance an index cursor. Ok(true) if a new entry exists,
/// Ok(false) at end-of-scan. Direction implicit from last seek.
pub fn cursor_idx_next(cursor: &mut CursorHandle) -> Result<bool, RuntimeCondition>;

/// Read the rowid associated with the current index entry.
/// Err(CursorClosed) if cursor is past-end or closed.
pub fn cursor_idx_rowid(cursor: &CursorHandle) -> Result<i64, RuntimeCondition>;
```

### C

```c
LeapRuntimeCondition leap_storage_open_index_cursor(
    LeapDatabase* db,
    const char* index_name, size_t index_name_len,
    LeapCursor** out_cursor
);

LeapRuntimeCondition leap_storage_cursor_seek_ge(LeapCursor*, const LeapValue* key, bool* out_found);
LeapRuntimeCondition leap_storage_cursor_seek_gt(LeapCursor*, const LeapValue* key, bool* out_found);
LeapRuntimeCondition leap_storage_cursor_seek_le(LeapCursor*, const LeapValue* key, bool* out_found);
LeapRuntimeCondition leap_storage_cursor_seek_lt(LeapCursor*, const LeapValue* key, bool* out_found);

LeapRuntimeCondition leap_storage_cursor_idx_next (LeapCursor*, bool* out_has_more);
LeapRuntimeCondition leap_storage_cursor_idx_rowid(const LeapCursor*, int64_t* out_rowid);
```

## PRIMARY KEY auto-index

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
- Spec < 200 lines.
