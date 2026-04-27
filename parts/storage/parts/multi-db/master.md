---
name: storage/multi-db
kind: leaf
shapes: ./shapes.json
inherits:
  - /parts/storage/parts/file-format/master.md
  - /parts/storage/parts/pager/master.md
  - /parts/storage/parts/wal/master.md
  - /spec/durability.spec.md
---

# Part: storage/multi-db

Multi-database catalog for a single connection. Owns the binding
between **logical schema names** (`main`, `temp`, plus zero or
more attached aliases) and **per-schema storage state** (pager +
WAL + open file handle).

This part is the storage-side counterpart to the
`parser/attach-stmt` and `parser/detach-stmt` parsers. It does
NOT define a SQL statement; it defines the runtime state and the
operations the executor calls when an `ATTACH` or `DETACH`
statement runs, plus the **two-phase commit** glue that keeps
multi-database transactions atomic.

The on-disk constraint is mainline compatibility: the master
journal format MUST round-trip with mainline SQLite (a leap
master journal is replayable by mainline; a mainline master
journal is replayable by leap-WAL recovery). See pin 7.

## Why a catalog

A single connection can read and write more than one database
file. Mainline SQLite admits up to 10 attached databases by
default (`SQLITE_MAX_ATTACHED`); leap matches that bound. Every
qualified name `schema.table.column` resolves through this
catalog. Every multi-database transaction commits or rolls back
atomically via a master journal that names every per-schema
journal file involved.

## Catalog layout

```
DbCatalog
├── slot[0] = main          (always present, never detachable)
├── slot[1] = temp          (always present, never detachable)
├── slot[2..N] = attached   (0 ≤ N-2 ≤ 8 in v1; total cap 10)
│
└── transaction state: per-schema commit/rollback journal map +
                       master-journal path when active
```

Each `SchemaSlot` owns:
- `name` — owned logical schema name (case-folded for lookup;
  preserved as-written for diagnostics).
- `path` — owned filesystem path of the database file.
- `pager` — opaque per-schema Pager instance (see
  `/parts/storage/parts/pager`).
- `wal` — opaque per-schema WalState (see
  `/parts/storage/parts/wal`); absent for `:memory:` schemas.
- `is_readonly` — boolean.
- `attach_seq` — monotonically-assigned attach-order index, used
  ONLY for name-resolution walk order (see pin 5). NOT stable
  across detach-then-reattach.

## Constants

- `MAX_ATTACHED_DBS = 10` — total catalog slots, matching
  mainline.
- `MAIN_SLOT = 0` — fixed index of the `main` schema.
- `TEMP_SLOT = 1` — fixed index of the `temp` schema.
- `MASTER_JOURNAL_SUFFIX_LEN = 11` — the literal `-mj` plus 8 hex
  digits (`-mjXXXXXXXX`).

## Declared shapes (in `shapes.json`)

- `DbCatalog` — opaque. Owns the slot list, the master-journal
  state machine, and a per-connection RNG handle for master
  journal naming.
- `SchemaSlot` — opaque (Pager + WalState are opaque, so the slot
  is too).
- `MultiDbError` — single-channel error with named conditions
  (see pin 14).
- Functions: `catalog_open_main`, `catalog_attach`,
  `catalog_detach`, `catalog_resolve`, `catalog_begin`,
  `catalog_commit`, `catalog_rollback`, `catalog_close`.

## State machine

Catalog lifetime:

```
[fresh] --catalog_open_main(main_path)--> [open, slot[0]=main, slot[1]=temp]
[open]  --catalog_attach(path, name)----> [open with N+1 slots]    (N+1 ≤ 10)
[open]  --catalog_detach(name)----------> [open with N-1 slots]    (busy-guarded)
[open]  --catalog_close()---------------> [closed]
```

Transaction lifetime (within `[open]`):

```
[idle] --catalog_begin(write?)--> [in_txn, dirty_slots = {}]
[in_txn] --executor writes to slot k--> dirty_slots ∪= {k}
[in_txn] --catalog_commit()-->
    if |dirty_slots| ≤ 1:
        single-slot fast path: commit that pager / WAL directly
    else:
        2PC path:
          1. allocate master journal at <main_path>-mj<8hex>
          2. write absolute paths of every per-slot journal
          3. fsync master journal
          4. for each dirty slot: commit its per-slot journal
             (rollback-mode) or its WAL (wal-mode), syncing each
          5. unlink master journal
        --> [idle]
[in_txn] --catalog_rollback()-->
    for each dirty slot: rollback its per-slot journal / WAL
    --> [idle]
```

Crash recovery on `catalog_open_main` checks for any
`<main_path>-mj*` file. If present, the recovery driver in
`/parts/storage/parts/pager` (its `recover_master_journal`
routine — see pager spec) is invoked to replay or finalize the
2PC outcome.

## Operations

### catalog_open_main(main_path) -> DbCatalog | MultiDbError

Open / create the main database and bind a TEMP schema. Slot 0
is `main` with a per-slot pager + WAL; slot 1 is `temp` with a
fresh anonymous pager (no WAL, no on-disk file in v1 —
implementation MAY use a memory-backed pager). Drives master
journal recovery if a stale `-mj*` file is present (see
`/spec/durability.spec.md`).

### catalog_attach(catalog, db_path, schema_name) -> unit | MultiDbError

Open `db_path` as a new schema slot. Validations (in order):

1. catalog state must be `[open]` and NOT `[in_txn]`.
2. `schema_name` must not already exist in any slot
   (case-folded compare).
3. number of currently-bound slots must be < `MAX_ATTACHED_DBS`.
4. `db_path` must be openable for read/write (or read-only,
   matching the connection's mode).

On success: a fresh Pager is opened on `db_path`, a fresh
WalState is opened on `{db_path}-wal` (per
`/parts/storage/parts/wal`). The slot is appended at the next
free index, given a fresh `attach_seq` (monotone counter never
reused). On any failure no slot is appended.

### catalog_detach(catalog, schema_name) -> unit | MultiDbError

Remove the named schema slot. Validations (in order):

1. catalog state must be `[open]` and NOT `[in_txn]`.
2. `schema_name` must NOT be `main` or `temp`.
3. the slot must exist.
4. the slot must have NO open cursors. The executor passes a
   busy-snapshot (count of cursors per slot) into the catalog;
   if the count for the target slot is non-zero, raise
   `SchemaBusy`.

On success: close the slot's WAL (checkpoint pending frames per
`/spec/durability.spec.md`), close its pager, drop the slot from
the slot list. Slot indices of higher-indexed slots compact
DOWN (`attach_seq` does not). The case-folded name becomes
re-attachable in a subsequent `catalog_attach`.

### catalog_resolve(catalog, schema_name) -> SchemaIdx | MultiDbError

Look up a schema by name (case-folded ASCII compare). Returns
the slot index in the current slot list. Slot indices are NOT
stable across `catalog_detach`; the compiler MUST re-resolve per
statement (see pin 11 here and `/parts/compiler/parts/qualified-names`
pin 13).

### catalog_walk_unqualified(catalog) -> list<SchemaIdx>

Iterator: returns `[main, temp, attached-by-attach_seq-asc]`.
Used by `/parts/compiler/parts/qualified-names` to resolve
unqualified table references (the FIRST slot whose schema
contains a matching object wins).

### catalog_begin / catalog_commit / catalog_rollback

See state machine above. `catalog_commit` is the entry point
for the master-journal protocol when `|dirty_slots| ≥ 2`.

## Master journal format (mainline-compatible)

A master journal is a small file located alongside the main
database at `<main_path>-mj<8hex>`. Its byte layout:

```
[N null-terminated absolute paths of per-slot journals]
[u32 big-endian: total bytes consumed by the path list]
[u32 big-endian: master journal magic = 0x9A737CB0]
[u32 big-endian: simple checksum (sum of u32 words in the path list)]
```

The trailing `(length, magic, checksum)` triple makes the file
self-validating: a per-slot journal `J` references the master
journal by name, and a recovery driver reading `J` must verify
that the master file exists, has the magic, and lists `J` by
absolute path. If any check fails, the master journal is
considered finalized and per-slot journals roll back
independently.

Mainline SQLite uses the same magic value and self-validating
trailer (see fileformat2.html "Atomic Commit"). Bidirectional
compatibility is the proof.

## Correctness pins

1. **Slot count bounded** — `MAX_ATTACHED_DBS = 10` total slots
   including `main` and `temp`. `catalog_attach` raises
   `TooManyAttached` when adding an 11th slot.
2. **Reserved slot indices** — `main` is always slot 0, `temp`
   is always slot 1. Both indices are stable for the lifetime
   of the catalog. `catalog_detach` of either raises
   `CannotDetachReserved`.
3. **Per-schema isolation** — every slot owns its own Pager and
   its own WalState. Cross-slot reads / writes go through
   distinct file handles; there is no shared page cache. The
   storage stunt's binary-equivalence claim is preserved
   per-schema.
4. **Walk order is `main → temp → attached-in-attach-order`** —
   `catalog_walk_unqualified` yields exactly this sequence.
   Used by name resolution; FIRST hit wins (mainline-equivalent).
5. **`attach_seq` is monotone, never reused** — even after
   detach-then-reattach the new slot gets a FRESH `attach_seq`
   greater than every previously-issued value. Walk order is
   determined by `attach_seq` ascending.
6. **2PC kicks in only at |dirty_slots| ≥ 2** — single-slot
   commits skip the master journal entirely (mainline parity
   for performance).
7. **Master journal is mainline-compatible** — magic
   `0x9A737CB0`, big-endian length + checksum trailer,
   null-terminated absolute paths. A mainline SQLite running
   recovery on a leap-written master journal MUST succeed; a
   leap recovery on a mainline-written master journal MUST
   succeed. Verified by the
   `tests/cross-build/master_journal_*` corpus (both
   directions).
8. **Master journal naming** — `<main_path>-mj` followed by
   exactly 8 lowercase hex digits drawn from the connection's
   RNG. The 32 bits of randomness are sufficient for crash
   uniqueness within a single host; the 8-hex form matches
   mainline.
9. **Master journal cleanup** — committed iff every per-slot
   journal sync has succeeded; THEN the master journal is
   unlinked. A crash before the unlink leaves the master
   journal on disk; recovery on next open replays per-slot
   journals OR drops them based on the master journal's
   presence (matches mainline atomic-commit protocol).
10. **catalog_attach is forbidden inside a transaction** —
    raises `AttachInTransaction`. Mainline parity.
11. **Slot indices NOT stable across detach** — after a
    `catalog_detach` of a slot with index `k`, slots above `k`
    compact DOWN. Compilers MUST NOT cache a `SchemaIdx` across
    statement boundaries; they re-resolve via
    `catalog_resolve(name)` per statement
    (`/parts/compiler/parts/qualified-names` pin 13 enforces).
12. **DETACH busy-guard at the executor** — `catalog_detach`
    checks the executor-supplied open-cursor count for the
    target slot and raises `SchemaBusy` if non-zero. The
    parser does NOT enforce this; the executor MUST pass an
    accurate snapshot. Open prepared statements that hold a
    cursor on the slot MUST be finalized before DETACH
    succeeds (mainline parity).
13. **Cross-schema FK rejected at DDL-exec** — when CREATE
    TABLE / ALTER TABLE introduces a foreign-key constraint
    whose referenced table lives in a different schema slot,
    the DDL executor raises `CrossSchemaForeignKey`. The
    parser admits the syntax; the compiler's name-resolution
    detects the cross-schema reference; the storage layer
    rejects the install. v1 has no plan to lift this — single
    file per schema simplifies recovery.
14. **KEY clause rejected at executor** — when
    `AttachStmt.key_expr` is `present` AND evaluates to a
    non-empty value, the executor raises
    `EncryptionNotSupported`. An empty / NULL key is treated
    as if absent (mainline parity for the unencrypted build).
15. **MultiDbError named conditions** — `TooManyAttached`,
    `DuplicateSchemaName`, `SchemaNotFound`,
    `CannotDetachReserved`, `SchemaBusy`,
    `AttachInTransaction`, `OpenFailed`,
    `CrossSchemaForeignKey`, `EncryptionNotSupported`,
    `MasterJournalIo`, `MasterJournalCorrupt`. Each maps to an
    idiomatic error type per target.
16. **Language-neutral interface** — every shape uses the
    neutral type vocabulary (`string`, `u32`, `option`,
    `result`, opaque types, lists). No mention of
    `std::path::Path`, `Result<T,E>`, `char *`, `FILE *`, or
    target allocator semantics. Targets map opaque types to
    their idiomatic owned forms.

## Regeneration envelope

- This part owns NO emission today (spec-only leaf, parallel to
  the way `wal/master.md` originally landed). Targets attach in
  a follow-up wave once the master-journal protocol has a
  cross-build smoke.
- When emission lands: line budget ~600-900 lines per target
  (catalog plus 2PC driver). Pager and WAL are imported, not
  re-implemented.

## Smoke probes (deferred until emission lands)

```text
1. open main → 2 slots (main + temp).
2. attach 'a.db' AS x → 3 slots; resolve('x') = 2.
3. attach 9 more → 11th raises TooManyAttached.
4. detach 'x' → 2 slots; resolve('x') raises SchemaNotFound.
5. detach 'main' → CannotDetachReserved.
6. begin write; insert into main; insert into x; commit
   → master journal written, both syncs succeed, master
   unlinked.
7. begin write; insert into main; insert into x; KILL between
   per-slot syncs → on next open, recovery sees master journal,
   replays / aborts atomically.
8. attach 'a.db' AS y; cursor open on y; detach 'y'
   → SchemaBusy.
```
