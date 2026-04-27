---
name: storage/backup-engine
kind: leaf
shapes: ./shapes.json
inherits:
  - /parts/storage/parts/file-format/master.md
  - /parts/storage/parts/fileformat-read/master.md
  - /parts/storage/parts/fileformat-write/master.md
  - /parts/storage/parts/pager/master.md
  - /parts/storage/parts/wal/master.md
emits:
  rust:   { path: src-rust/storage/backup_engine.rs }
  c:      { path: src-c/storage/backup_engine.c, headers: [src-c/storage/backup_engine.h] }
  zig:    { path: src-zig/storage/backup_engine.zig }
  go:     { path: src-go/storage/backup_engine.go }
  python: { path: src-python/storage/backup_engine.py }
---

# Storage backup engine: page-by-page copy under read lock

The state machine that drives an online backup. The lib-api
surface (`/parts/lib-api/parts/backup`) is a thin wrapper around
the functions declared here. This part owns:

- The state machine: `Idle → Copying → Completed | RolledBack`
  with `RestartRequired` as a self-edge from `Copying`.
- The page-cursor that walks `(2, 3, …, pagecount, 1)` — page 1
  deferred per Pin B11.
- The per-step shared-lock dance on the source.
- The destination's exclusive write-lock acquired at `open` and
  released at `release`.
- The WAL-snapshot read for WAL-mode sources (delegates frame
  resolution to `/parts/storage/parts/wal`).
- Restart detection: comparing the source's "data version" /
  change counter across step boundaries.
- Page 1 deferral and final-write commit on the destination.
- Destination page-size adoption from a freshly-created
  destination.
- Rollback on `release` while not `Completed`.

This is a **storage** part: it consumes the file-format reader,
the file-format writer, the pager, and the WAL parts. It emits
no SQL surface and is invisible to the VDBE.

## State machine

```
              backup_engine_open
                     │
                     ▼
                  ┌─────┐  step(0) (no-op)
                  │ Idle│ ◄─────────────┐
                  └──┬──┘                │
                     │ first step(>0)    │
                     ▼                   │
              ┌──────────┐  step(>0)     │
   ┌─────────►│ Copying  │───────────────┤
   │          └────┬─────┘   step(>0)    │
   │ source-       │                     │
   │ write         ▼                     │
   │       ┌──────────────────┐          │
   └───────│ RestartRequired  │──────────┘
           └──────────────────┘
                     │ all pages copied (incl. page 1)
                     ▼
                ┌──────────┐
                │Completed │  release → handle freed; dst committed
                └──────────┘
                     ▲
                     │ release while Copying / RestartRequired
                     │ → rollback dst, then RolledBack
                ┌──────────┐
                │RolledBack│  release → handle freed; dst pre-init state
                └──────────┘
```

States are explicit fields on `BackupEngine.state`; transitions
are driven by `backup_engine_step`, `backup_engine_release`, and
the per-step source-write detector.

## Algorithm

### `backup_engine_open(src_handle, dst_handle)`

```
acquire exclusive write-lock on dst_handle
        # Err(EngineOpen) on contention
src_pagecount = read_source_pagecount(src_handle)
        # via fileformat-read of the database header (page 1)
src_change_counter = read_source_change_counter(src_handle)
        # the database header's 4-byte change-counter field
dst_pre_init_size = current_dst_size_in_pages(dst_handle)
        # 0 for a freshly-created destination
src_page_size = read_source_page_size(src_handle)
dst_page_size = read_dst_page_size_or_zero(dst_handle)
if dst_page_size != 0 and dst_page_size != src_page_size:
    release dst write-lock
    return Err(PageSizeMismatch { src_page_size, dst_page_size })

remaining_pages = build_pending_set(src_pagecount)
        # the cursor structure: a counter + a "page 1 deferred"
        # flag. Pages 2..=src_pagecount are ordered ahead;
        # page 1 is deferred until last (Pin B11).

return Ok(BackupEngine {
    state: Idle,
    src_handle,
    dst_handle,
    src_page_size,
    src_pagecount_observed: src_pagecount,
    src_change_counter_observed: src_change_counter,
    dst_pre_init_size,
    pending: remaining_pages,
    page1_deferred: true,
})
```

### `backup_engine_step(engine, n_pages)`

```
if n_pages == 0:
    return Progressed   # no-op; Pin B12

acquire shared read-lock on src_handle
src_change_counter_now = read_source_change_counter(src_handle)
if src_change_counter_now != engine.src_change_counter_observed:
    # source was written between steps → restart (Pin B4)
    engine.src_pagecount_observed = read_source_pagecount(src_handle)
    engine.src_change_counter_observed = src_change_counter_now
    engine.pending = build_pending_set(engine.src_pagecount_observed)
    engine.page1_deferred = true
    engine.state = RestartRequired
    # truncate / reset dst back to pre-init size; the writes from the
    # aborted pass become free pages or are simply overwritten on the
    # next pass. v1 chooses truncate to engine.dst_pre_init_size for
    # simplicity (slower but correct).
    truncate_dst_to(engine.dst_handle, engine.dst_pre_init_size)
    release shared read-lock on src_handle
    return Progressed   # Pin B4: restart is NOT an error

if engine.state is Idle:
    engine.state = Copying

if engine.dst_pre_init_size == 0 and dst_page_size_unset(engine.dst_handle):
    # First step against a fresh destination: adopt the source's page size
    set_dst_page_size(engine.dst_handle, engine.src_page_size)

copied = 0
while copied < n_pages and engine.pending is not empty:
    page_no = pop_next_non_page_one(engine.pending)
    if page_no is None:
        break    # only page 1 left; Pin B11 defers it to the very end
    page_image = source_read_page(engine.src_handle, page_no)
        # WAL-mode: routed through wal_read_page; falls through to
        # main file when the page isn't in WAL (Pin B8).
    dst_write_page(engine.dst_handle, page_no, page_image)
        # buffered; not yet fsync'd
    copied = copied + 1

release shared read-lock on src_handle

if engine.pending is empty (no non-page-1 pages remain) and engine.page1_deferred:
    # Final step path: copy page 1 last, then commit dst (Pin B11)
    acquire shared read-lock on src_handle
    page1 = source_read_page(engine.src_handle, 1)
    release shared read-lock on src_handle
    dst_write_page(engine.dst_handle, 1, page1)
    dst_commit(engine.dst_handle)   # fsync; durability boundary
    engine.page1_deferred = false
    engine.state = Completed
    return Completed

return Progressed
```

`build_pending_set` and `pop_next_non_page_one` are the cursor
abstraction. v1 represents `pending` as a 1-based bitmap of size
`src_pagecount_observed`; alternative renderings (range counter,
list) are admitted as long as Pin B11 (page 1 deferred) holds.

### `backup_engine_release(engine)`

```
if engine.state is Completed:
    release dst exclusive write-lock
    return
# state is Idle, Copying, or RestartRequired:
truncate_dst_to(engine.dst_handle, engine.dst_pre_init_size)
        # rollback: dst is restored to its size before init.
        # For a fresh dst, this is 0 → file truncated to empty.
        # For a dst that pre-existed, the original pages were
        # never overwritten in v1 (the pager's shadow journal
        # captures the pre-image). v1 invokes the pager's
        # rollback path here.
pager_rollback(engine.dst_handle)
release dst exclusive write-lock
engine.state = RolledBack
```

### Accessors

```
backup_engine_remaining(engine) -> u32:
    return |engine.pending|   # cardinality of the pending set,
                              # including page 1 if still deferred

backup_engine_pagecount(engine) -> u32:
    return engine.src_pagecount_observed

backup_engine_state(engine) -> EngineState:
    return engine.state
```

## Correctness pins

**E1. Destination exclusive lock spans `open` to `release`.**
Acquired in `open`; held continuously, including across `step`
boundaries; released in `release` regardless of `state`. No
other connection writes the destination while a backup runs.

**E2. Source shared lock is per-step, not per-handle.** Acquired
on entry to each `step` that does work; released before
returning. No source lock is held while the caller is between
steps; long backups do not starve source readers/writers.

**E3. Source-write detection by change-counter compare.** At
the start of each `step`, the source's database header
change-counter (the file-format's 4-byte field at fixed offset)
is read under the shared lock. If it differs from the value
captured at `open` (or at the previous restart), a restart is
triggered. The change-counter increments on every transaction
commit on the source; this is the spec-pinned mainline
mechanism.

**E4. Restart truncates dst back to `dst_pre_init_size`.** On
restart, the destination is reset to its pre-`init` state
before the new pass begins. v1's spec-pinned path uses pager-
level rollback for pre-existing destinations and file truncate
for fresh destinations. The next `step` re-copies from page 2.

**E5. Page 1 is copied LAST.** The pending-set cursor never
yields page 1 from `pop_next_non_page_one`. Page 1 is copied in
the same `step` invocation that observes the pending set
(modulo page 1) becoming empty, immediately before
`dst_commit`. This guarantees that a destination observed
mid-backup never has a header that asserts a page count larger
than the live page set (mainline-parity invariant).

**E6. WAL-mode source reads via `wal_read_page` first.** When
the source is in WAL mode (the `-wal` file exists and the WAL
header is valid per `/parts/storage/parts/wal`), every page
read in `step` first consults the WAL frame map at the snapshot
fixed by the step's shared-lock acquisition. Pages absent from
the WAL fall through to the main file. The snapshot's
`mx_frame` is captured at lock acquisition and held for the
duration of the step's read sequence.

**E7. Fresh destination adopts source page size on first
step.** A destination that was empty at `open` has its page
size set to the source's page size on the first non-zero step.
Spec-side this is a single write to the destination's database
header (page 1 stays deferred per E5; the page-size field is
set in the writer's in-memory header, applied at `dst_commit`).

**E8. Pre-existing destination must match source page size.**
A destination that already contains a database (page 1 is
non-empty at `open`) MUST have a page size equal to the
source's. v1's `open` returns `PageSizeMismatch`; v1 does NOT
admit in-flight page-size conversion.

**E9. `dst_commit` happens exactly once per pass.** A pass that
runs to completion calls `dst_commit` exactly once, after the
last page (page 1) is written. A pass that restarts does NOT
commit; instead, the next pass's eventual completion does.
This is the durability boundary — partial backups are not
visible to a destination reader (which would, in v1, have to
wait for the exclusive lock to release anyway).

**E10. `Completed` is terminal modulo `release`.** Once the
state reaches `Completed`, subsequent `step` calls are
admitted as no-ops returning `Completed` (idempotent; they
DO NOT release the dst lock — only `release` does that).

**E11. `release` is idempotent.** A second `release` on a
handle whose state is already `RolledBack` or `Completed`
(and whose lock has already been released) is a no-op. Targets
MAY render this by consuming the handle on the first
`release`; the spec admits both consuming and non-consuming
renderings.

**E12. Source page reads use the fileformat-read part.**
Reading a source page is delegated to
`/parts/storage/parts/fileformat-read` (for the main file
path) and `/parts/storage/parts/wal` (for the WAL frame map).
The backup engine MUST NOT reimplement page decoding.

**E13. Destination page writes use the fileformat-write
part.** Writing a destination page is delegated to
`/parts/storage/parts/fileformat-write`. The backup engine
issues raw page-image writes (the page is copied byte-for-
byte; no encoding is re-derived). The destination's pager
ledger captures the pre-images for E4 rollback.

**E14. `pending` cardinality is the spec definition of
`remaining`.** The lib-api's `backup_remaining` accessor
returns `|engine.pending|` directly. Targets MAY cache this
count separately from the data structure for O(1) reads, but
the canonical value is the cardinality of `pending` (with page
1 included while `page1_deferred` is true).

**E15. No invented helpers.** Per §Generation scope. The
emitted surface is exactly the `BackupEngine` record, the
`EngineState` enum, the `EngineStepOutcome` enum, and the
five engine functions declared in `shapes.json`. The cursor
data structure (the bitmap or counter) is a target-private
detail and MUST NOT leak into the public surface.

## Ambiguities and v1 scope decisions

- **Pager rollback vs file truncate.** v1's restart path
  uses pager-rollback for a pre-existing destination and
  file-truncate for a fresh destination. A future
  optimization could keep the partial write set and
  re-copy only the pages that were re-dirtied on the
  source; deferred to a backup-engine-v2 follow-up.
- **Source `change-counter` vs WAL `mx_frame` advance.** A
  WAL-mode source's commit increments the change-counter at
  the next checkpoint, but readers see WAL-side commits
  earlier (via `mx_frame` advance). v1 detects the WAL-side
  advance via change-counter parity in the WAL header; this
  is mainline-parity. Decoupling change-counter detection
  from WAL-snapshot detection is a future refinement.
- **Backup throughput.** Bench lane 4 is INSERT throughput,
  not backup throughput. v1 does NOT pin a backup-rate
  target; the page-copy loop's per-page cost is dominated
  by I/O, and the structural correctness of the state
  machine is the v1 deliverable.

## Regeneration envelope

- Line budget: ~400-600 lines per target. The state machine
  is straightforward; the pending-set cursor and the
  WAL/main-file read fork are the bulky pieces.
- Imports: `Database`, `RuntimeCondition` from
  `/parts/core` / `/parts/storage`; reads from
  `/parts/storage/parts/fileformat-read` and
  `/parts/storage/parts/wal`; writes from
  `/parts/storage/parts/fileformat-write`; pager rollback
  from `/parts/storage/parts/pager`.
- No new VDBE opcodes; this is a storage-side state
  machine only.

## Smoke probe (structural)

1. `open(src=100-page, dst=fresh)` returns engine with
   state=Idle, pagecount=100, remaining=100.
2. `step(engine, 10)` advances; remaining=90;
   state=Copying; dst contains 10 page-images for pages
   2..=11 (page 1 still deferred, Pin E5).
3. Repeat `step(engine, STEP_ALL)` once more → state=
   Completed; remaining=0; dst has 100 pages including
   page 1 written last; `dst_commit` was invoked exactly
   once (Pin E9).
4. `release(engine)` → dst write-lock released; engine
   freed.
5. With a writer firing on src between two steps:
   `step(engine, n)` after the writer's commit observes a
   change-counter mismatch, sets state=RestartRequired,
   truncates dst, returns `Progressed`; remaining now
   reflects the new pagecount (Pin E3, E4).
6. `release(engine)` while state=Copying truncates dst
   back to `dst_pre_init_size` and sets state=RolledBack
   (Pin E11 path).
