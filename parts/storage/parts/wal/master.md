---
name: storage/wal
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /spec/durability.spec.md
  - /parts/io-backend/master.md
  - /parts/storage/parts/file-format/master.md
  - /parts/storage/parts/pager/master.md
emits:
  c: { path: src-c/storage/wal.c, headers: [src-c/storage/wal.h] }
  rust: { path: src-rust/src/storage/wal.rs }
---

# Part: storage/wal

Write-ahead log. Absorbs v1 `spec/wal.spec.md` including Phase 3d
(atomic-rename), Phase 4a (multi-frame reader), and Phase 4b
(per-commit append-on-write). This is one of the three sub-parts
most likely to be scrutinized by critics, because WAL correctness
is where LEAP's discipline most visibly meets storage reality.

## Public interface

```
struct Wal {
    mode:        WalMode,       // Phase3dAtomicRename | Phase4bAppendOnWrite
    frames:      Vec<WalFrame>, // in-memory frame batch (Phase 4b only)
    fd:          Option<Fd>,    // WAL file descriptor (file-backed only)
    path:        Option<Path>,  // WAL file path
}

fn wal_begin_session(db: &Database, mode: WalMode) -> Wal
fn wal_append_frames(wal: &mut Wal, dirty_pages: &[PageId], images: &[Page]) -> Result<()>
fn wal_commit(wal: &mut Wal) -> Result<()>
fn wal_checkpoint(wal: &mut Wal, db: &mut Database) -> Result<()>
fn wal_recover(db: &mut Database, wal_path: &Path) -> Result<()>
fn wal_discard(wal: &mut Wal) -> Result<()>  // uncommitted tail
```

## Mode selection

- **`Phase3dAtomicRename`** — default for in-memory DBs and the v1
  simple path. On `commit`: write the entire current page image
  to a new file, fsync, rename over the main file. No WAL file on
  disk after commit. Simplest durability story; correct but does
  not scale to many-small-commits workloads.
- **`Phase4bAppendOnWrite`** — active when `LEAP_WAL_APPEND=1` AND
  the database is disk-backed. On `commit`: append a frame batch
  of dirty pages to the WAL file; fsync; leave the WAL in place.
  `checkpoint` folds the WAL into the main file.

Mode is set at `Wal::begin_session` time, derived from the Database's
settings. A single Database holds exactly one mode for the lifetime
of its handle.

## Phase 4b — session activation contract

A session is "Phase 4b-active" iff:

1. The Database was opened on a disk-backed path (not `:memory:`).
2. The `LEAP_WAL_APPEND=1` environment variable was set at open
   time (or equivalent PRAGMA).
3. The runner/harness selected this mode via the
   `LEAP_WAL_APPEND` knob.

Activation is checked once at session start; mode cannot change
mid-session.

## Phase 4b — write-side protocol

On transaction commit:

1. Query the pager's dirty-page set (snapshot-diff v1, see
   `parts/storage/parts/pager/master.md` § "Pager dirty-set").
2. For each dirty page, construct a `WalFrame` containing:
   - Page number (4 bytes)
   - Page image (`page_size` bytes)
   - Frame checksum (8 bytes, fnv-1a over page image + page number)
3. Append the frames to the in-memory batch.
4. Append a `WalCommitMarker` frame with:
   - Marker magic (`0x434F4D4D` = "COMM")
   - Commit sequence number (monotonic)
   - Batch checksum (checksum of all frame checksums in this batch)
5. Flush the in-memory batch to the WAL file (`io_backend::write`).
6. `io_backend::fsync` the WAL file.
7. Clear the dirty-page set.

Commit returns only after step 6 completes successfully.

## Phase 4b — recovery on open

When opening a database and a WAL file exists alongside:

1. Scan the WAL from start to end.
2. Validate each frame's checksum; stop at first invalid
   (uncommitted tail).
3. Partition frames into batches by `WalCommitMarker` boundaries.
4. For each complete batch (batch checksum valid): replay
   page-images into the in-memory page cache.
5. Discard any partial trailing batch past the last valid
   `WalCommitMarker` — that represents a mid-commit crash and must
   not be applied.
6. Database is now at a consistent post-recovery state. Checkpoint
   may run next (or be deferred).

Multi-commit recovery (Phase 4a + Phase 4b): the reader must
correctly identify every `WalCommitMarker` and apply only full
batches, never partial. The 6/6 Phase 4b fixture
(`tests/cross-build/phase4b.json`) validates this on both targets.

## Checkpoint

Checkpoint is the operation that folds the WAL into the main DB
file and truncates the WAL:

1. Acquire exclusive writer lock.
2. For each committed batch in the WAL, apply its page images to
   the main DB file (overwriting in place).
3. `fsync` the main DB file.
4. Truncate the WAL file to zero length.
5. Release lock.

Checkpoint may run at close, at a threshold (WAL size exceeds N
frames), or manually via `PRAGMA wal_checkpoint`.

## Uncommitted tail discard

If a write session fails mid-transaction (rollback, crash), the
in-memory frame batch is discarded before it reaches the WAL file.
`wal_discard` is the explicit API. A crash with partial writes
already on disk is handled by the recovery-time checksum validation.

## Fixture cases

`tests/cross-build/phase4b.json` (v1 fixture, absorbed here as
this sub-part's primary test set):

1. **phase3d-fallback** — in-memory DB + no env var → atomic-rename
   mode; file-based assertions skipped.
2. **single-commit-frame-emission** — WAL file exists after commit;
   contains N frames + 1 commit marker.
3. **multi-commit-recovery** — 3 commits, close, reopen; recovery
   applies all 3 batches.
4. **bulk-insert-dirty-set** — 10k inserts in one transaction;
   dirty-set tracks correct pages; one batch emitted.
5. **uncommitted-tail-discard** — partial trailing batch past last
   valid commit marker is discarded on reopen.
6. **empty-session-no-wal** — session with zero writes → no WAL
   file created.

## Phase pins

- **Phase 4** — WAL baseline (Phase 3d atomic-rename).
- **Phase 4a** — multi-frame WAL reader.
- **Phase 4b** — per-commit append-on-write.

## Regeneration envelope

- Target leaf size: 800–1200 lines per target.
- Spec < 400 lines.
- Test ownership: 6 fixture cases above; cross-build equivalence
  primary.
