---
name: storage/without-rowid
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /parts/core/master.md
  - /parts/storage/master.md
  - /parts/storage/parts/btree/master.md
  - /parts/storage/parts/file-format/master.md
  - /parts/storage/parts/fileformat-write-lib/master.md
  - /parts/storage/parts/index/master.md
emits:
  c:      { path: src-c-v2/storage/without_rowid.c, headers: [src-c-v2/storage/without_rowid.h] }
  rust:   { path: src-rust-v2/storage/without_rowid.rs }
  zig:    { path: src-zig-v2/storage/without_rowid.zig }
  go:     { path: src-go-v2/storage/without_rowid.go }
  python: { path: src-python-v2/storage/without_rowid.py }
---

# Part: storage/without-rowid

WITHOUT ROWID tables: B-tree records keyed by the **declared PRIMARY KEY**
rather than by an internal rowid. Reference: sqlite.org/withoutrowid.html
(published format spec — allowed input).

The query layer is **transparent** to the WITHOUT ROWID distinction:
the parser surfaces a flag on the table-schema record, and the storage
layer detects it and dispatches to the right cursor / record encoding.
DML codegen (`parts/compiler/parts/{insert,update,delete}/`) and
SELECT codegen (`parts/compiler/parts/select/`) emit the **same opcodes**
regardless; storage handles the divergence.

## Table-schema flag

Each `TableSchema` record carries:

```
without_rowid: bool        // present when CREATE TABLE … WITHOUT ROWID
pk_columns:    [ColumnIdx] // 1+ entries; required when without_rowid=true
pk_collations: [CollName]  // per-column collating sequence
pk_directions: [SortOrder] // ASC|DESC per column
```

Required: `pk_columns` is non-empty when `without_rowid=true`.
Compile-time error `SCHEMA_WITHOUT_ROWID_PK_MISSING` otherwise.

## On-disk record layout

A WITHOUT ROWID row is stored in the table's B-tree as a single
**index-style record** (no separate rowid integer). The btree uses
the **index-leaf / index-interior** page kinds (the same kinds used
by ordinary indexes), not the table-leaf / table-interior kinds.

Record bytes are produced by the existing record-encoder (varint
header + serialtypes), but the **logical split** is:

```
record = encode( pk_columns_in_pk_order ++ remaining_columns_in_decl_order )
key    = encode( pk_columns_in_pk_order )            // for B-tree comparisons
```

The full record is stored as the payload; the key prefix is what the
btree comparator uses. Comparison honors `pk_collations` and
`pk_directions` per column.

## Key-encoding contract

- The PK key is the **canonical-order** prefix of the record. No
  separate "key blob" exists alongside the value.
- DESC columns invert sort order at the comparator level; the bytes
  are not pre-inverted (matches mainline).
- `NULL` is permitted in PK columns of WITHOUT ROWID tables (mainline
  behavior); two `NULL`s compare equal at the PK level → uniqueness
  violation. Spec pin 7.

## Storage surface (canonical signatures)

Both emissions must match these signatures.

### Rust

```rust
use crate::core::{Value, RuntimeCondition, SortOrder};
use crate::storage::{Database, CursorHandle, TableSchema};

/// Open a read/write cursor on a WITHOUT ROWID table by name.
pub fn open_without_rowid_cursor(
    db: &Database,
    table_name: &str,
) -> Result<CursorHandle, RuntimeCondition>;

/// Seek by full PK tuple. Ok(true) if exact match found.
pub fn cursor_seek_pk(
    cursor: &mut CursorHandle,
    pk: &[Value],
) -> Result<bool, RuntimeCondition>;

/// Read the full row payload at the current position
/// (PK columns followed by remaining columns, in declaration order).
pub fn cursor_read_row(
    cursor: &CursorHandle,
) -> Result<Vec<Value>, RuntimeCondition>;

/// Insert a row. Returns ConstraintUnique on duplicate PK.
pub fn without_rowid_insert(
    db: &Database,
    schema: &TableSchema,
    row: &[Value],
) -> Result<(), RuntimeCondition>;

/// Update row at current cursor; PK column edits are detected and
/// performed as delete+insert at the storage layer.
pub fn without_rowid_update(
    cursor: &mut CursorHandle,
    schema: &TableSchema,
    new_row: &[Value],
) -> Result<(), RuntimeCondition>;

pub fn without_rowid_delete(cursor: &mut CursorHandle) -> Result<(), RuntimeCondition>;
```

### C

```c
LeapRuntimeCondition leap_storage_open_without_rowid_cursor(
    LeapDatabase* db, const char* table_name, size_t name_len,
    LeapCursor** out_cursor);

LeapRuntimeCondition leap_storage_cursor_seek_pk(
    LeapCursor*, const LeapValue* pk, size_t pk_len, bool* out_found);

LeapRuntimeCondition leap_storage_cursor_read_row(
    const LeapCursor*, LeapValue** out_row, size_t* out_len);

LeapRuntimeCondition leap_storage_without_rowid_insert(
    LeapDatabase* db, const LeapTableSchema* schema,
    const LeapValue* row, size_t row_len);

LeapRuntimeCondition leap_storage_without_rowid_update(
    LeapCursor*, const LeapTableSchema* schema,
    const LeapValue* new_row, size_t new_len);

LeapRuntimeCondition leap_storage_without_rowid_delete(LeapCursor*);
```

## VDBE-facing transparency

`OpenWrite` / `OpenRead` consult the schema's `without_rowid` flag
and dispatch internally. Compilers do **not** emit a different opcode
sequence; the **same** SELECT/INSERT/UPDATE/DELETE pipeline runs:

- `Rowid` opcode against a WITHOUT ROWID cursor returns
  `RuntimeCondition::NoRowid` (new condition; promote to all 5 targets).
- `NewRowid` is **never emitted** by INSERT codegen against WITHOUT
  ROWID tables; the planner notices the flag and routes to the
  PK-tuple insert path instead. Spec pin 11.
- `Insert` opcode delegates to `without_rowid_insert` when its target
  cursor is on a WITHOUT ROWID root.
- INTEGER PRIMARY KEY is **not** aliased to a rowid in WITHOUT ROWID
  tables — it is a real PK column with its own storage cell. Spec
  pin 4.

## Auto-index on WITHOUT ROWID

A WITHOUT ROWID table needs **no** `sqlite_autoindex_*` for its PK —
the table B-tree itself is the PK index. Secondary indexes still
get auto-indexes when declared UNIQUE. Each secondary index entry's
**rowid slot stores the PK tuple** rather than an integer rowid;
the index-cursor surface widens accordingly (see Spec pin 12).

## Correctness pins

1. `CREATE TABLE … WITHOUT ROWID` without an explicit `PRIMARY KEY`
   declaration raises `SCHEMA_WITHOUT_ROWID_PK_MISSING` at parse/
   compile time, before any storage write.
2. The B-tree backing a WITHOUT ROWID table uses index-leaf and
   index-interior page kinds, not table-leaf / table-interior.
3. PK column order in the on-disk record matches the order declared
   in `PRIMARY KEY (...)`, **not** the order of `CREATE TABLE` columns.
4. INTEGER PRIMARY KEY in a WITHOUT ROWID table is **not** rowid-
   aliased; it is stored as a PK column like any other.
5. Non-PK columns appear in the record after the PK prefix, in the
   declaration order of `CREATE TABLE`.
6. Comparisons honor per-column `pk_collations` and `pk_directions`.
   DESC sort is implemented in the comparator, not by byte inversion.
7. Two rows with all-NULL PKs collide and the second `INSERT` raises
   `ConstraintUnique` — NULLs compare equal in PK context (mainline
   behavior; differs from secondary unique-index semantics).
8. UPDATE that changes any PK column is implemented as
   `delete-old-key` + `insert-new-key`; if the new PK collides with
   an existing row, the operation raises `ConstraintUnique` and the
   old row is **not** deleted (atomic at the storage call boundary).
9. `Rowid` opcode against a WITHOUT ROWID cursor raises
   `RuntimeCondition::NoRowid`; SELECT codegen never emits `Rowid`
   for tables it knows are WITHOUT ROWID.
10. The schema flag `without_rowid` is byte-serialized into
    `sqlite_schema.sql` text exactly (mainline reads it back from the
    DDL). No additional schema column is added.
11. `NewRowid` is suppressed by the compiler when target table is
    WITHOUT ROWID; planner re-routes INSERT through PK-tuple path.
12. Secondary indexes on a WITHOUT ROWID table store the PK tuple in
    the slot where rowid would otherwise live; `cursor_idx_rowid`
    against such an index returns `RuntimeCondition::NoRowid` and
    the planner uses `cursor_idx_pk` instead.
13. WITHOUT ROWID tables are mainline-readable: a `.db` produced by
    LEAP must open in mainline SQLite and round-trip data identically.
14. Bidirectional: a `.db` produced by mainline SQLite with
    WITHOUT ROWID tables must open in LEAP; PK detection comes from
    parsing the DDL stored in `sqlite_schema`.
15. Empty PK tuple (zero columns) is a parse-time error
    `SCHEMA_WITHOUT_ROWID_PK_MISSING`; not a runtime concern.
16. Page format version, leaf payload thresholds, and overflow-page
    spillover follow the same rules as ordinary index B-trees;
    no new page-format constants are introduced.

## Phase pins

- **Phase 14a** — schema flag plumbed; storage detection.
- **Phase 14b** — INSERT/UPDATE/DELETE round-trip on PK-keyed B-tree.
- **Phase 14c** — secondary indexes on WITHOUT ROWID (PK-tuple slot).
- **Phase 14d** — bidirectional file-format compat with mainline.

## Regeneration envelope

- Target leaf size: 400–700 lines per target.
- Spec < 220 lines.
