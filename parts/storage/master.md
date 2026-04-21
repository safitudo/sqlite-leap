# Part: storage

Owns the in-memory Database. Exposes the operations defined in `spec/storage.spec.md` (sections "Operations") through an opaque handle.

## Contract

- **Input:** operations are invoked on an opaque storage handle (a Database). Each target represents the handle as its idiomatic mutable-reference type (a `Database*` in C, a `&mut Database` or `RefCell` in Rust, etc.). A fresh handle is obtained via a `create_database()` constructor and disposed via the target's standard lifetime mechanism.
- **Outputs:** each operation returns success with the output defined in `spec/storage.spec.md` or fails with exactly one of the storage-level `STORAGE_*` error conditions.

## Required behaviour

Per `spec/storage.spec.md`:

- `create_database()` returns a fresh, empty Database handle.
- `create_table(handle, name, columns)` — see spec.
- `insert_row(handle, table_name, column_names, values)` — see spec. `column_names` is a nullable ordered list; `null` means positional insert over all columns.
- `select_all(handle, table_name)` — returns all LIVE rows (see tombstone section below) in insertion order, columns in declared order.
- `select_columns(handle, table_name, column_names)` — returns all LIVE rows in insertion order, columns in the order named.
- **Phase 2c-3 additions:**
  - `update_row_at_cursor(handle, cursor, column_names, values)` — mutates the row at the cursor's current position. See `spec/storage.spec.md` § "Phase 2c-3".
  - `delete_row_at_cursor(handle, cursor)` — tombstones the row at the cursor's current position.
- **Phase 2c-3 cursor abstraction** — the storage part MUST expose a write-capable cursor (used by `OpenWrite` / `Rewind` / `Next` / `Column` / `UpdateRow` / `DeleteRow`) that tracks a current position over a table's rows, skips tombstoned rows on `Next`, and supports in-place updates and deletions at the current position. The exact cursor type is target-defined; only its abstract contract matters.

- **Phase 3a additions — on-disk backend:**
  - `create_memory_database()` — explicit in-memory constructor (alias for `create_database()`, used by new tests that want to distinguish from `open_database`).
  - `open_database(path)` — on-disk Database handle. Creates an empty SQLite-compatible 4096-byte file if `path` does not exist; otherwise opens and validates an existing one (see `spec/file-format.spec.md` § "Supported read surface"). May raise `STORAGE_FILE_IO`, `STORAGE_CORRUPT_HEADER`, `STORAGE_UNSUPPORTED_FEATURE`.
  - `close_database(handle)` — flushes any dirty on-disk pages and releases the handle; no-op on in-memory. May raise `STORAGE_FILE_IO`.
  - The existing 6 ops (`create_table`, `insert_row`, `select_all`, `select_columns`, `update_row_at_cursor`, `delete_row_at_cursor`) are UNCHANGED in surface — each has an in-memory implementation (already built) and an on-disk implementation (new in Phase 3a).
  - The on-disk implementation reads/writes pages per `spec/file-format.spec.md`: 100-byte header on page 1, table-leaf pages (type `0x0d`) only, records in serial-type format, big-endian on disk, host-endian in RAM.
  - Rowids: monotonically assigned per table, starting at 1, never reused. Stored as the table-leaf cell's rowid varint. In-memory backend also gains implicit rowids (not visible through SELECT in Phase 3a).
  - **Simplicity strategy for Phase 3a**: on open, read the entire file into RAM; operate on in-RAM pages throughout the session; write the entire file back on close. No page cache, no journaling, no partial writes. This is slow per-op but correct, and keeps 3a implementation tight. Page-cache optimisation is Phase 3b; journaling is Phase 3d.
  - **Part independence update**: the storage part still has no dependency on other parts. It gains a dependency on the host OS's file I/O primitives (open/read/write/fsync/close), which are target-defined per language.

- **Phase 3b additions — multi-page tables (on-disk):**
  - Public API surface UNCHANGED. All 9 operations (`create_database`, `create_memory_database`, `open_database`, `close_database`, `create_table`, `insert_row`, `select_all`, `select_columns`, `update_row_at_cursor`, `delete_row_at_cursor`) keep their Phase 3a signatures.
  - The on-disk backend's storage tree grows beyond a single leaf per table: see `spec/file-format.spec.md` § "Phase 3b — multi-page tables" for the interior-page (0x05) layout, split protocol, and B-tree read/write recipes.
  - The cursor abstraction hides page boundaries from callers; vdbe and executor see the same per-row stream as Phase 3a regardless of tree depth.
  - In-memory backend UNCHANGED.
  - Simplicity strategy (whole-file slurp-on-open, flush-on-close) UNCHANGED from Phase 3a — Phase 3b still performs all I/O at open/close boundaries. Page-cache + partial-write support moves to Phase 3d (with the journal).
  - `STORAGE_PAGE_FULL` now fires only in the narrower case where a split would require an interior-page-level split (deferred to 3c) or where a single row cannot fit in any page (deferred to 3c via overflow pages).

Storage MUST:

- Preserve row insertion order
- Treat table and column names case-sensitively for lookup
- Copy or retain values (not borrow from caller) so the Row remains valid after the caller's inputs go out of scope — the exact copy strategy is target-defined
- Surface exactly the `STORAGE_*` error conditions enumerated in the spec, each carrying the fields the spec names

Storage MUST NOT:

- Perform I/O (Phase 2a is in-memory only)
- Depend on any other part's generated code
- Silently coerce types (strict typing; only NULL is universal)

## Implementation freedom

Data structure choice is the storage target's prerogative. Examples: a plain array-of-structs, a vector-of-rows with a side hash map for column-name lookup, a struct-of-arrays for column-store layouts. Ownership (arena allocator in C, `Vec<Row>` with owned `String`s in Rust) is target-defined. The test suite does not observe the internal representation — only the abstract operations.

## Part independence

Storage depends only on:

- `spec/storage.spec.md`
- `schema/value.schema.json` (for the Value union)

It does NOT depend on the tokenizer, parser, or executor. Those parts are higher-level consumers.

## Output location

Generated code lives in `src-{lang}/storage/`. Exposes the constructor and the four operations listed above (or their target-language equivalents). The executor part calls into this interface and no other.
