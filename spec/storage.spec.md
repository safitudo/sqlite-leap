# Storage — language-neutral spec

> **Phase 5 (Async) header note.** This document defines the sync-only storage contract covering Phases 2a / 3a–3d / 4a. It is extended, not replaced, by `pager-async.spec.md` (the async pager state machine) and `io-backend.spec.md` § "Phase 5 extension — async submission/completion model". New code on C and Rust targets SHOULD target the async path defined there; the sync contract below is retained for WASM (which has no async file I/O primitives) and for correctness-first local iteration. The observable semantics of CRUD operations (`create_table`, `insert_row`, `select_all`, …) are unchanged; what Phase 5 changes is the internal I/O seam, not the external storage API. No Phase 4 on-disk format guarantees are altered by Phase 5. See `pager-async.spec.md` for the list of sections that new async-aware implementations replace.

This spec defines the in-memory storage model introduced in Phase 2a. Later
phases extend it with on-disk file format, paging, and WAL; those are NOT in
scope here.

Storage is a separate part (`parts/storage/`). Other parts — specifically the
executor — interact with storage only through the operations listed below.
Storage's internal data structures are an implementation detail of the
storage target. Each language target is free to choose any representation
(arrays, linked lists, hash maps, struct-of-arrays) as long as the abstract
contract is honoured.

## Data model

A **Database** is a non-persistent container. In Phase 2a every test case
begins with an empty database. The database holds an unordered set of
**Tables**, each uniquely keyed by a case-sensitive **table name** (an
`IDENTIFIER` as produced by the tokenizer).

A **Table** has:

- `name` — an `IDENTIFIER`, case-sensitive, unique within the database
- `columns` — a non-empty ordered list of **Column** records
- `rows` — an ordered list of **Row** records; the order is insertion order and MUST be preserved on readback

A **Column** has:

- `name` — an `IDENTIFIER`, case-sensitive, unique within its table
- `type` — one of the values `INTEGER` or `TEXT` (Phase 2a supports no other types)

A **Row** is an ordered list of **Value** records whose length equals the table's column count. The i-th Value in a Row corresponds to the i-th Column in the table.

A **Value** is the same `Value` union defined in `schema/value.schema.json`: a 64-bit signed integer, a UTF-8 text, or SQL NULL.

## Type compatibility

Phase 2a uses strict typing:

- A column declared `INTEGER` accepts an integer Value or a NULL Value. A text Value is rejected with `STORAGE_TYPE_MISMATCH`.
- A column declared `TEXT`    accepts a text    Value or a NULL Value. An integer Value is rejected with `STORAGE_TYPE_MISMATCH`.

NULL is universally accepted regardless of the column's declared type.

No coercion occurs. SQLite's historical type affinity is NOT in scope for Phase 2a; later phases may relax.

## Operations

Each operation terminates in one of two ways: successfully, producing the stated output, or unsuccessfully, producing exactly one of the named error conditions. Each language target maps success / failure to its idiomatic mechanism.

### `create_table(name, columns)`

- **Inputs:**
  - `name` — an `IDENTIFIER`
  - `columns` — a non-empty ordered list of `(name, type)` pairs
- **Success:** the database now contains a new Table with the given `name`, the given `columns` (order preserved), and an empty `rows` list.
- **Errors (checked in this precedence order — first match wins):**
  1. `STORAGE_TABLE_EXISTS` — a table with `name` already exists in the database. Carries `table` (the offending name).
  2. `STORAGE_DUPLICATE_COLUMN` — two columns in `columns` share a name (case-sensitive compare). Carries `table` and `column` (the first repeated name, leftmost).

### `insert_row(table_name, column_names, values)`

- **Inputs:**
  - `table_name` — an `IDENTIFIER`
  - `column_names` — EITHER the null/absent marker ("no column list supplied; apply positionally to all table columns") OR a non-empty ordered list of `IDENTIFIER` names
  - `values` — a non-empty ordered list of Values
- **Success:**
  - If `column_names` is absent: the Table named `table_name` gains one Row whose i-th Value is `values[i]`. Requires `|values| == |table.columns|`.
  - If `column_names` is present: the Table named `table_name` gains one Row whose j-th Value is derived by: if the j-th declared column's name appears at index k in `column_names`, the Value is `values[k]`; else the Value is NULL.
- **Errors:**
  - `STORAGE_TABLE_NOT_FOUND` — no table named `table_name` exists. Carries `table`.
  - `STORAGE_COLUMN_NOT_FOUND` — a name in `column_names` is not a column of the table. Carries `table` and `column` (the offending name).
  - `STORAGE_DUPLICATE_COLUMN` — `column_names` mentions the same column name more than once (case-sensitive). Carries `table` and `column`.
  - `STORAGE_ARITY_MISMATCH` — value count does not match the expected count (`|table.columns|` when no `column_names`, else `|column_names|`). Carries `table`, `expected` (integer), `got` (integer).
  - `STORAGE_TYPE_MISMATCH` — a value's type is incompatible with its target column. Carries `table`, `column` (target column name), `expected_type` (`"INTEGER"` or `"TEXT"`), `got_type` (`"INTEGER"` or `"TEXT"`). NULL is universally accepted and never raises this error.

Error precedence (when multiple conditions would apply): `STORAGE_TABLE_NOT_FOUND` > `STORAGE_COLUMN_NOT_FOUND` (first offending name wins) > `STORAGE_DUPLICATE_COLUMN` > `STORAGE_ARITY_MISMATCH` > `STORAGE_TYPE_MISMATCH` (first offending value position wins).

### `select_all(table_name)`

- **Inputs:** `table_name` — an `IDENTIFIER`
- **Success:** an ordered list of Rows in insertion order; each produced Row is the full stored Row in declared-column order. An empty-table case returns an empty list (no error).
- **Errors:**
  - `STORAGE_TABLE_NOT_FOUND` — no table named `table_name` exists. Carries `table`.

### `select_columns(table_name, column_names)`

- **Inputs:** `table_name` — an `IDENTIFIER`; `column_names` — a non-empty ordered list of `IDENTIFIER` names.
- **Success:** an ordered list of Rows in insertion order; each produced Row has one Value per name in `column_names`, in that order. Duplicates in `column_names` are ALLOWED and produce duplicate columns in each output Row (mirrors SQLite's observed behaviour).
- **Errors:**
  - `STORAGE_TABLE_NOT_FOUND` — as above.
  - `STORAGE_COLUMN_NOT_FOUND` — a name in `column_names` is not a column of the table. Carries `table` and `column`. The first offending name (leftmost) wins.

## Implementation freedom

The storage part MAY represent Tables, Rows, the Database, and its internal indices using any data structures the target chooses, as long as:

- The abstract contract above is honoured
- Insertion order of rows is preserved on readback
- Column and table name lookup is case-sensitive

Memory ownership, lifetime, and thread-safety are target-defined. Phase 2a tests are single-threaded and run each case against a freshly-constructed database, so owned-value Rust and manual-free C both work.

## Target-defined conditions

Allocator failure is target-defined and not exercised by the Phase 2a test suite. The executor does not probe for it, and no `STORAGE_*` name covers it.

## Test authority

`tests/cross-build/phase2a.json` is the executable specification for Phase 2a storage behaviour. If this document and those tests disagree, the tests win.

---

## Phase 2c-3 — mutation operations (UPDATE, DELETE)

Phase 2c-3 extends the storage data model with a **tombstone** per Row and adds two new operations: `update_row_at_cursor` and `delete_row_at_cursor`. No existing operation's contract changes; existing ops gain a single clarification ("tombstoned rows are not visible").

### Tombstone model

Every Row has an implicit boolean flag: **live** (default) or **tombstoned**. A live row is visible to queries; a tombstoned row is not. Tombstoning is one-way — a tombstoned row cannot be resurrected. Storage implementations MAY keep tombstoned rows in their internal row list (saving allocation churn) OR compact them out; observable behaviour is identical.

### Visibility rules (extend existing ops)

- `select_all(table_name)` — returns live rows only, in insertion order (insertion order is unchanged by tombstoning: deleted rows are simply skipped).
- `select_columns(table_name, column_names)` — returns live rows only.
- Cursor iteration (`Rewind`, `Next`, `Column` via the VDBE) — `Rewind` positions on the first LIVE row; `Next` advances to the next LIVE row, skipping tombstones; both eventually fall through to past-end when no live row remains.
- `insert_row(...)` — appends a live row at the end of the internal row list. The tombstone slots of previously-deleted rows are NOT reused in Phase 2c-3; the new row always takes a fresh slot (implementation detail) or is appended past any trailing tombstones (observable equivalent).

### New operation: `update_row_at_cursor(cursor, column_names, values)`

- **Inputs:**
  - `cursor` — a write-capable cursor positioned on a live row
  - `column_names` — a non-empty ordered list of `IDENTIFIER` names
  - `values` — a non-empty ordered list of Values; `|values| == |column_names|`
- **Success:** the row at the cursor's current position is mutated. For each `i`, the column named `column_names[i]` in the cursor's table receives `values[i]`. Columns not in `column_names` retain their existing values. The row remains live (UPDATE does not tombstone). Row insertion order is unchanged.
- **Errors (precedence order — first match wins):**
  - `STORAGE_COLUMN_NOT_FOUND` — a name in `column_names` is not a column of the cursor's table. Fields: `table`, `column`.
  - `STORAGE_DUPLICATE_COLUMN` — `column_names` contains the same name more than once (case-sensitive). Fields: `table`, `column`. (Expected to be caught at compile time by the compiler; here as a safety net.)
  - `STORAGE_TYPE_MISMATCH` — a value's type is incompatible with its target column's declared type (non-NULL type disagreement). Fields: `table`, `column`, `expected_type`, `got_type`. First offending `(column, value)` pair (leftmost in `column_names`) wins.

NULL values are universally accepted regardless of declared column type (same rule as `insert_row`).

### New operation: `delete_row_at_cursor(cursor)`

- **Inputs:** `cursor` — a write-capable cursor positioned on a live row
- **Success:** the row at the cursor's current position is marked tombstoned. Subsequent queries and subsequent iterations (on any cursor, including the same one) do not see this row.
- **Errors:** none. The "cursor is positioned on a live row" precondition is the VDBE / compiler's contract; the storage implementation MAY assert the precondition (undefined behaviour on violation is acceptable).

### Interaction with a running cursor

A cursor is allowed to DELETE its current row, then call `Next`. The tombstoning does NOT invalidate the cursor. `Next` after a `delete_row_at_cursor` advances past the tombstoned row to the next live row (or past-end). This is how Phase 2c-3's compiled DELETE statements walk and delete in a single pass.

A cursor is allowed to UPDATE its current row, then call `Next` — the row remains live and visible to future scans, but THIS cursor's iteration moves on.

Concurrent cursors on the same table in the same VDBE program are not exercised by Phase 2c-3 tests; behaviour in that case is target-defined.

### Ordering after tombstoning

Insertion order is preserved for all LIVE rows across UPDATE/DELETE operations. Example:

```
INSERT INTO t VALUES (1);  -- row 0 live
INSERT INTO t VALUES (2);  -- row 1 live
INSERT INTO t VALUES (3);  -- row 2 live
DELETE FROM t WHERE x = 2; -- row 1 now tombstoned
SELECT * FROM t;           -- returns [[1], [3]] in that order
INSERT INTO t VALUES (4);  -- appended as row 3 live
SELECT * FROM t;           -- returns [[1], [3], [4]]
```

No rowid is exposed in Phase 2c-3 — deletion and update operate on the cursor's current position, not on an explicit rowid.

### Test authority (Phase 2c-3)

`tests/cross-build/phase2c3.json` validates the new mutation operations. Phase 2a's tests remain in force and MUST stay green.

---

## Phase 3a — on-disk persistence (two backends)

Phase 3a adds a second storage backend: **on-disk**, producing SQLite-compatible files. The **in-memory backend from Phase 2a–2c remains unchanged** and stays the primary path for fast iteration, tests, and Lane 3 (in-memory SELECT benchmark). The on-disk backend is a parallel implementation; both satisfy the same abstract operations contract.

See `spec/file-format.spec.md` for the authoritative on-disk layout (header, pages, cells, records, varint).

### Backend selection

Two new operations replace the single-rooted `create_database()` with a richer open protocol:

- **`create_memory_database()`** — returns a handle to a new in-memory Database. Behaviour identical to Phase 2a's `create_database()`. All existing phase1–2c-3 tests use this.
- **`open_database(path)`** — returns a handle to an on-disk Database at `path`. If the file does not exist, creates a fresh empty SQLite-compatible database (4096-byte single page, no tables) at that path. If the file exists and is valid per `spec/file-format.spec.md` § "Supported read surface", opens it.

The two handles are NOT interchangeable at the ABI level (different target-level representations), but they satisfy the SAME abstract operations (`create_table`, `insert_row`, `select_all`, `select_columns`, `update_row_at_cursor`, `delete_row_at_cursor`). Callers select once at open time and use the same op names thereafter.

### `close_database(handle)` (new)

- **Inputs:** `handle` — a Database handle from either backend.
- **Success:** all pending changes are flushed (on-disk backend only — in-memory is a no-op). The handle is closed and subsequent operations on it are target-defined undefined behaviour.
- **Errors:**
  - `STORAGE_FILE_IO` (on-disk only) — filesystem failure during flush / close. Fields: `path`, `operation`.

For test infrastructure, `close_database` is called at the end of every on-disk test case. In-memory tests may skip it.

### Abstract-operation clarifications (Phase 3a)

All six existing abstract operations work identically on both backends from the caller's perspective. Storage-level errors are the same names, same fields. The on-disk backend adds THREE extra error possibilities (any operation that touches a page can hit them):

- `STORAGE_FILE_IO` — I/O failure during the op.
- `STORAGE_CORRUPT_PAGE` — a previously-valid page became unparseable (shouldn't happen under normal operation; surfaces as a safety net).
- `STORAGE_PAGE_FULL` — on INSERT or UPDATE: the record no longer fits on its table's single page. Fields: `table`, `required_bytes`, `available_bytes`.

Open-time (in `open_database`) additionally may raise:

- `STORAGE_CORRUPT_HEADER` — the file's header fails validation.
- `STORAGE_UNSUPPORTED_FEATURE` — the file uses a format feature we don't handle yet (see file-format spec).
- `STORAGE_UNSUPPORTED_TYPE` — deferred to first column read that hits an unsupported serial type.

### Rowid semantics (Phase 3a)

On-disk storage introduces an explicit **rowid** for each row: a 64-bit signed integer assigned at INSERT time, monotonically increasing per table, starting at 1, never reused within a file's lifetime (tombstones + DELETE increment the implicit "next rowid" counter only on INSERT). This is SQLite's default behavior (without `AUTOINCREMENT`) and is required to place cells in the table-leaf B-tree in rowid-sorted order.

The in-memory backend previously had no explicit rowid — insertion order was position in a list. To keep the two backends equivalent for tests, the in-memory backend now ALSO assigns an implicit rowid (starting at 1, monotonic). Visible effect on tests: none. Rowids are not surfaced through the SELECT projection in Phase 3a (`SELECT rowid FROM t` is a later feature — `rowid` is not a grammar keyword yet).

### Cursor lifecycle extensions (Phase 3a, on-disk only)

Cursor positions on the on-disk backend represent `(root_page, cell_index)`. Rewind positions at the first live cell. Next advances to the next live cell (in rowid order) or falls through at end-of-page. Column reads decode the cell's record on demand. UpdateRow encodes new values and replaces the cell in-place (may succeed or raise `STORAGE_PAGE_FULL`). DeleteRow removes the cell from the page (compacts in-memory; flushed at close).

### Test authority (Phase 3a)

`tests/cross-build/phase3a.json` is the executable specification for Phase 3a on-disk behavior. Prior phases remain in force and MUST stay green on the in-memory backend.

## Phase 3b — multi-page tables (on-disk backend)

Phase 3b lifts the single-page-per-table restriction on the on-disk backend. The public API surface is UNCHANGED (no new ops, no new error fields — `STORAGE_PAGE_FULL` continues to be the page-full signal but now fires only in the narrower interior-full case; see `spec/file-format.spec.md` § "Phase 3b — multi-page tables"). The in-memory backend is UNCHANGED.

### What the storage part must handle in Phase 3b

- **On-disk cursor over multi-page trees.** Rewind descends to the leftmost leaf; Next walks leaves left-to-right across interior pages. The cursor abstraction MUST hide page boundaries from callers; executor / vdbe code from Phases 2b–2c-3 sees exactly the same per-row stream it saw in Phase 3a. The cursor remembers its path (a stack of `(page, cell_index)` frames for interior ancestors) so that Next can pop-and-advance without re-descending from root.
- **On-disk INSERT with leaf splits.** The writer walks to the rightmost leaf (monotonic rowids guarantee that's where the new row belongs), then applies the split protocol from `file-format.spec.md` if the leaf is full. Split protocol may allocate 1 or 2 new pages (Case A on first split, Case B on subsequent).
- **On-disk UPDATE across pages.** UPDATE locates the target row via the cursor (which now traverses interior routing). In-place rewrite succeeds if the new record size ≤ old record size + slot padding (straightforward in-page mutation); if the new record would overflow the current leaf, raise `STORAGE_PAGE_FULL` (row-migration across leaves is NOT supported in Phase 3b; it's deferred because monotonic rowids mean practical updates rarely outgrow their leaf).
- **On-disk DELETE across pages.** DELETE writes the tombstone bit on the target leaf cell (same mechanism as Phase 3a). The tree is never re-balanced; tombstoned cells remain on the page until overwritten or until Phase 3c's compaction pass reclaims them.
- **Close** flushes every dirty page (leaves AND interiors) in the in-RAM cache. File layout is a concatenation of page buffers in page-number order.

### Rowid assignment (Phase 3b)

Unchanged from Phase 3a: starts at 1, increments by 1 per INSERT per table, never reuses. The max-rowid-so-far is tracked in RAM per table (derived on open from the tree's rightmost leaf's last cell's rowid, or 0 if the table is empty).

### Interior-page read tolerance

On open, the reader MUST accept files written by mainline SQLite with arbitrary-depth interior trees. The cursor algorithm in `file-format.spec.md` handles any depth. The writer produces only depth-≤-2 trees in Phase 3b.

### Test authority (Phase 3b)

`tests/cross-build/phase3b.json` is the executable specification for Phase 3b. Phase 3a, 2c-3, and earlier tests MUST stay green on their declared backend.
