---
name: storage/wal-bridge
kind: leaf
shapes: ./shapes.json
inherits:
  - /parts/storage/parts/wal/master.md
  - /parts/storage/parts/page-cache/master.md
  - /parts/storage/parts/mem-store/master.md
  - /parts/storage/parts/file-format/master.md
  - /parts/storage/parts/fileformat-read/master.md
  - /parts/storage/parts/fileformat-write/master.md
  - /parts/storage/parts/locking/master.md
emits:
  rust:   { path: src-rust/storage_pager.rs }
  c:      { path: src-c/storage/wal_bridge.c, headers: [src-c/storage/wal_bridge.h] }
  zig:    { path: src-zig/storage/wal_bridge.zig }
  go:     { path: src-go/storage/wal_bridge.go }
  python: { path: src-python/storage/wal_bridge.py }
---

# Part: storage/wal-bridge — Pager + WAL commit bridge

Pin 18 (v8-wal). The integration leaf that wires `mem-store` to `wal/`
through a real **page cache** and a real **commit bridge**: at COMMIT,
dirty pages flow from the cache into WAL frames and an `fsync` honors
the connection's `synchronous` level. Recovery on open replays the
WAL into the cache. PRAGMA `journal_mode=WAL` flips a real bit;
PRAGMA `synchronous=NORMAL|FULL|OFF|EXTRA` controls real fsync timing.

This is the spec the L4 INSERT bench depends on for honest comparison
with mainline-WAL — every COMMIT pays one fsync; mainline pays one
fsync; same disk-cost contract.

**Phase 18.1 (Rust prototype) is canonical and validated.** Phase 18.2
sibling emission to C / Zig / Go / Python is **in scope** as of
2026-04-27 — the Rust prototype proved the spec coherent end-to-end
(L4 100k INSERT 94.9k qps, mainline integrity_check ok, reopen
recovery green). Multi-target emission slots are declared at the
end of this leaf; the wal/ leaf defines the byte-format surface and
this leaf defines the cursor-signature migration and the bridge to
mem-store across all 5 targets.

## Why a new leaf (not just extending mem-store)

The cursor-signature change (every cursor op takes a `&mut Pager`)
ripples through ~50-100 VDBE call sites. mem-store already owns the
in-memory cursor; pager owns the page cache + WAL state. Splitting
them keeps the in-memory mode usable (tests, ephemeral DBs, the
`:memory:` path) and keeps the file-backed mode honest. The Pager is
the single chokepoint where reads fault pages from disk-or-WAL and
writes mark pages dirty.

## State

A `Pager` instance owns:

- `db_path: string` — canonical path to the main database file.
- `page_size: u32` — fixed at open; matches the file header.
- `cache: PageCache` — the LRU page cache (page-cache leaf).
- `wal: option<WalState>` — present iff `journal_mode == Wal`.
- `journal_mode: JournalMode` — `Memory`, `Delete`, `Wal`.
  `Memory` means no on-disk durability (RAM-only databases).
  `Delete` is the rollback-journal mode (atomic rename at commit;
  no journal file in v1, fast since we always rewrite the whole
  file). `Wal` is the WAL-mode covered by this leaf.
- `synchronous: SyncLevel` — `Off`, `Normal`, `Full`, `Extra`.
  Controls fsync gating per the W15..W18 pins in `parts/storage/parts/wal/`.
- `lock: LockManager` — process-local lock state from `parts/storage/parts/locking/`.

A `Database` (mem-store) gains an optional `pager: option<Pager>`.
When `pager == None` the database is in-memory (existing v7-tx
semantics). When `pager == Some(_)` the database is path-backed and
COMMIT goes through this leaf.

## Cursor-signature migration (the invasive change)

Every cursor-mutating function gains a `&mut Pager` parameter; every
cursor-read function gains a `&Pager`. The migration applies
target-wide, but Phase 18.1 only emits the Rust signatures.

### Frozen v1 surface (with new pager param)

All five LIVE functions in mem-store v7 grow a `pager` argument:

```
open_read_cursor (db: &Database,                          table: &str)             -> Result<CursorHandle, RuntimeCondition>
open_write_cursor(db: &Database,                          table: &str)             -> Result<CursorHandle, RuntimeCondition>
cursor_rewind   (cursor: &mut CursorHandle, pager: &mut Pager)                     -> Result<bool,        RuntimeCondition>
cursor_next     (cursor: &mut CursorHandle, pager: &mut Pager)                     -> Result<bool,        RuntimeCondition>
cursor_column   (cursor: &CursorHandle,     pager: &Pager,     col: u32)           -> Result<Value,       RuntimeCondition>
cursor_insert_row(cursor: &mut CursorHandle, pager: &mut Pager, db: &mut Database,
                                              row: Vec<Value>)                      -> Result<i64, RuntimeCondition>
cursor_delete_row(cursor: &mut CursorHandle, pager: &mut Pager, db: &mut Database) -> Result<(),          RuntimeCondition>
cursor_update_row(cursor: &mut CursorHandle, pager: &mut Pager, db: &mut Database,
                                              column_names: &[String],
                                              new_values: &[Value])                  -> Result<(), RuntimeCondition>
```

`open_read_cursor` and `open_write_cursor` keep their old signature —
they only resolve a table name and don't touch pages until rewind.

`close_cursor` keeps its old signature — it's a no-op.

The deferred stubs (open_index_cursor, cursor_seek_*, cursor_idx_*,
cursor_prev) gain `pager: &mut Pager` for forward compat but their
bodies still return `Err(RuntimeCondition::IoError)` in Phase 18.1.

### VDBE call-site migration

Every VDBE opcode handler that calls a cursor function MUST thread
`pager` through. The pager comes from `&mut Database` (via
`db.pager.as_mut().expect("pager not initialized")` for path-backed
sites, or via a `Pager::new_in_memory()` fallback for in-memory mode).
Concretely the Rust `vdbe.rs` opcodes affected:

- `OpenRead`, `OpenWrite` — no change (cursor-open doesn't touch pager).
- `Rewind`, `Next` — pass `pager`.
- `Column` — pass `pager`.
- `InsertRow`, `DeleteRow`, `UpdateRow` — pass `pager` and `&mut db`.
- `Close` — no change.
- All `Seek*` opcodes — pass `pager`.

The execution loop holds `&mut Database` already (for txn frame
push/pop). Add a borrow-split: `let (db_rest, pager) = db.split_pager_mut()`
helper that returns `(&mut Database without pager, &mut Pager)` —
needed because Rust borrow checker cannot share a `&mut Database`
with a `&mut Pager` when both live inside the same struct.
**This split is the spec's hardest Rust ergonomics call.** The
helper is part of the public mem-store surface, declared in
shapes.json.

## In-memory Pager (the always-safe fallback)

Every `Database::new()` constructs a Pager in `JournalMode::Memory`
mode. This Pager has:

- `db_path = ""` (empty)
- `cache: PageCache` with capacity 1 (page-cache pin 1 forbids capacity 0;
  capacity 1 is the smallest legal value and is never exercised in
  Memory mode anyway since no page faults happen)
- `wal = None`
- `journal_mode = Memory`
- `synchronous = Off`

In-memory mode every cursor op delegates to the existing v7-tx
in-memory implementation; the Pager is consulted but does no I/O.
This preserves backward compatibility for every existing test and
benchmark that uses `database_new()`.

## File-backed Pager (the WAL path)

`open_database_at(path)` — existing function — is extended:

1. Open or create the main file at `path`.
2. Decode the database header; extract `page_size`.
3. Construct a `PageCache` with capacity (configurable; default 2000
   pages — `2000 * 4096 = 8 MiB`).
4. Open the WAL: `wal_open(path, page_size)`.
5. Replay any committed frames in the WAL into the in-memory tables
   AND into the page cache (so subsequent reads see WAL state).
6. Construct the `Pager` with `journal_mode = Wal` (default for
   file-backed) and `synchronous = Normal` (default).
7. Attach the Pager to the Database.

The replay step works as follows: for each `(page_number, frame_no)`
in `wal.wal_index`, fetch the frame's page image, write it into
`cache.put(page_number, image, dirty=false)`. Subsequent
`pager_get_page(p)` calls return the WAL'd image instead of the
on-disk image — the WAL is authoritative until checkpoint.

## Pager API

```
fn pager_new_in_memory()                                     -> Pager
fn pager_new_file_backed(path: &str)                         -> Result<Pager, RuntimeCondition>

fn pager_get_page (p: &Pager,     page_no: u32)              -> Result<PageImage, RuntimeCondition>
fn pager_get_page_mut(p: &mut Pager, page_no: u32)           -> Result<PageImage, RuntimeCondition>
fn pager_mark_dirty(p: &mut Pager, page_no: u32)             -> Result<(),       RuntimeCondition>
fn pager_set_journal_mode(p: &mut Pager, mode: JournalMode)  -> Result<(),       RuntimeCondition>
fn pager_set_synchronous(p: &mut Pager, level: SyncLevel)    -> Result<(),       RuntimeCondition>

fn pager_begin_transaction (p: &mut Pager)                   -> Result<(), RuntimeCondition>
fn pager_commit_transaction(p: &mut Pager, db: &Database)    -> Result<(), RuntimeCondition>
fn pager_rollback_transaction(p: &mut Pager)                 -> Result<(), RuntimeCondition>

fn pager_checkpoint(p: &mut Pager)                           -> Result<(), RuntimeCondition>
fn pager_close     (p: Pager)                                -> Result<(), RuntimeCondition>
```

`pager_get_page` consults `cache.get(p)`. On hit: return the cached
image. On miss: if `journal_mode == Wal`, call
`wal_read_page(state, db_path, p)`; if Some, cache it and return. If
None or non-WAL mode, read the page from the main file at offset
`(p - 1) * page_size`, cache it, return.

`pager_get_page_mut` is `pager_get_page` followed by
`cache.mark_dirty(page_no)`. Callers MUST `pin` the page before
mutation and `unpin` after; this leaf does not enforce that — the
B-tree leaf does.

## Commit bridge (the bench-relevant path)

`pager_commit_transaction(p, db)` is the heart of pin 18. The flow:

```
if p.journal_mode == Memory:
    return Ok(())   # in-memory; nothing to flush

if p.journal_mode == Wal:
    # Pin 19 implementation: the page cache is the source of truth.
    # Cursor write paths (insert/update/delete) have already mutated
    # in-memory page images via pager_get_page_mut, marking each
    # touched page dirty. COMMIT iterates only the dirty set —
    # never the whole database. See parts/storage/parts/btree-write.

    p.lock.wal_acquire(WalLockSlot::Write, WalLockKind::Exclusive)?

    let wal = p.wal.as_mut().expect("WAL state present in Wal mode")
    let dirty: Vec<(u32, PageImage)> = p.cache.flush_dirty()
                                              # ascending page_no order, clears bits

    for (pn, img) in &dirty:
        wal_append_frame(wal, pn, &img)?

    # Commit: bake new_db_size into the last frame; fsync per W9/W15/W16.
    # P19-8: new_db_size == p.db_size_pages (the running total updated
    # by pager_allocate_page; written into page-1 offset 28 at commit time).
    let new_db_size = p.db_size_pages
    let info = wal_commit(wal, &p.db_path, new_db_size)?

    # The fsync inside wal_commit is gated on p.synchronous;
    # implementations MUST consult p.synchronous before issuing
    # the fsync syscall (see W15..W18).

    # 6. Release the writer lock.
    p.lock.wal_release(WalLockSlot::Write)?

    return Ok(())

if p.journal_mode == Delete:
    # Rollback-journal-mode equivalent: serialize the database
    # to a temp file, atomic-rename, fsync per p.synchronous.
    # Phase 18.1 reuses the existing `serialize_database_to_with_sync`
    # entry point.
    return serialize_database_to_with_sync(db, &p.db_path, p.synchronous)
```

**Pin 19 closes the per-commit O(db_size) walker.** The page cache is
the live row store for path-backed databases; cursor writes mutate
page images in place via `pager_get_page_mut`, and COMMIT iterates
only `cache.flush_dirty()`. The boundary spec for the cursor write
path lives in `parts/storage/parts/btree-write/master.md`.

`pager_rollback_transaction(p)`:
- If `journal_mode == Wal`: call `wal_rollback(state)` to discard
  pending frames, `cache.clear()` to drop dirty in-memory pages,
  release the writer lock if held. The next read re-faults from
  disk-or-WAL via `pager_get_page`.
- If `journal_mode == Memory` or `Delete`: no Pager-side work; the
  mem-store v7-tx in-memory rollback handles row truncation.

`pager_checkpoint(p)`:
- If `journal_mode != Wal`: no-op.
- Else acquire `WalLockSlot::Checkpoint` exclusive, call
  `wal_checkpoint(state, &p.db_path)`, release. The WAL file is
  reset (salts roll, header rewritten); the cache retains its
  entries (they remain clean after the checkpoint flushed them
  to the main file).

`pager_close(p)`:
- If `journal_mode == Wal`: best-effort `pager_checkpoint(p)` before
  drop. If checkpoint fails (e.g. another process holds READ),
  silently leave the WAL — recovery on next open replays it.
- Drop the cache.
- Close the main file handle.

## fsync discipline

Every fsync site in this leaf consults `p.synchronous`. The matrix:

| Site                                 | OFF | NORMAL | FULL | EXTRA |
|--------------------------------------|-----|--------|------|-------|
| WAL frame append (interior)          |  no |   no   |  no  |  no   |
| `wal_commit` (commit-frame fsync)    |  no |   no   |  yes |  yes  |
| `wal_checkpoint` (db file fsync)     |  no |  yes   |  yes |  yes  |
| File-format atomic-rename (Delete)   |  no |  yes   |  yes |  yes  |
| Parent-dir fsync after WAL replace   |  no |   no   |  no  |  yes  |

**This matrix is normative.** Pin 18 callers MUST pass `p.synchronous`
to any function that issues an fsync, and that function MUST
short-circuit per the table.

For the L4 INSERT bench: mainline default `synchronous=NORMAL`,
`journal_mode=WAL`. NORMAL gates per-commit fsync OFF; checkpoint
fsync ON. Leap matches: at NORMAL, `wal_commit` skips the per-commit
fsync; checkpoint pays it. **This is mainline-equivalent semantics.**
The bench harness MUST set both PRAGMAs identically on both sides.

## PRAGMA wiring

`PRAGMA journal_mode=WAL` (statement compiled by the pragma part)
calls `pager_set_journal_mode(p, Wal)`:
- If transitioning from `Memory` to `Wal`: open the WAL file via
  `wal_open(path, page_size)`, populate `p.wal`.
- If transitioning from `Delete` to `Wal`: ditto.
- If already `Wal`: no-op.

`PRAGMA synchronous=NORMAL|FULL|OFF|EXTRA` calls
`pager_set_synchronous(p, level)`. Pure assignment; no side effects.
Subsequent commits/checkpoints honor the new level.

`PRAGMA journal_mode` and `PRAGMA synchronous` (no value) are
read-only queries returning the current mode/level as a string.

## Recovery on open

Sketched in §"File-backed Pager"; expanded:

1. `wal_open(path, page_size)` returns `WalState` with the live
   region computed (mx_frame, wal_index built).
2. For each `(page_no, frame_no)` in `wal_index`:
   `image = wal_read_page(&state, path, page_no)?.expect(...)`
   `cache.put(page_no, image, dirty=false)`
3. Decode the database header from page 1 (via cache, which now
   sees the WAL'd image if present). Use this to enumerate tables
   via the existing `deserialize_database_from_bytes` flow — but
   route page reads through `pager_get_page` instead of slicing
   raw bytes. (Pin 19 amendment: the deserializer is cache-aware —
   recovery reads page 1 via `pager_get_page(p, 1)`, decodes
   sqlite_master, and faults each table root through the cache on
   demand. mem-store is populated lazily on first cursor_rewind,
   per P19-12.)

The Phase 18.1 bootstrap is correct but inefficient: we read the
WAL, materialize it into a temp file, then re-read that file into
mem-store. A future phase routes deserialization through the cache
directly. Document this in §Out of scope.

## Numbered Correctness pins

**P18.1. Pager exists for every Database.** `database_new()`
constructs a `Pager` in `JournalMode::Memory` mode and stores it
on the Database. `open_database_at(path)` constructs a
`JournalMode::Wal` pager. There is no path through the public
surface that produces a `Database` with `pager == None`.

**P18.2. In-memory Pager is a no-op for every Pager API.** Every
`pager_*` function called on a `JournalMode::Memory` Pager either
returns `Ok(())` immediately (commit/rollback/checkpoint) or
returns an empty/cached page (get_page on a never-faulted page is
acceptable to return a zero-image; tests don't exercise this path).

**P18.3. WAL frames written at commit have salts matching the WAL
header.** Verified by W5 in `parts/storage/parts/wal/`. The bridge
MUST NOT bypass `wal_append_frame`'s checksum/salt logic.

**P18.4. fsync gating per-synchronous.** The matrix in §"fsync
discipline" is normative. A target that calls fsync on a
`SyncLevel::Off` Pager fails this pin.

**P18.5. Recovery is idempotent.** Opening a path-backed Database,
reading every row, closing without writing, reopening — yields
identical row-set on every iteration. Verified by smoke probe.

**P18.6. Mainline-readable post-commit.** After
`pager_commit_transaction` on a `JournalMode::Wal` Pager, running
mainline `sqlite3 path "PRAGMA integrity_check"` MUST return `ok`.
The WAL file produced MUST be either replayed by mainline (if
mainline opens with WAL mode auto-detected) or checkpointable
into the main file before mainline reads it. Verified by smoke probe.

**P18.7. WAL writer lock held across the append-and-commit
window.** Between the first `wal_append_frame` of a transaction
and `wal_commit`, the Pager MUST hold `WalLockSlot::Write`
Exclusive. Released on success or on rollback. A second writer
opening the same Database in the same process MUST observe
`LockError::Busy` until release.

**P18.8. Cursor signature migration is uniform.** Every cursor-op
in the v7-tx public surface gains exactly one new parameter
(`pager: &mut Pager` for write paths, `pager: &Pager` for read
paths). No cursor-op silently accepts a default Pager; callers
MUST thread one explicitly.

**P18.9. Borrow-split helper exists.**
`Database::split_pager_mut(&mut self) -> (&mut DatabaseTables, &mut Pager)`
returns disjoint mutable borrows. The `DatabaseTables` view exposes
every Database field except `pager`. This helper is the only
sanctioned path for VDBE opcode handlers to obtain a `&mut Pager`
while still holding a `&mut Database`.

**P18.10. JournalMode and SyncLevel are owned by core.** The enums
live in `parts/core/shapes.json` (or are imported from the existing
pragma part). This leaf does not redefine them. The wal-bridge
shapes.json declares the Pager record and the Pager API surface
only.

**P18.11. wal-shm is NOT consulted in Phase 18.1.** Single-process
single-writer scope. The `parts/storage/parts/wal-shm/` leaf exists
but is not depended on by this leaf. Multi-process WAL ships in
pin 20+.

**P18.12. PRAGMA journal_mode actually flips a bit.** A test that
opens a Database in `JournalMode::Memory`, calls
`pager_set_journal_mode(Wal)`, runs an INSERT in a transaction, and
inspects the on-disk path MUST observe a `{path}-wal` file with at
least one frame after commit. The current STMT_NOOP behavior is
explicitly forbidden.

**P18.13. PRAGMA synchronous actually controls fsync.** A test that
sets `synchronous=Off` and runs 10K INSERTs in a single transaction
MUST complete strictly faster than the same workload at
`synchronous=Full` on a non-trivial filesystem (e.g. ext4, APFS).
This is a soft pin (timing-sensitive); the hard form is "fsync
syscall count from `strace`/`fs_usage` differs across levels".

**P18.14. Eq-harness pins behavior across modes.** A workload
executed with `(journal_mode=Wal, synchronous=Normal)` produces the
same row-set as the same workload with `(journal_mode=Memory)`. The
on-disk artifacts differ; the observable query results do not.

## Smoke probe (Phase 18.1, Rust only)

`src-rust/examples/wal_bridge_smoke.rs`:

1. Construct a path-backed Database via `open_database_at("/tmp/leap-wb-1.db")`.
2. `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL`.
3. `BEGIN; CREATE TABLE t(id INTEGER PRIMARY KEY, payload TEXT); INSERT INTO t VALUES(1, 'a'),(2, 'b'),...,(100, 'z'); COMMIT`.
4. Assert `/tmp/leap-wb-1.db-wal` exists and is non-empty.
5. Close the Database via `pager_close`.
6. Run mainline `sqlite3 /tmp/leap-wb-1.db "PRAGMA integrity_check; SELECT COUNT(*) FROM t"` — expect `ok` and `100`.
7. Reopen via `open_database_at` (WAL replay path) and `SELECT COUNT(*) FROM t` — expect `100`.

Smoke counts: 7-step demo, expect all 7 PASS for the leaf to be
considered green at Phase 18.1.

## Out of scope (Phase 18.3+)

- `wal-shm`-mediated multi-process WAL. Pin 20+.
- `PASSIVE` vs `RESTART` vs `TRUNCATE` checkpoint variants. v1 is
  PASSIVE.
- Concurrent reader admission via `READ(k)` slots. v1 single-writer
  serializes everything.
- Prefetch / read-ahead in the page cache.
- Cache-aware `deserialize_database_from`. Phase 18.1 uses a temp-file
  bootstrap.

## Regeneration envelope

- Spec line budget: ≤ 600 lines (this file).
- shapes.json: ≤ 200 lines (Pager record + API surface +
  JournalMode/SyncLevel enums if not already in core).
- Rust target leaf size: 700-900 lines for `src-rust/storage_pager.rs`.
- Touches mem-store: cursor signature change (every LIVE function
  grows a pager param). Estimate +30 lines for the borrow-split helper.
- Touches vdbe.rs: ~50-100 call sites for the threading. The change
  is mechanical: each cursor call gets `pager` threaded from the
  surrounding `Database`.
- Existing tests: every `cursor_*` call site in tests gains a Pager.
  Helper: `pager_new_in_memory()` lets tests stay short.

## Phase pins

- **Phase 18.1** — Rust prototype. THIS leaf. Cursor migration,
  Pager scaffolding, WAL commit bridge, recovery, PRAGMA wiring.
  Validated by smoke probe + corpus regression.
- **Phase 18.2** — 4-target sibling emission (C/Zig/Go/Python). The
  WAL byte-format encoder/decoder lifts from
  `parts/storage/parts/wal/` (currently Rust-only) to all 5 targets.
  Cursor signature migration on each target.
- **Phase 19** — In-place B-tree mutation (lifted; see
  `parts/storage/parts/btree-write/master.md`). Per-commit cost drops
  from O(db_size) to O(dirty_pages); multi-commit and L4 workloads
  approach mainline parity.
- **Phase 20** — `wal-shm` multi-process coordination. Cross-process
  reader/writer protocols.

## Open questions for follow-up

1. **Cache capacity policy.** Phase 18.1 fixes capacity at 2000
   pages. SQLite's default is 2000 pages too, but a runtime PRAGMA
   `cache_size` adjusts it. Add to pin 18.5? Currently deferred.
2. **WAL auto-checkpoint threshold.** Mainline auto-checkpoints
   when WAL exceeds 1000 frames. Phase 18.1 does NOT auto-checkpoint;
   `pager_close` does a best-effort one. Add pin?
3. **Synchronous=EXTRA directory fsync site.** The matrix says
   "after WAL replace" — but Phase 18.1 doesn't replace the WAL,
   only resets it in place. The directory fsync site is more
   relevant for `Delete` mode's atomic rename. Confirm during
   Rust prototype.
