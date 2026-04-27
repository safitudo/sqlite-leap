---
name: mem-store
kind: leaf
emits:
  rust: { path: src-rust/storage.rs }
  c:    { path: src-c/storage.c, headers: [src-c/storage.h] }
---

# In-memory storage (behavioral test harness)

Minimal HashMap-backed Database + CursorHandle implementation. Scope
is exactly what the VDBE SELECT execution path needs: read-only
cursors with rewind/next/column. Writes, rowid seeks, indexes, seeks
by key, cursor invalidation on DDL — all out of scope for this leaf;
they belong to the btree-backed real storage part.

**This leaf replaces the stub `src-rust/storage.rs`** (currently a set
of `unimplemented!()` shells). After this leaf runs, every VDBE read
opcode terminates in a working function instead of a panic.

## Scope

Admitted:
- `Database` that owns a list of named tables; caller installs tables
  before invoking the VDBE.
- `CursorHandle` that remembers a table index + row index + validity
  flag, with a shared-mutability reference to the table's row buffer
  so that writes via one cursor are visible to reads via another.
- `open_read_cursor`, `open_write_cursor`, `close_cursor`,
  `cursor_rewind`, `cursor_next`, `cursor_column`,
  `cursor_insert_row`, `cursor_delete_row`.

Shared-mutability note: the current signature of `cursor_insert_row`
does NOT pass `&Database`. Therefore the cursor must internally
carry a shareable, mutable handle to the table's rows. In Rust this
is idiomatically `Rc<RefCell<Vec<Vec<Value>>>>`; in C it is a
pointer into the `Database.tables` array. Either way, `Database`
itself exposes `tables: Vec<MemTable>` where each MemTable's `rows`
field is stored such that multiple cursors can both read and mutate
through it without cloning. **This is a change from mem-store v1**,
which captured a clone at open time; we now need cursor writes to be
visible to subsequent cursor reads on the same Database.

Deferred (these symbols MUST still be exported as stubs so the VDBE
code compiles; each stub returns `RuntimeCondition::IoError` and is a
runtime-only panic path — NOT `unimplemented!()`, since that kills
execution even when the opcode is never reached):

- `open_index_cursor`
- `cursor_seek_ge`, `cursor_seek_gt`, `cursor_seek_le`, `cursor_seek_lt`
- `cursor_seek_rowid`, `cursor_idx_next`, `cursor_idx_rowid`
- `cursor_prev`
- `cursor_update_row`

These stubs preserve the surface the rest of the tree compiles
against; they return `Err(RuntimeCondition::IoError)` rather than
panicking. A SELECT program that doesn't use them will never hit
them.

## Correctness pins

1. **database_new yields an empty catalog** — `Database { tables: [] }`
   or target-equivalent; no tables installed.
2. **database_install_table adds by name** — after install,
   `open_read_cursor(db, "t")` succeeds for the installed name and
   returns a fresh cursor.
3. **Replace-on-conflict** — calling `database_install_table` twice
   with the same name overwrites the existing entry (last-write-wins,
   probe-simple semantics).
4. **Table not found is TableNotFound** — `open_read_cursor` on an
   unknown table returns `Err(RuntimeCondition::TableNotFound)` if
   that variant exists, otherwise the closest equivalent (e.g.
   `StorageTableNotFound` per the core enum). Probe pin: use the
   exact variant the Rust `core::RuntimeCondition` declares — no
   new enum members invented.
5. **Fresh cursor is not valid** — immediately after `open_read_cursor`,
   `cursor.is_valid == false`. `cursor_column` on a not-yet-rewound
   cursor returns err.
6. **cursor_rewind on empty table returns Ok(false)** — cursor's
   `is_valid` stays false.
7. **cursor_rewind on non-empty table** — returns `Ok(true)`,
   `cursor.row_index == 0`, `cursor.is_valid == true`.
8. **cursor_next advances** — after rewind to row 0, `cursor_next`
   returns `Ok(true)` if row 1 exists (and sets `row_index = 1`,
   still valid), else `Ok(false)` (`is_valid = false`, `row_index`
   implementation-defined but consistent).
9. **cursor_next past end** — once `is_valid == false` (exhausted),
   calling `cursor_next` again returns `Ok(false)`; does not panic.
10. **cursor_column by index** — returns a CLONE of the stored Value
    (the cursor does not give out borrows into the database, so the
    caller can keep the value after advancing). Out-of-range index
    returns `Err(RuntimeCondition::IoError)`.
11. **close_cursor is a no-op** — safe to call on any cursor state;
    does not affect the Database.
12. **No panics on valid opcode sequences** — a VDBE program that
    does `OpenRead`, `Rewind`, loop `{Column..., Next}`, `Close`, `Halt`
    runs to completion without an `unimplemented!()` / panic,
    regardless of whether the table is empty.
13. **Deferred stubs are reachable without panic** — calling any
    of the deferred functions returns `Err(RuntimeCondition::IoError)`.
    No `unimplemented!()` macros, no `todo!()` macros. This keeps
    the binary robust to future VDBE opcodes that reach them
    unexpectedly.
14. **Exports match the current src-rust/storage.rs public surface** —
    every `pub fn` currently declared there must still exist, with
    the same signature. The implementation body is what changes;
    the interface is FROZEN by what the VDBE currently imports.
15. **cursor_delete_row keeps scan invariant** — after deleting the
    row at `row_index = i`, the cursor is positioned such that the
    NEXT call to `cursor_next` returns the row that logically
    follows the deleted one (i.e. does not skip the row that shifts
    into position i). Implementation: remove index i from the vec;
    if i > 0, set `row_index = i - 1`; if i == 0, set
    `row_index = u32::MAX` (sentinel meaning "before-first"). Then
    extend `cursor_next` to treat `row_index == u32::MAX` as
    "advance to 0" rather than "error". This is how a full-table
    `DELETE FROM t` manages to remove every row in one pass.

16. **database_install_table_with_pk records Rowid IndexSpec** —
    when `pk_column == Some(name)`, the resolved 0-based column
    index is recorded on the MemTable as `IndexSpec { kind: Rowid,
    columns: [idx] }` (replacing any prior IndexSpec list on the
    table — v1 mem-store only ever has at most one). When
    `pk_column == None`, the IndexSpec list is left empty.
    Subsequent `cursor_insert_row` calls on a table with a Rowid
    IndexSpec MUST use the inserted row's value at column `idx` as
    the rowid (provided that value is `Value::Integer`); other
    types fall back to auto-rowid (probe-grade — the spec leaves
    type coercion to v2). `cursor_seek_rowid` MAY use a
    target-local sorted index (e.g. BTreeMap) keyed by rowid for
    O(log N) lookup; targets without an ambient ordered map MAY
    fall back to linear scan (correctness over speed). Pin 14
    (frozen public surface) is amended: the public surface now
    additionally exports `database_install_table_with_pk`.
    `database_install_table` is preserved as a thin shim that
    forwards `pk_column = None`. The lib_bench harnesses in
    `src-c/examples/lib_bench.c` and `src-rust/examples/lib_bench.rs`
    obtain the `pk_column` argument by calling
    `pk_from_create_stmt` (parser leaf) on the parsed
    CreateTableStmt — they MUST NOT inline that detection.

17. **Transaction protocol — single-level INSERT-only rollback (v7-tx)** —
    `Database` gains a `txn_stack: Vec<TxnFrame>` field; v1 only ever
    holds zero or one frames. The state machine has two states:

        idle  ──BEGIN──▶  in_txn  ──COMMIT──▶  idle
                            │
                            └─ROLLBACK──▶ idle

    Allowed transitions:

    - `idle ──BEGIN──▶ in_txn`: `database_begin_transaction` snapshots
      `(rows.len, rowids.len)` for every currently-installed table and
      pushes the resulting `TxnFrame` onto `txn_stack`.
    - `in_txn ──COMMIT──▶ idle`: `database_commit_transaction` pops
      and discards the top `TxnFrame`. The current state is permanent.
    - `in_txn ──ROLLBACK──▶ idle`: `database_rollback_transaction`
      pops the top `TxnFrame`; for each `TableSnapshot { table_index,
      rows_len, rowids_len }` in the frame, truncates the corresponding
      `MemTable.rows` and `MemTable.rowids` to the recorded lengths.
      Targets that maintain auxiliary indexes (e.g. the pk_index used
      by `cursor_seek_rowid`) MUST synchronize them so post-rollback
      reads don't see ghost rowid entries — the simplest correct
      implementation is to clear and rebuild the index from the
      truncated rowids vector. Snapshot-frame `table_index` values
      that fall outside the current `tables` length (a table was
      somehow removed during the transaction — DDL-rollback is
      out of scope) are silently skipped.

    Error conditions (v1):

    - `BEGIN` while `txn_stack` is non-empty → `Err(RuntimeCondition::IoError)`.
      Nested transactions and SAVEPOINT support are deferred.
    - `COMMIT` or `ROLLBACK` while `txn_stack` is empty →
      `Err(RuntimeCondition::IoError)`. Implicit-commit-of-nothing is
      not modeled in v1; callers track open-state explicitly.

    v1 limitations (call out in publication context):

    - **INSERT-only rollback fidelity.** A `TableSnapshot` records only
      the row-vector lengths at BEGIN time. ROLLBACK truncates back to
      that length, which correctly undoes appended INSERTs. UPDATE
      mutates a row in-place and DELETE removes a row, neither of
      which a length-only snapshot can restore. v1 callers running
      UPDATE/DELETE inside a transaction will observe partial-state
      ROLLBACK behavior. Faithful UPDATE/DELETE rollback is a
      follow-up part (full row-content snapshotting or a
      copy-on-write rows vector — design open).
    - **Single-level only.** No nested SAVEPOINTs in v1; the stack
      structure is forward-compatible but the `BEGIN`-while-active
      check enforces depth ≤ 1.
    - **No DDL inside a transaction.** A `CREATE TABLE` issued between
      BEGIN and ROLLBACK is NOT undone (the new table remains).
      Acceptable for the L4 INSERT workload; flagged for follow-up.

    Probe rationale: the leaf is admitted to remove the structural
    asymmetry whereby leap's `lib_bench` skipped BEGIN/COMMIT entirely
    while mainline ran the full transactional bytecode (see
    `docs/POST-PUBLICATION-ROADMAP.md` P0.2). The bookkeeping cost
    must be comparable for an honest L4 measurement; the v1 limits
    above do not affect the INSERT-into-a-WAL-transaction workload
    that motivates this leaf.

## Version history (mem-store)

- **v1 (pre-2026-04-24):** read-only cursor; INSERT/UPDATE/DELETE stubs.
- **v2:** shared-mutability write path via Rc<RefCell> (Rust) / pointer-into-Database (C).
- **v3:** cursor_delete_row LIVE with scan-invariant preservation.
- **v4 (2026-04-24):** `MemTable.column_names` added; `database_install_table` takes a column_names list; `cursor_update_row` LIVE — resolves column names to row indices via MemTable.column_names and overwrites specified slots. If a target emission of an earlier version is still on disk, callers pass an empty column_names list to preserve existing behavior for INSERT/SELECT/DELETE; UPDATE will error with IoError (or SchemaMissing if the target adds that variant).
- **v5 (2026-04-24, α11):** rowid tracking — parallel `rowids` vector; explicit-rowid insert path via "rowid" column-name; `cursor_seek_rowid` LIVE.
- **v7-tx (2026-04-27, pin 17):** transaction stack. `Database` gains
  `txn_stack: Vec<TxnFrame>`; new entrypoints `database_begin_transaction`,
  `database_commit_transaction`, `database_rollback_transaction`. v1
  supports a single active frame (no nested SAVEPOINT) and INSERT-only
  rollback fidelity. UPDATE/DELETE inside a transaction is best-effort.
  Wired through lib_bench harnesses so leap-c / leap-rust runs the same
  per-statement bookkeeping as mainline at BEGIN/COMMIT/ROLLBACK
  boundaries (closes the L4 INSERT methodology asymmetry called out in
  POST-PUBLICATION-ROADMAP.md P0.2).
- **v6 (2026-04-24, α20):** view registry. `Database` gains a `views: Vec<ViewEntry>` field where `ViewEntry` holds `name: String` plus `select_sql: String` (the stored SELECT text). The compiler re-tokenizes + re-parses the stored text at each reference — views are resolved as synthetic derived-table sources, never mutate the `tables` array. New API:
  - `database_install_view(db, name, select_sql)` — overwrites any existing view with the same name (ASCII-case-insensitive).
  - `database_drop_view(db, name) -> bool` — returns true if a view was removed, false if no match (caller chooses whether a missing-view DROP is silent or an error).
  - `database_lookup_view(db, name) -> Option<&ViewEntry>` — read-only fetch.
  Views do NOT appear in `tables`; name collisions between a real table and a view are a caller-side error and are not prevented by storage. The VIEW entries are plain data — cycle detection lives in the compiler.

## Error return discipline

Every function whose return is `result<_, RuntimeCondition>` MUST
propagate the `RuntimeCondition` value itself, not a
target-idiomatic wrapper that hides it. Concretely:

- **Rust:** `Result<T, RuntimeCondition>` — not a custom error enum.
- **C:** the out-param pattern already returns `LeapRuntimeCondition`.
- **Go:** `(T, RuntimeCondition, bool)` or `(T, *RuntimeCondition)` —
  NOT `error` / `errors.New`. Callers use `errors.As` only when
  wrapping is unavoidable; default is direct return.
- **Zig:** `!union(T, RuntimeCondition)` or the mapping's error-union
  equivalent — not `anyerror`.
- **Python:** `Union[T, RuntimeCondition]` or raise a
  `RuntimeConditionError` that carries the condition as a field.

Rationale: VDBE opcode handlers dispatch on the condition value
(e.g. `InvalidCursor` vs `IoError` have different halt semantics).
Generic error types erase this dispatch and force string parsing.

## Clone allocator for Text / Blob reads

`cursor_column` returns `Value` by value. For `Value::Text` /
`Value::Blob`, that requires cloning the bytes out of the table
storage. Targets without an ambient allocator (Zig, some C layouts)
may need to thread an allocator into cursor_column. The shape
currently has no allocator parameter — resolution:

- **Rust / Go / Python:** allocators are ambient; no change.
- **C:** the existing `clone_value` helper in storage.c uses
  `malloc`/`strdup`; this is accepted since the C runtime provides
  a process-wide allocator.
- **Zig:** the runner's single-allocator harness (e.g.
  `std.heap.page_allocator`) suffices for behavioral smokes. For
  general use, either (a) cursor_column takes an explicit allocator
  in a future shape revision, or (b) the Zig mapping pins a
  well-known allocator at the module level. Current choice: (b)
  — document the allocator-at-module-level convention in Zig mapping,
  revisit if btree-backed storage surfaces richer requirements.

## Regeneration envelope

- Line budget: **~150-220 lines** of Rust. ~60 lines for the five
  live functions + struct defs; ~80 lines for the deferred stubs
  that return IoError; ~20 lines for docs.
- No dependencies beyond std.
- Public items: `Database`, `CursorHandle`, and every `pub fn`
  that currently exists in `src-rust/storage.rs`.

## Current src-rust/storage.rs public surface (frozen)

Every entry below must reappear in the regenerated file with the
same signature. Bodies for the five LIVE functions do real work;
the rest return `Err(RuntimeCondition::IoError)`.

LIVE (do the real thing):
- `open_read_cursor(db: &Database, table: &str) -> Result<CursorHandle, RuntimeCondition>`
- `close_cursor(handle: CursorHandle)` — no-op
- `cursor_rewind(cursor: &mut CursorHandle) -> Result<bool, RuntimeCondition>`
- `cursor_next(cursor: &mut CursorHandle) -> Result<bool, RuntimeCondition>`
- `cursor_column(cursor: &CursorHandle, col_index: u32) -> Result<Value, RuntimeCondition>`

Note: the current signature of `cursor_rewind`, `cursor_next`,
`cursor_column` does NOT take `&Database` — they must store enough
state on the CursorHandle to resolve rows on their own. The
generated implementation therefore either (a) stores an `Rc<>` /
`Arc<>` back to the table's row data on the cursor, or (b) stores
an owned clone of the row set on the cursor at rewind time. For
the probe, **(b) is fine and simpler**: at `cursor_rewind`, the
cursor can capture a clone of the row list; `row_index` walks it.
This keeps the cursor signature free of `&Database` — matching the
VDBE's existing calling convention.

STUBS (return `Err(RuntimeCondition::IoError)`):
- `open_write_cursor`, `open_index_cursor`
- `cursor_seek_ge`, `cursor_seek_gt`, `cursor_seek_le`, `cursor_seek_lt`
- `cursor_seek_rowid`, `cursor_idx_next`, `cursor_idx_rowid`
- `cursor_prev`
- `cursor_insert_row`, `cursor_update_row`, `cursor_delete_row`

Bodies for these stubs: `Err(RuntimeCondition::IoError)` (not
`unimplemented!()`). For functions that return `()` (like
`close_cursor`), keep the no-op body.

## Smoke probe

`src-rust/examples/select_compile_smoke.rs` is extended (or a
companion `select_behavioral_smoke.rs` created) to:

1. Construct a `Database`.
2. Install a table `t` with two columns and three rows:
   `[[Integer(1), Text("a")], [Integer(2), Text("b")], [Integer(3), Text("c")]]`.
3. Compile `SELECT * FROM t` with the matching TableSchema.
4. Execute the compiled program through `execute_program` (or
   whatever VDBE driver exists) with a `row_sink` that collects
   emitted rows into a Vec.
5. Assert the collected rows match the installed rows.
6. Repeat for `SELECT * FROM t WHERE a = 2` and assert exactly one
   row is emitted (`[Integer(2), Text("b")]`).

If the driver surface isn't directly invocable yet, the probe may
restrict itself to verifying that the LIVE functions are reachable
(no `unimplemented!()` triggered) by constructing a cursor, rewinding,
reading columns, and advancing — all without going through the VDBE.
That's still a strictly stronger claim than "stub".

## Pin 18 (v8-pager): Database gains a Pager field

Pin 18 closes the structural gap between the in-memory `Database` and
the path-backed page-cache + WAL state owned by
`/parts/storage/parts/wal-bridge`. Every `Database` carries a `Pager`
field; in-memory mode constructs the Pager via `pager_new_in_memory()`
and consults it without doing I/O. Path-backed mode (`open_database_at`
in fileformat-read, file-format leaf) constructs a `JournalMode::Wal`
Pager and threads it into the same field.

This pin is structural only. Cursor signatures are NOT changed by
pin 18. The cursor-signature migration that threads `&mut Pager` /
`&Pager` through every cursor op lands as a separate pin (the
wal-bridge leaf documents the surface; the mem-store cursor functions
inherit the parameter list from there).

### Type changes

- `Database` gains `pager: Pager` (imported from
  `/parts/storage/parts/wal-bridge`).
- A companion record `DatabaseTablesView` exposes mutable references
  to every Database field EXCEPT `pager`. The view is what
  `split_pager_mut` returns alongside `&mut Pager` — see below.

### Function additions

- `database_new()` continues to return a fresh empty Database; it
  additionally initializes `pager` to `pager_new_in_memory()` per
  wal-bridge's contract.
- `Database::split_pager_mut(&mut self) -> (DatabaseTablesView, &mut Pager)`
  — returns disjoint mutable borrows of the non-pager fields and the
  Pager. The disjoint-borrow guarantee is essential: every VDBE opcode
  handler that mutates rows (insert/update/delete) AND consults the
  Pager (B-tree page faulting in pin 19+; cursor-threading in 18.1c)
  must hold both borrows simultaneously. The Rust borrow checker
  accepts this via field-destructuring; equivalent disjoint-borrow
  patterns exist in C (struct-field pointer aliasing), Zig (separate
  `*` fields), Go (separate fields), Python (no aliasing, just access
  both attributes). Targets emit the helper using their natural idiom.

### Database::clone() semantics with Pager

Cloning a `Database` MUST produce a fresh in-memory Pager regardless
of the source's journal mode. Path-backed databases are constructed
via `open_database_at` (fileformat-read / wal-bridge), NEVER via
`Clone`. The cloned Database carries no WAL state, no lock state, no
cache entries. This avoids the otherwise-unsolvable problem that
`LockManager` and the WAL writer state are not cloneable (Mutexes,
file handles), and it codifies the existing semantics of `backup.rs`
and the test fixtures that clone Database snapshots: a clone is a new
logical instance, not a duplicated handle on the original's on-disk
artifacts.

### Default semantics

`Database::default()` produces the same value as `database_new()` —
empty tables, empty views, empty txn_stack, in-memory Pager.

### Numbered Correctness pins (continued from pin 17)

**P18.1.** Every `Database` has a `pager` field. There is no path
through the public surface that produces a `Database` with `pager`
absent (no `Option<Pager>`).

**P18.2.** `database_new()` initializes `pager` via
`pager_new_in_memory()`. The journal mode of a freshly constructed
in-memory Database is `Memory`; `synchronous` is `Off`.

**P18.3.** `Database::split_pager_mut` returns disjoint mutable
references. Targets that cannot express disjoint mutable references
in safe code (Python, Go) emit a structurally-equivalent pair of
attribute references; the contract is that mutations through one do
not invalidate the other.

**P18.4.** `Database::clone()` (or its target equivalent) MUST emit a
fresh in-memory Pager on the cloned instance. Path-backed databases
are constructed via `open_database_at`, never via `Clone`. A test
that opens a path-backed Database, clones it, and asserts the clone's
journal_mode is `Memory` MUST pass.

**P18.5.** The pager field is structural only at pin 18. No cursor
function in mem-store v7-tx changes signature at this pin. The
cursor-signature migration (every cursor op grows a `&mut Pager` or
`&Pager` parameter) is owned by `parts/storage/parts/wal-bridge`
§"Cursor-signature migration" and lands as a separate pin.

### Out of scope at pin 18

- Cursor signature migration. Pin 18.1c (separate pin in wal-bridge).
- File-backed Pager construction inside `database_new()`. The
  in-memory default is the only path; path-backed Pagers are produced
  by `open_database_at` (fileformat-read leaf) and assigned into the
  Database after construction.
- Multi-process WAL coordination. wal-shm, pin 20+.

## Pin 16-amend (2026-04-27): pk_col_name + pk_index + database_clone_table

Two pre-existing target-local lifts on the Rust mem-store emission are
promoted to the spec at this pin so regeneration round-trips cleanly
without dropping caller-visible structure.

### MemTable.pk_col_name (option<string>)

Mirrors the column name of the `Rowid` IndexSpec when present.
`database_install_table_with_pk` sets it to `Some(name)`;
`database_install_table` leaves it `None`. Targets emit it as a public
optional-string field on `MemTable`. Callers that need O(1) name-based
PK resolution (the compiler's predicate-pushdown + SeekRowid-emission
path is one such caller) read it directly.

This is redundant with `IndexSpec { kind: Rowid, columns: [n] }`'s
`columns[0]` (which is the resolved index, not the name) — the spec
preserves both because they answer different questions:

- "What column index is the PK?" → `IndexSpec.columns[0]`
- "What column NAME is the PK?" → `pk_col_name`

The compiler's pk-map population and the cursor's rowid-alias hoist
both read the name; `cursor_seek_rowid` reads the index.

### MemTable.pk_index (auxiliary rowid → row_index map)

Maintained alongside `rowids` so `cursor_seek_rowid` is O(log N)
instead of O(N). Logically `{ i64 → u32 }`. Targets choose the
concrete container:

- Rust: `Rc<RefCell<BTreeMap<i64, u32>>>` (shared mutability matches
  `rows` / `rowids`).
- Python: dict.
- Go: map.
- C/Zig: hash table or sorted vector — implementor's choice.

The contract is:
1. Lookup is sub-linear in row count.
2. The map stays consistent with `rowids` after every
   insert/delete/update — every i in [0, rowids.len()) MUST satisfy
   `pk_index[rowids[i]] == i`.
3. `cursor_seek_rowid` MUST consult the map; fallback to linear
   `rowids` scan is a target-local fallback for not-yet-populated
   tables and is not required.

External direct reads of the map are permitted (the field is public)
but the recommended access path for snapshot-style use is
`database_clone_table` (see below); the recommended access path for
single-rowid lookup is `cursor_seek_rowid`.

### database_clone_table(db, table_name) -> Result<MemTable>

Owned deep-copy of a named MemTable. Materializes rows / rowids /
pk_index / pk_col_name into a fresh MemTable that does not alias the
source's reference-counted state. Subsequent writes to the source
MUST NOT be visible through the returned clone.

Used by `/parts/storage/parts/backup-engine` to capture a snapshot at
backup-init time. Without this method, the backup engine would have
to reach into pk_index / rows / rowids directly and clone-out each
container, leaking target-private representations into a sibling part.

Returns `err(TableNotFound)` if no table by that name exists.

### Numbered Correctness pins (continued)

**P16a-1.** `pk_col_name` is `Some(name)` iff `database_install_table_with_pk`
was called with `Some(name)`. `database_install_table` always leaves
it `None`.

**P16a-2.** `pk_index` is consistent with `rowids` after every
mem-store-mutating call: for every i in [0, rowids.len()),
`pk_index.lookup(rowids[i]) == i`.

**P16a-3.** `database_clone_table` produces a value whose subsequent
mutations do not affect the source MemTable, and whose state at the
moment of the call exactly equals the source's then-current state
(rows-by-value, rowids-by-value, pk_index-by-value, pk_col_name-by-value).

**P16a-4.** `cursor_seek_rowid` consults `pk_index` for sub-linear
performance. Targets MAY include a linear-scan fallback for
backwards-compat with rows installed before pk_index was populated;
the fallback's existence does not satisfy P16a-4 by itself.
