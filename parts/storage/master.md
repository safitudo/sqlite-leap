---
name: storage
kind: inner
inherits:
  - /spec/memory-discipline.spec.md
  - /spec/durability.spec.md
  - /schema/value.schema.json
  - /parts/core/master.md
  - /parts/io-backend/master.md
emits:
  c:
    path: src-c-v2/storage/mod.h
  rust:
    path: src-rust-v2/storage/mod.rs
---

# Part: storage

The on-disk storage engine. Absorbs v1's `storage.spec.md`,
`file-format.spec.md`, `wal.spec.md`, `pager-async.spec.md`, and
related phase pins into five sub-parts. Storage is **inner**.

## Public interface

`Database` is the storage facade. It exposes:

- **Schema operations:** `create_table`, `drop_table`, `create_index`,
  `drop_index`, `alter_table`.
- **Row operations:** `insert_row`, `update_row`, `delete_row`,
  `scan_table` (cursor), `scan_index` (cursor), `seek_rowid`,
  `seek_index`.
- **Schema introspection:** `table_schema(name)`, `index_schema`,
  `list_tables`.
- **Transactional boundary:** `begin`, `commit`, `rollback`,
  `checkpoint` (WAL).
- **File lifecycle:** `open(path)`, `close`. In-memory DB is
  `open(":memory:")`.

Each operation returns success or a named storage condition:

- `STORAGE_TABLE_NOT_FOUND`, `STORAGE_COLUMN_NOT_FOUND`,
  `STORAGE_DUPLICATE_TABLE`, `STORAGE_DUPLICATE_COLUMN`,
  `STORAGE_CONSTRAINT_UNIQUE`, `STORAGE_CONSTRAINT_NOT_NULL`,
  `STORAGE_CONSTRAINT_CHECK`, `STORAGE_IO_ERROR`,
  `STORAGE_CORRUPTION`.

## VDBE cursor-open surface (called by vdbe/opcodes-core)

The VDBE opens cursors via the following storage functions:

### Rust

```rust
pub fn open_cursor(
    db: &Database,
    table: &str,
    writable: bool,
) -> Result<CursorHandle, RuntimeCondition>;
```

Returns `CursorHandle` on success. On failure, maps storage's
internal conditions to the VDBE-facing `RuntimeCondition`:

- Storage `TABLE_NOT_FOUND` → `RuntimeCondition::TableNotFound`
- Storage `IO_ERROR` → `RuntimeCondition::IoError`
- Any other storage condition → `RuntimeCondition::IoError` with a
  logged detail (v2 doesn't propagate finer-grained storage
  diagnostics to the VDBE).

### C

```c
LeapRuntimeCondition leap_storage_open_cursor(
    LeapDatabase* db,
    const char* table, size_t table_len,
    bool writable,
    LeapCursor** out_cursor
);
```

Returns `LEAP_RC_*` condition code; on success (implied by returning
an OK sentinel distinct from any `LEAP_RC_*`) populates
`*out_cursor`.

The VDBE passes its storage-backing `Database` handle through
`VdbeState` or via a separate handle provided by the executor
driver; the exact plumbing is a v2 open question — sub-parts should
assume a `Database` reference is available in `state.db()` or as a
function argument, pending a future cross-sub-part interface
declaration.

## `CursorHandle` — canonical shape (owned by this part)

Opaque cursor handle exposed to the VDBE. The VDBE holds these by
value in `VdbeState::cursors`; it does not introspect their
internals.

### Rust

```rust
pub struct CursorHandle {
    // Implementation detail: cursor kind (table | index), backing
    // b-tree handle, current position, writable flag. Internals
    // opaque to callers.
    inner: CursorInner,
}

impl CursorHandle {
    pub fn is_writable(&self) -> bool;
    pub fn is_closed(&self) -> bool;
}
```

### C

```c
typedef struct LeapCursor LeapCursor;  // opaque; defined in storage.c
bool leap_cursor_is_writable(const LeapCursor*);
bool leap_cursor_is_closed(const LeapCursor*);
```

The VDBE only observes a cursor through the methods/functions
above. All positional ops (seek, next, column read) are routed via
VDBE opcodes → storage surface.

## Sub-part map

- `parts/file-format/` — on-disk layout. Absorbs v1
  `file-format.spec.md` (572 lines). Page types, header, page
  encoding, varint, cell packing. Bidirectional compat with
  mainline SQLite files.
- `parts/btree/` — b-tree operations: insert, delete, split, merge,
  cursor walk. Multi-page paging. Both table b-trees and index
  b-trees.
- `parts/pager/` — page cache, dirty-page tracking, eviction.
  Absorbs v1 `pager-async.spec.md` (235 lines).
- `parts/wal/` — write-ahead log. Absorbs v1 `wal.spec.md` (323
  lines) including Phase 3d atomic-rename mode, Phase 4a reader,
  Phase 4b per-commit append-on-write.
- `parts/index/` — index management: creation, rowid-based lookup,
  index maintenance on DML (Phase 9c), UNIQUE enforcement (Phase
  9g).

## Cross-sub-part invariants

### Durability

Fsync boundaries live in `parts/wal/` and `parts/pager/`. The rule
(also in `/spec/durability.spec.md`): every `commit` returns only
after the frame batch has been fsync'd to the WAL file. Checkpoint
fsync's both the main DB file and truncates the WAL atomically.

### File-format compatibility

The wire contract is SQLite's published file format 3. All
sub-parts that read or write bytes to disk obey
`parts/file-format/master.md`. A v1 LEAP-written DB must be readable
by mainline SQLite byte-for-byte, and vice versa. This is tested
via the roundtrip matrix (`tests/fuzz/file-format/`, 900/900 green
as of v1 freeze).

### Page size

Fixed 4096-byte pages for v1 and v2. Variable page size is out of
scope.

### WAL activation

A `Database` opened on a path-backed file may operate in one of two
WAL modes:

- **Phase 3d (atomic-rename)** — default for in-memory DBs and the
  v1 simple path. Each commit rewrites the entire image via an
  atomic rename.
- **Phase 4b (append-on-write)** — active when `LEAP_WAL_APPEND=1`
  AND the database is disk-backed. Commits append a dirty-page
  frame batch to the WAL file; checkpoint folds the WAL into the
  main file.

The mode selection is the storage facade's concern; sub-parts do not
branch on it beyond `parts/wal/` itself.

## What this part does NOT own

- Query planning / index selection: the compiler chooses which index
  to open; storage just opens it.
- Concurrent writer coordination beyond single-writer serialization.
  Multi-writer and replication are out of scope for v2.

## Composition

Each sub-part emits its own module. This part's generator produces
a `Database` struct that holds handles into file-format, btree,
pager, wal, and index sub-parts, and exposes the public interface
above by delegating to them.
