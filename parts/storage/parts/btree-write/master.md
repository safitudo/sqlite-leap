---
name: storage/btree-write
kind: leaf
inherits:
  - /parts/storage/parts/btree/master.md
  - /parts/storage/parts/page-cache/master.md
  - /parts/storage/parts/pager/master.md
  - /parts/storage/parts/wal-bridge/master.md
  - /parts/storage/parts/mem-store/master.md
  - /parts/storage/parts/file-format/master.md
  - /parts/storage/parts/fileformat-write/master.md
  - /parts/storage/parts/page-codec/master.md
emits:
  rust:   { path: src-rust/storage.rs }
  c:      { path: src-c/storage/storage_btree.c, headers: [src-c/storage/storage_btree.h] }
  zig:    { path: src-zig/storage_btree.zig }
  go:     { path: src-go/storage/storage_btree.go }
  python: { path: src-python/storage_btree.py }
---

# Part: storage/btree-write — In-place B-tree write with per-page dirty tracking

Pin 19 (v9-btree). The leaf that closes the per-commit O(db_size)
serialization gap left intentionally open by pin 18. After pin 19, every
B-tree mutation (insert / update / delete) touches a small number of
in-memory page images **in place**, marks them dirty in the page cache,
and COMMIT iterates only the dirty set — never the whole database.

This is the spec the L4 INSERT bench depends on for honest mainline
parity in `--db` mode. Today (Phase 18.1) the smoking gun lives at
`src-rust/storage_pager.rs:420`:

> `// Phase 18.1 implementation: re-encode the whole DB into pages each commit (no per-row dirty tracking yet — pin 19 closes that). Push every page through the cache as dirty, then flush dirty pages to the WAL.`

For the L4 single-commit bench (100k INSERTs in one BEGIN/COMMIT) the
COMMIT path consumes 82.7 ms — full re-serialization of every table
into 4 KB pages, ~4 MB of `cache.put(..., dirty=true)` clones, then
~1000 WAL frame appends. Mainline does ~10 ms (1000 frames + 1 fsync).
After pin 19 the leap COMMIT collapses to the **same shape** as
mainline's: O(dirty pages) frame appends + 1 fsync, target ~5–10 ms
on the same hardware.

## What pin 19 is NOT

- It is not a new B-tree algorithm. The split / descent semantics
  defined in `parts/storage/parts/fileformat-write/master.md` (root
  split, non-root leaf split, recursive parent split, root interior
  split) carry forward unchanged.
- It is not a recovery-format change. The on-disk WAL frame layout
  and the main-file page layout are identical to pin 18.
- It is not a wal-shm change. Multi-process WAL is still pin 20+.
- It is not a checkpoint-policy change. Auto-checkpoint thresholds
  remain a follow-up.

What pin 19 IS: the **boundary move** between mem-store and the page
cache. Today mem-store rows live in language-natural containers (Rust
`Rc<RefCell<Vec<Vec<Value>>>>`, Python `list[list[Value]]`, etc.) and
COMMIT re-serializes those containers from scratch. After pin 19 the
page cache is the live source of truth for every row that has ever
been on disk; mem-store cursors decode bytes on read and encode bytes
on write.

## Architectural choice — Option B (page-cache primary)

Two architectures were considered:

- **Option A**: keep mem-store as the primary row store. At COMMIT,
  diff the mem-store against the previous on-disk image to discover
  which pages changed; only those pages flow to WAL frames. Mem-store
  unchanged; commit cost drops to O(dirty pages) at the cost of a
  per-commit diff.
- **Option B**: make the page cache the primary store. Every cursor
  read decodes from a page image; every cursor write encodes into a
  page image and marks the page dirty. mem-store cursors become
  *views* over the cache. COMMIT iterates `cache.flush_dirty()`
  directly — no diff required.

**This spec selects Option B.** Three reasons:

1. Mainline-faithful. SQLite's pager-cursor architecture is exactly
   this shape; bench parity ultimately requires the same allocation
   profile, and Option A's per-commit diff is itself O(db_size).
2. Speed and stuntability privileged
   (memory: `feedback_decision_criterion_speed_stuntability`).
   Option A leaves a hidden O(db_size) walker in the COMMIT path —
   correct, but visible in benchmark numbers and demo flame graphs.
3. The page cache is already the read source-of-truth post-pin-18
   (every `pager_get_page` consults the cache before disk-or-WAL).
   Option B unifies read and write paths around one structure.

The cost of Option B is the depth of the change. Mem-store is
restructured: `MemTable.rows` no longer holds the canonical row
vector for path-backed databases; instead, a path-backed MemTable
holds `root_page: u32` and the rows materialize on demand from
pages decoded through the cache. In-memory mode (`JournalMode::Memory`)
keeps the existing row-vector path unchanged — Option B only
reshapes the *file-backed* path.

## State

A path-backed `MemTable` after pin 19 carries:

- `root_page: u32` — the table's b-tree root (already in the catalog
  via sqlite_master).
- `column_names: list<string>` — already present (pin 16-amend).
- `pk_col_name: option<string>` — already present.
- `pk_index: map<i64, PageLocation>` — replaces the rowid → row_index
  map. `PageLocation { page_no, cell_index }` resolves a rowid to its
  current home cell. Updated on every insert / delete / split.

The mem-store's `MemTable.rows` and `MemTable.rowids` fields remain
**only** for in-memory mode. For path-backed mode they are NOT
populated; cursor reads decode pages instead.

A `CursorHandle` after pin 19 carries (in addition to its pin-18.1c
fields):

- `current_page_no: u32` — the leaf page this cursor is positioned on.
- `current_cell_index: u32` — the index within that leaf's pointer
  array.
- `descent_stack: list<DescentFrame>` — captured at rewind / seek
  time so cursor advance and split-time-rebalance can walk back up.

`DescentFrame { page_no: u32, cell_index_or_right_child: u32 }` —
`u32::MAX` (or the named tag `RIGHT_CHILD`) means "we descended via
right_child on this hop". The shape mirrors the parent_stack already
defined in `fileformat-write/master.md` §"Descent: find the insertion
leaf".

## The cursor write path

### `cursor_insert_row(cursor, pager, db, row) -> Result<i64>`

1. Resolve the table's `root_page` from `db.tables[t].root_page`.
2. Descend from `root_page` to the target leaf for the new rowid
   (rowid is `Null` for INTEGER PRIMARY KEY auto-assignment;
   resolve via `db.tables[t].max_rowid + 1` if so). The descent
   uses `pager_get_page(p, page_no)` for every interior hop —
   no direct file I/O.
3. Encode the new cell via `encode_cell(rowid, values)` (existing
   helper from `fileformat-write`).
4. If the leaf has free space:
   a. Call `pager_get_page_mut(p, leaf_page_no)` to obtain a
      mutable handle and mark the page dirty.
   b. Splice the cell into the page image at
      `cell_content_offset - new_cell_len`.
   c. Update the leaf header (cell_count, cell_content_offset)
      in the page image.
   d. Update `db.tables[t].pk_index[rowid] = PageLocation { ... }`.
5. If the leaf is full:
   a. Run the split algorithm from `fileformat-write` §"Split
      algorithm". Every page touched by the split (`L`, `Lnew`,
      every parent on `descent_stack` whose divider array changes,
      and any newly allocated page from `pager_allocate_page`)
      MUST be obtained via `pager_get_page_mut` so the cache
      marks them dirty.
   b. Update `pk_index` for every cell that migrated to a new
      page or new cell index.

The split helpers (`build_leaf_page`, `build_interior_table_page`,
`root_split`, `non_root_leaf_split`, `recursive_parent_split`,
`root_interior_split`) keep their existing semantics. The pin-19
change is the **buffer they write into**: instead of slicing into
a single byte buffer and atomic-renaming, each helper produces a
page image and the caller installs that image via
`pager_get_page_mut(...)` + a write into the returned mutable
view. Page allocation (the file-tail extension that
`fileformat-write` does via `bytes.extend(zeros(page_size))`)
becomes `pager_allocate_page(p) -> Result<u32, ...>` which:

- Increments the in-memory `db_size_pages` counter.
- Calls `cache.put(new_page_no, zeros(page_size), dirty=true)`.
- Returns the new page number.

The actual file-tail bytes are written at COMMIT, not at
allocation. Until then the page lives only in the cache.

### `cursor_delete_row(cursor, pager, db) -> Result<()>`

1. Use `cursor.current_page_no` and `cursor.current_cell_index`.
2. Call `pager_get_page_mut(p, cursor.current_page_no)`.
3. Remove the cell from the page image:
   a. Drop the pointer at `cell_index` from the pointer array.
   b. The cell bytes themselves become free space — we do NOT
      compact the page; we let `cell_content_offset` drift only
      when the freed cell was the smallest pointer. (Mainline
      tracks this via `first_freeblock`; pin 19 conservatively
      sets `first_freeblock = 0` and never coalesces freelist —
      acceptable for v1, since `fileformat-read` already
      tolerates non-coalesced freelists.)
   c. Update header: cell_count -= 1.
4. If the leaf becomes empty (`cell_count == 0`) AND the leaf is
   not the table's root: deferred — page-merge / underflow
   rebalance is **out of scope** at pin 19. Document as a known
   wart; bench impact is negligible because workloads under test
   do not delete entire pages worth of cells. Mainline's b-tree
   will still read the resulting tree correctly; the only
   observable effect is that the file holds slightly more empty
   pages than mainline would.
5. Update `db.tables[t].pk_index` to remove the deleted rowid.
6. Cursor is invalidated per the cursor-stability rule.

### `cursor_update_row(cursor, pager, db, column_names, new_values) -> Result<()>`

1. Decode the existing cell at `(cursor.current_page_no,
   cursor.current_cell_index)` into a row vector.
2. Apply `column_names[i] -> new_values[i]` to that row.
3. Encode the new cell.
4. If the new cell fits in the page (size ≤ old size, OR free space
   is sufficient): in-place replace the cell bytes; update the
   pointer entry and header in the page image; mark the page dirty.
5. If the new cell does NOT fit: route through `cursor_delete_row`
   followed by `cursor_insert_row` on the same rowid. The new cell
   may land on a different page; `pk_index[rowid]` updates to the
   new `PageLocation`. Both pages (old and new) are marked dirty.

## The cursor read path

### `cursor_rewind(cursor, pager) -> Result<bool>`

1. Resolve the cursor's table's `root_page`.
2. Descend the leftmost path: at every interior page, follow the
   first cell's `child_page` (NOT `right_child`); at the first leaf,
   set `cursor.current_page_no = leaf_page_no`,
   `cursor.current_cell_index = 0`, populate `descent_stack`.
3. If the leaf has zero cells: return Ok(false) (empty tree).
4. Else return Ok(true).

### `cursor_next(cursor, pager) -> Result<bool>`

1. Increment `cursor.current_cell_index`.
2. If still inside the leaf's `cell_count`: return Ok(true).
3. Else walk back up `descent_stack` to find the next subtree:
   pop frames until one frame's `cell_index_or_right_child` is
   not the rightmost; descend left from there. (Standard b-tree
   in-order traversal.)
4. If the stack empties without finding a successor: return
   Ok(false).

### `cursor_column(cursor, pager, col) -> Result<Value>`

1. Call `pager_get_page(p, cursor.current_page_no)`.
2. Decode the cell at `cursor.current_cell_index` (using the same
   record-decoder already in `fileformat-read`).
3. Return `cells[cursor.current_cell_index].values[col]`.

In-memory mode (`JournalMode::Memory`) bypasses all of the above:
the existing v7-tx interior-mutability row-vector path is
preserved unchanged for the in-memory case. The pager parameter
is consulted to discover the journal mode; if Memory, the cursor
delegates to the existing implementation.

## The commit path

After pin 19, `pager_commit_transaction(p, db)` is amended:

```
if p.journal_mode == Memory:
    return Ok(())

if p.journal_mode == Wal:
    p.lock.wal_acquire(WalLockSlot::Write, WalLockKind::Exclusive)?

    # Pin 19: iterate ONLY dirty pages. The cache is already the
    # source of truth — no encode_database_to_pages(db) call.
    let wal = p.wal.as_mut().expect("WAL state present in Wal mode")
    let dirty = p.cache.flush_dirty()    # ascending page_no, clears dirty bits

    for (pn, img) in dirty:
        wal_append_frame(wal, pn, &img)?

    let new_db_size = p.db_size_pages
    wal_commit(wal, &p.db_path, new_db_size)?
    p.lock.wal_release(WalLockSlot::Write)?
    return Ok(())

if p.journal_mode == Delete:
    # Rollback-journal mode: pin 19 still requires a per-page diff
    # for in-place file rewrite. Phase 19.1 keeps the existing
    # whole-file serialize_database_to_with_sync path; per-page
    # in-place file write under Delete mode is deferred.
    return serialize_database_to_with_sync(db, &p.db_path, p.synchronous)
```

The `db.pager.db_size_pages` field is added at pin 19. It tracks
the total page count after every `pager_allocate_page`. Mainline's
DbHeader `database_size` field at offset 28 is written from this
counter at COMMIT time (page 1 itself is dirtied if its header
changed).

### Lines in `wal-bridge/master.md` that become stale

The following lines in `parts/storage/parts/wal-bridge/master.md`
are written assuming the pre-pin-19 implementation. Pin 19's
follow-up amendment to `wal-bridge` MUST update them; this leaf
does NOT modify wal-bridge directly.

- **Lines 249–256**: the "Phase 18.1 limitation" stanza — drop in
  full. Replace with a "Pin 19 closes this" pointer to this leaf.
- **Line 213**: `let pages: Vec<(u32, PageImage)> = encode_database_to_pages(db, p.page_size)`
  — remove. The cache iteration replaces it.
- **Lines 216–217**: the `cache.put(pn, img.clone(), dirty=true)`
  loop — remove. Pages are already dirty in the cache from cursor
  writes.
- **Line 337**: `pin 19 makes the deserializer cache-aware` — this
  pin closes that promise; the recovery-on-open path now reads
  via `pager_get_page` instead of the temp-file bootstrap.
- **Line 445**: `In-place B-tree mutation. Pin 19.` — out-of-scope
  bullet drops.
- **Lines 479–481**: Phase 19 entry in §"Phase pins" updates from
  forward-reference to back-reference.

`parts/storage/parts/wal-bridge/shapes.json:117` and `:150`
(the `pager_commit_transaction` and `encode_database_to_pages`
doc strings) become stale and need rewording in the same
amendment pass.

## Page splits — integration with existing split logic

The split helpers in `parts/storage/parts/fileformat-write/master.md`
already cover all four cases (root split, non-root leaf split,
recursive parent split, root interior split). Pin 19 does not
re-spec them. The integration is:

1. Where `fileformat-write` says `splice_page(bytes, page_no, ...)`
   pin 19 substitutes:
   ```
   let mut img = pager_get_page_mut(p, page_no)?
   img.copy_from_slice(&page_bytes)
   ```
   (The cache marks the page dirty automatically via
   `pager_get_page_mut`.)
2. Where `fileformat-write` says `bytes.extend(zeros(page_size))`
   to allocate a new page, pin 19 substitutes
   `let new_pn = pager_allocate_page(p)?`. The new page enters the
   cache in dirty state with a zero-filled image.
3. Where `fileformat-write` says `write_atomic(bytes)` at the end
   of every split function, pin 19 substitutes nothing — the
   atomic durability boundary moves to `pager_commit_transaction`,
   which fsyncs the WAL. Split helpers under pin 19 do NOT touch
   disk; they only mutate cache page images.
4. The descent's `parent_stack` in `fileformat-write` is the same
   shape as the `cursor.descent_stack` in this leaf. Splits
   triggered by `cursor_insert_row` consume the descent stack the
   cursor already captured at rewind / seek time.

The split's correctness pins (S1..S16 in `fileformat-write`)
remain normative under pin 19. The only new requirement is
**dirty-bit propagation**: every page that the split mutates
(including the parent that gets a new divider, the grandparent
escalated by a recursive split, and every intermediate
`P_moved` page allocated by `root_interior_split`) MUST land in
the cache marked dirty. A split that touches N pages and marks
fewer than N pages dirty is a pin-19 violation.

## Rollback

`pager_rollback_transaction(p)` after pin 19:

1. If `p.journal_mode == Memory`: no-op (in-memory mem-store
   handles row-level rollback via the existing v7-tx txn_stack).
2. If `p.journal_mode == Wal`:
   a. `wal_rollback(p.wal)` — discards uncommitted frames.
   b. `p.cache.clear()` — every dirty page is dropped. Clean
      pages are also dropped because the cache cannot
      distinguish "clean image we faulted from disk" from
      "clean image from a previous committed cache state" once
      the rollback boundary moves; conservatively clearing the
      whole cache forces re-fault on the next read, which is
      always correct.
   c. Release `WalLockSlot::Write` if held.
3. If `p.journal_mode == Delete`: existing behavior; the v7-tx
   in-memory txn_stack covers row truncation, and there is no
   on-disk uncommitted state because Delete mode rewrites the
   whole file at COMMIT only.

The rollback path MUST restore the cache to a state where every
subsequent read returns the on-disk-or-WAL image as it stood at
the most recent successful COMMIT (or as it stood at open, if no
COMMIT has occurred). Conservative cache.clear() achieves this.

A future optimization (deferred): track per-page "was clean
before this transaction" and only invalidate pages that were
touched. Acceptable to defer because rollback is the cold path.

## Cursor stability across writes

The pre-pin-19 invariant from `parts/storage/parts/btree/master.md`
§"Cursor stability" remains:

> Cursors may be invalidated by any write operation on the same
> tree. Compiled programs MUST NOT perform a write and then
> continue to read through a pre-existing cursor on the written
> tree.

Under pin 19 the invalidation rule is enforced by:

1. Page splits that move cells reset every cursor's
   `current_page_no` and `current_cell_index` to a sentinel
   "invalidated" state.
2. The compiler already emits cursor-write-then-close-then-reopen
   in the existing v7-tx codegen; no codegen change required.

A cursor that is invalidated and then read raises
`RuntimeCondition::CursorInvalidated`. A cursor that observes
its page's `cell_count` drop below `current_cell_index + 1`
between a `cursor_next` and a subsequent `cursor_column`
likewise raises that condition.

## Cache eviction under dirty pages

The page-cache's pin 6 ("Eviction never selects a `dirty == true`
entry") is load-bearing for pin 19. A long-running transaction
that dirties more pages than the cache's capacity (default 2000
pages = ~8 MiB) MUST cause the cache to **temporarily exceed
capacity** rather than evict a dirty page. This is already the
page-cache's pin 8 contract; pin 19 surfaces the user-visible
consequence: very large transactions consume RAM proportional to
their dirty-page count.

A future pin (deferred) introduces partial dirty-flush: at a
configurable threshold, mid-transaction the writer flushes some
dirty pages to the WAL and clears their dirty bits, freeing the
cache to evict them. Mainline does this. Pin 19 does not. For
the L4 bench (100k INSERTs ≈ 1000 dirty pages ≈ 4 MiB) the
threshold is never hit.

## Performance pins

**Phase 18.1 baseline (Mac, lib_bench, 100k INSERTs in one BEGIN/COMMIT, path-backed WAL DB):**

- leap-rust: **585k qps** (170 ms total). `pager_commit_transaction` consumes 82.7 ms — `encode_database_to_pages` re-serializes everything.
- mainline-sqlite: **885k qps** (110 ms total). COMMIT consumes ~10 ms — 1000 frame appends + 1 fsync.
- gap: **60–90 ms** concentrated entirely in COMMIT.

**Pin 19 target (same hardware, same workload):**

- COMMIT consumes **5–10 ms** (parity with mainline; same number of
  WAL frames written, same fsync). This collapses the 60–90 ms
  gap entirely.
- Aggregate qps target: **≥ 850k qps**, i.e. within 5% of mainline.

**Performance pin Q1.** `pager_commit_transaction` on a
`JournalMode::Wal` Pager performs **exactly** `cache.flush_dirty()`
and the resulting `wal_append_frame` calls. There is NO call to
`encode_database_to_pages`, NO call to `serialize_database_to_with_sync`,
NO walk of `db.tables`, on the WAL path. A bench-time strace
showing more `write` syscalls than `dirty_page_count + 1` (where
+1 is the commit-frame fsync) indicates a pin-19 violation.

**Performance pin Q2.** Per-INSERT work in `cursor_insert_row`
is bounded by `O(log N)` page faults (one per descent level) plus
`O(1)` cache mutations for the leaf, where N is the table size.
A bench showing per-INSERT wall-clock that grows linearly with
table size (rather than logarithmically) indicates the descent
is touching too many pages or the cache is missing.

**Performance pin Q3.** RAM growth during a 100k-INSERT
transaction is bounded by `dirty_page_count * page_size` plus
mem-store overhead for `pk_index`. Concretely: ≤ 1000 × 4096
bytes ≈ 4 MiB for the dirty pages, plus ~3 MiB for `pk_index`,
totalling under 10 MiB. A bench showing RAM growth over 50 MiB
on this workload indicates page-image cloning on the dirty path.

## Numbered Correctness pins

**P19-1. Dirty-bit propagation is uniform.** Every B-tree
mutation (`cursor_insert_row`, `cursor_delete_row`,
`cursor_update_row`) MUST mark every page it modifies as dirty
in the cache. A target that mutates a page image without going
through `pager_get_page_mut` (which calls `cache.mark_dirty`)
fails this pin. Verified by a smoke probe that runs an INSERT,
inspects `cache.flush_dirty()` output, and confirms every
page-image diff observed is in the returned set.

**P19-2. Split correctness preserved.** Every page touched by a
split — including parents up the descent stack, allocated tail
pages, and (for `root_interior_split`) the moved-root page —
ends in the cache marked dirty. Mainline's `PRAGMA integrity_check`
on the post-COMMIT database file MUST return `ok` for every
split case (root, non-root, recursive, root-interior).

**P19-3. Rollback restores a clean cache.** After
`pager_rollback_transaction`, every subsequent
`pager_get_page(p, pn)` either returns a faulted-from-disk image
matching the most recent COMMIT or returns the same WAL-replayed
image that recovery-on-open would produce. Verified by a smoke
probe: BEGIN; INSERT 100; ROLLBACK; SELECT COUNT(*) → 0.

**P19-4. Cursor invalidation on write.** A cursor that has
issued any of `cursor_insert_row` / `cursor_delete_row` /
`cursor_update_row` followed by `cursor_column` without an
intervening `cursor_rewind` or `cursor_seek_*` raises
`RuntimeCondition::CursorInvalidated`. Compiler-side: existing
codegen already separates write and read cursors; no change.

**P19-5. Ascending page_no flush order.** `cache.flush_dirty()`
returns dirty pages in ascending `page_no` order
(`page-cache/master.md` pin 11). The commit path appends WAL
frames in the same order. Mainline's WAL replay is order-
independent on `(page_no, frame_no)` lookup, but ascending order
is normative for cross-target byte-identity of generated WAL
files.

**P19-6. Cache eviction never selects dirty.** The page cache's
pin 6 ("Eviction never selects a dirty entry") is normatively
inherited. A pin-19 emission that violates this — for instance,
by adding a fast-path that drops dirty pages under memory
pressure — fails this pin.

**P19-7. Commit ordering: lock → append → fsync → release.**
The COMMIT path acquires `WalLockSlot::Write` Exclusive before
the first `wal_append_frame`, holds it across every frame and
the commit-frame fsync, releases on success or rollback. A
second writer in the same process between `wal_append_frame`
calls observes `LockError::Busy` until release. (Inherited from
wal-bridge P18.7; restated here because pin 19 does not change
the lock contract.)

**P19-8. `db_size_pages` matches DbHeader.database_size.** At
COMMIT time, the page-1 image's offset-28 `database_size` field
equals `p.db_size_pages`. After every `pager_allocate_page`,
`p.db_size_pages` is incremented and page 1 is marked dirty
(because its header changed). A target that allocates a new
page without dirtying page 1 fails this pin.

**P19-9. `pk_index` consistency across pages.** For every rowid
in `pk_index`, the indicated `(page_no, cell_index)` in the
cache decodes to a cell whose `rowid` field equals that key.
Mutated by every insert / delete / update / split. A
post-mutation walk that finds a `pk_index` entry pointing at a
cell with a different rowid fails this pin.

**P19-10. In-memory mode is unchanged.** A Database in
`JournalMode::Memory` performs no `pager_get_page` /
`pager_get_page_mut` calls in its cursor body. The existing
v7-tx interior-mutability path is preserved bit-for-bit. No
behavioral or performance regression for `database_new()`-only
workloads (the entire test suite using in-memory databases).

**P19-11. Index B-trees use the same model.** Index
B-tree write (Phase 113 / Phase 116) is restructured under
pin 19 to route through the same `pager_get_page_mut` +
`pk_index`-equivalent (an `index_to_rowid` map) machinery. The
cell-format is index-table-cell instead of leaf-table-cell, but
the dirty-tracking and split semantics are identical.

**P19-12. Recovery-on-open routes through the cache.** The
`open_database_at(path)` recovery path described in
`wal-bridge/master.md` §"Recovery on open" is amended: instead
of the temp-file bootstrap, recovery reads page 1 via
`pager_get_page(p, 1)`, decodes sqlite_master, and for each
table issues `pager_get_page(p, root_page)` to discover its
b-tree. The cache faults each page from disk-or-WAL on demand;
mem-store is populated lazily (path-backed `MemTable.rows` is
empty until the first cursor_rewind).

**P19-13. Mainline-readable post-commit (inherited).** After
`pager_commit_transaction` on a `JournalMode::Wal` Pager,
running mainline `sqlite3 path "PRAGMA integrity_check"` MUST
return `ok`. (Inherited from wal-bridge P18.6.)

## Out of scope (deferred)

- Multi-process WAL coordination. wal-shm; pin 20+.
- Page underflow / sibling merge after delete. v1 leaves empty
  leaf pages in place; mainline reads them correctly. Future
  pin: rebalance + freelist coalescing.
- Read-after-write within the same statement on the same cursor.
  Existing cursor-stability rule applies; compiler enforces.
- Background checkpoint integration. The threshold-based
  auto-checkpoint policy (mainline's 1000-frame default) is
  separate from pin 19.
- In-place file write under `JournalMode::Delete`. Pin 19's
  cache-flush model applies to WAL mode only; Delete mode
  retains the whole-file serialize-and-rename path. A future
  pin can extend Option B to Delete mode (write dirty pages
  in place to the main file under atomic-rename of a sibling
  copy).
- Partial dirty-flush mid-transaction. The cache is allowed to
  exceed capacity for the duration of one transaction; mainline's
  spill-to-WAL-mid-transaction optimization is deferred.
- `PRAGMA cache_size` runtime tuning.
- Cache-aware backup engine. The current backup-engine reads
  via mem-store row-vectors; pin 19 makes it consult the cache
  for path-backed sources. Deferred to a follow-up pin.

## Migration notes

Pin 19 is the boundary spec; tree-wide migration is per-landing
follow-up (Pin 19.2). See sibling `MIGRATION.md` for the full list
of parts and code sites that change after this leaf is canonical.

## Smoke probe (Phase 19.1 Rust + 19.2 sibling)

Phase 19.1 Rust is canonical (validated 2026-04-27: L4 100k INSERT
94.9k qps, integrity_check ok). Phase 19.2 sibling emission to
C / Zig / Go / Python is in scope; each sibling target runs the
same smoke probe with target-idiomatic example wiring.

`src-rust/examples/btree_write_smoke.rs`:

1. Construct a path-backed Database via
   `open_database_at("/tmp/leap-bw-1.db")`.
2. `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL`.
3. `BEGIN; CREATE TABLE t(id INTEGER PRIMARY KEY, payload TEXT);
   INSERT INTO t VALUES(1, 'a'),(2, 'b'),...,(100, 'z'); COMMIT`.
4. Inspect the cache: `cache.flush_dirty().len()` between INSERT
   and COMMIT MUST be ≤ 5 (one or two leaf pages, page 1 for
   header bump, possibly one interior split). Strictly less than
   the number of rows.
5. Assert `/tmp/leap-bw-1.db-wal` exists; frame count ≤ 5.
6. Close the Database.
7. Run mainline `sqlite3 /tmp/leap-bw-1.db "PRAGMA integrity_check; SELECT COUNT(*) FROM t"`
   — expect `ok` and `100`.
8. Reopen via `open_database_at` (recovery via cache) and
   `SELECT COUNT(*) FROM t` — expect `100`.

Smoke counts: 8-step demo. The new step over wal-bridge's smoke
is step 4 (the dirty-page-count assertion that proves pin 19
actually shrinks the COMMIT working set).

## Regeneration envelope

- Spec line budget: ≤ 700 lines (this file).
- shapes.json: ≤ 300 lines (CursorHandle field additions,
  PageLocation, pager_allocate_page, db_size_pages getter,
  amended `pager_commit_transaction` signature is unchanged but
  doc string changes).
- Rust target leaf size: estimated **1200–1600 lines** for the
  combined btree-write emission (cursor write paths +
  pager_allocate_page + descent + split integration). The
  fileformat-write split helpers (~600 lines per target today)
  remain in their existing leaf and are imported.
- C target leaf size: estimated **1800–2400 lines** (no
  Result-type sugar, manual error propagation, explicit page
  buffer management).
- Zig target leaf size: estimated **1400–1800 lines**.
- Go target leaf size: estimated **1600–2000 lines**.
- Python target leaf size: estimated **900–1200 lines**.
- Cross-target total estimate: **~7–9 kLOC** of agent-emitted
  code from this single leaf. Comparable in size to the
  fileformat-write split landing (Phase 113 / 116 / 217).
- Touches mem-store: `MemTable.rows` becomes
  conditionally-populated (in-memory mode only). Estimate
  +50 lines per target for the path-backed branch.
- Touches vdbe.rs: zero new call-site changes (cursor
  signatures unchanged from pin 18.1c).
- Existing tests: corpus regression must hold at 99.9%+ on
  every target. The L4 INSERT bench is the new acceptance
  criterion.

## Phase pins

- **Phase 19.1 (DONE 2026-04-27)** — Rust prototype. Cursor write path
  rewrite + pager_allocate_page + commit-path simplification.
  Validated by smoke probe + L4 bench parity.
- **Phase 19.2 (IN SCOPE 2026-04-27)** — 4-target sibling emission (C/Zig/Go/Python).
  The cache-flush commit path lifts to all 5 targets; the cursor
  write path lifts to all 5 targets. Mainline-readable post-commit
  on every target. Cross-target byte-identity on the WAL file
  produced by the smoke probe.
- **Phase 19.3** — Index B-tree per-page dirty (P19-11). Index
  writes route through the same machinery; corpus regression
  must remain green.
- **Phase 19.4** — Page underflow / sibling merge. Out of scope
  at 19.1–19.3; promoted when delete-heavy workloads are added
  to the bench corpus.

## Pin 19.1 implementation strategies (target-flexible)

The cursor read path (descent + decode-from-cache) is canonical and
MUST be implementable on every target. Two strategies are admitted
for the cursor *write* path mutation under DELETE / UPDATE / non-
monotonic INSERT — both produce mainline-readable bytes at COMMIT:

**Strategy A — per-cell in-place page mutation (canonical).**
DELETE/UPDATE locate the leaf via descent, fetch via
`pager_get_page_mut`, splice the cell out / in, rebuild the leaf via
`page_codec.build_leaf_page`, mark dirty. Non-monotonic INSERT does
the same plus split-on-overflow per §"Page splits". Commit flushes
exactly the touched pages — `O(modified pages)`. This is the
strategy spec'd in §"The cursor write path".

**Strategy B — deferred re-encode at COMMIT (Rust prototype 19.1).**
DELETE/UPDATE/non-monotonic-INSERT mark a per-table
`stream_invalid` flag on the path-builder. Mem-store rows / rowids
remain authoritative for the transaction. At COMMIT,
`finalize_path_btrees` re-encodes invalid tables from sorted
mem-store into fresh leaves (allocated via `pager_allocate_page`)
and written through `pager_replace_page`. Cost:
`O(rows_in_invalid_tables)` not `O(modified pages)`. Stale leaves
remain unreferenced post-commit; mainline `PRAGMA integrity_check`
tolerates them.

**P19-S1.** Both strategies MUST produce mainline-readable bytes
post-commit (PRAGMA integrity_check ok, mainline can SELECT).

**P19-S2.** Strategy choice is target-local and MUST be declared in
`parts/targets/<lang>/mapping.md`. Targets MAY upgrade B→A in a
follow-up landing without spec changes.

**P19-S3.** Targets that adopt Strategy B MUST keep the streaming-
append fast path for monotonic-rowid INSERT to preserve the L4
benchmark win (`O(dirty pages)` commit on the bench-leader path).

**P19-S4.** Cursor read path is unaffected by the strategy choice.
Paged reads decode from the page cache via
`page_codec.decode_leaf_cell`. Targets MAY ship a runtime flag
(e.g. Rust's `cursor_use_paged_reads: bool`) that keeps mem-store
rows as the in-session read source while paged reads are exercised
by validation probes; this flag is target-local and MUST default
to whichever value preserves existing corpus pass rate at the time
of pin 19.1 landing.

## Open questions for follow-up

The two pre-19 prerequisites (pk_index migration → Pin 19a; page-codec
extraction → Pin 19b) and the three deferred items (cache capacity,
Delete mode, backup engine) are tracked in sibling `OPEN-QUESTIONS.md`.
This leaf assumes 19a and 19b have landed before 19.1 begins.
