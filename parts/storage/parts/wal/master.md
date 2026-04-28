---
name: storage/wal
kind: leaf
shapes: ./shapes.json
inherits:
  - /parts/storage/parts/file-format/master.md
  - /parts/storage/parts/fileformat-read/master.md
  - /parts/storage/parts/fileformat-write/master.md
emits:
  rust:   { path: src-rust/storage_wal.rs }
  c:      { path: src-c/storage/storage_wal.c, headers: [src-c/storage/storage_wal.h] }
  zig:    { path: src-zig/storage/storage_wal.zig }
  go:     { path: src-go/storage/storage_wal.go }
  python: { path: src-python/storage/storage_wal.py }
---

# Part: storage/wal

Write-ahead log compatible with the **mainline SQLite WAL on-disk
format** (sqlite.org/fileformat2.html §"The Write-Ahead Log
Format"). The proof of compatibility is bidirectional: a database
written by leap-WAL must be replayable by mainline `sqlite3`, and a
WAL produced by mainline must be replayable by leap-WAL. WAL frames
are part of the on-disk contract — getting them right is required
for the "Done" criterion.

**Phase 4b (Rust prototype) is canonical and validated**
(`src-rust/storage_wal.rs`, 787 LOC, mainline-readable WAL frames,
fsync gate honors `PRAGMA synchronous`, WAL replay on reopen). The
Rust file is the canonical reference for sibling targets; the
spec in this file plus `shapes.json` are the language-neutral
contract.

**Phase 4b.2 (multi-target sibling emission, in scope 2026-04-27).**
Emit slots are declared in the frontmatter for all 5 targets. C /
Zig / Go / Python siblings implement the same surface (`wal_open`,
`wal_append_frame`, `wal_commit`, `wal_rollback`, `wal_read_page`,
`wal_checkpoint`, plus the codec helpers). Cross-target WAL byte
identity on the Phase 19.1 smoke probe (100-row INSERT into
`/tmp/leap-bw-1.db`) is the acceptance gate.

## Why a WAL

Rollback-mode (the path implemented in `fileformat-write`) writes
the entire file to a temp path and renames over the original. That
is correct but pays `O(file_size)` per commit. The WAL writes only
modified pages, appended sequentially, with `fsync` once per
commit. This is the path benchmark lane 4 (INSERT throughput)
depends on.

A WAL also unlocks readers and writers running concurrently:
readers lock down a frame index (the "mxFrame at read-snapshot")
and consult the WAL up to that frame, falling back to the main
database file for pages older than any in the WAL. Writers append
without disturbing readers.

## File layout (mainline-compatible)

A WAL is a single file with the path `{db_path}-wal`. It begins
with a 32-byte **WAL header**, followed by zero or more
**frames**. Each frame is `(24 + page_size)` bytes — a 24-byte
frame header followed by one full page image.

```
[WAL header     32 bytes]
[Frame 1 header 24 bytes][Frame 1 page  page_size bytes]
[Frame 2 header 24 bytes][Frame 2 page  page_size bytes]
...
```

WAL files grow in 24+page_size increments. They never shrink
mid-execution; checkpoint truncates them only at well-defined
boundaries (or the file is reset in place — see §Checkpoint).

### WAL header (32 bytes, big-endian)

| Offset | Width | Field                  | Notes                                  |
|--------|-------|------------------------|----------------------------------------|
| 0      | 4     | magic_number           | `0x377F0682` or `0x377F0683`           |
| 4      | 4     | file_format_version    | `3007000` (3.7.0+)                     |
| 8      | 4     | page_size              | Same value as the database's page_size |
| 12     | 4     | checkpoint_sequence    | Monotonic counter, +1 per checkpoint   |
| 16     | 4     | salt_1                 | Random; rolls every checkpoint         |
| 20     | 4     | salt_2                 | Random; rolls every checkpoint         |
| 24     | 4     | checksum_1             | Cumulative checksum over bytes 0..24   |
| 28     | 4     | checksum_2             | Cumulative checksum over bytes 0..24   |

The two magic numbers select endianness for **frame checksums**:

- `0x377F0682` → checksum reads page bytes as **little-endian** u32.
- `0x377F0683` → checksum reads page bytes as **big-endian** u32.

Leap-WAL emits `0x377F0683` (big-endian) for parity with the rest
of the file format. The reader accepts either.

### Frame header (24 bytes, big-endian)

| Offset | Width | Field                  | Notes                                  |
|--------|-------|------------------------|----------------------------------------|
| 0      | 4     | page_number            | 1-based page number being written      |
| 4      | 4     | db_size_after_commit   | Nonzero on commit frame; 0 otherwise   |
| 8      | 4     | salt_1                 | Copy of WAL header salt_1              |
| 12     | 4     | salt_2                 | Copy of WAL header salt_2              |
| 16     | 4     | checksum_1             | Running checksum-1 through this frame  |
| 20     | 4     | checksum_2             | Running checksum-2 through this frame  |

`db_size_after_commit` is the **commit marker**. When nonzero, this
frame is the last frame of a transaction and the value gives the
new database size in pages. When zero, the frame is interior to a
transaction and any reader that stops here must NOT apply the
partial transaction.

## Checksum (Fibonacci-style)

Mainline SQLite uses a non-cryptographic running checksum based on
Fibonacci accumulation. Each input is consumed as a pair of u32
words (`x0`, `x1`).

```
checksum_step(s0, s1, x0, x1):
    s0 = (s0 + x0 + s1) mod 2^32
    s1 = (s1 + x1 + s0) mod 2^32
    return (s0, s1)
```

Initial state for the WAL header checksum (over bytes 0..24):
`s0 = s1 = 0`. The result is written into bytes 24..32.

Initial state for **frame N**'s checksum: the (s0, s1) value left
behind by the WAL header (for frame 1) or by frame N-1 (for N>1).
The frame's checksum input is the 8 bytes of `(page_number,
db_size_after_commit)` followed by the page image, all read as
u32 words in the endianness selected by the WAL magic.

A frame is **valid** iff:

1. Its `salt_1`/`salt_2` match the WAL header's current salts.
2. The cumulative checksum recomputed from the WAL header through
   this frame matches the frame header's `checksum_1`/`checksum_2`.

Any invalid frame ends the live region of the WAL — every frame
after it (including itself) is treated as not present. Mainline
truncates on next checkpoint; leap-WAL matches.

## Reader protocol

Readers establish a **read-snapshot** at session start and use it
for the duration of their session. The snapshot is defined by:

- `mx_frame` — the frame number of the most recent commit frame
  visible to this reader. Frames > mx_frame are not consulted.
- A **wal-index** mapping `page_number → frame_number` for every
  frame in `[1, mx_frame]`. When a page appears in multiple
  frames, the LATEST frame wins.

```
wal_open(db_path) -> WalState:
    open or create {db_path}-wal
    if file is shorter than 32 bytes:
        # fresh or truncated WAL
        write a new WAL header with random salts; checkpoint_sequence = 0
        return WalState { mx_frame: 0, page_size, salts, ... }
    decode WAL header
    require checksum_1/checksum_2 valid
    scan frames forward, validating salts and running checksum
    record the frame_number of the most recent VALID commit frame
        (db_size_after_commit != 0) as mx_frame
    build wal_index: for f in 1..=mx_frame:
        wal_index[frame_page_number[f]] = f   # last write wins
    return WalState { mx_frame, wal_index, salts, ... }

wal_read_page(state, page_number) -> Option<PageImage>:
    if state.wal_index has page_number, return frame's page image
    else return None  # caller falls back to main db file
```

Readers do not modify the WAL file. Two readers may run
concurrently with one writer: each reader's snapshot is a frozen
`(mx_frame, wal_index)` pair captured at open time; new commits
appended after that don't change what the reader sees.

## Writer protocol

A writer batches dirty pages into **frames**, appending them to
the WAL file. Within a transaction, frames are appended one at a
time as pages are dirtied. The transaction COMMIT is signaled by
setting `db_size_after_commit` to a nonzero value on the **last
frame of the transaction** and `fsync`ing the WAL file.

```
wal_begin_write(state) -> Writer:
    require no other writer holds the writer lock
    return a Writer bound to state, with frames_pending = []

wal_append_frame(writer, page_number, page_image):
    # builds the frame header but does NOT write to disk yet;
    # buffered append. (Targets MAY flush to OS buffers eagerly;
    # the durability boundary is wal_commit's fsync.)
    frame_no = state.mx_frame + len(writer.frames_pending) + 1
    cumulative checksum extended from prior frame's running state
    frame_header.salt_1 = state.salt_1
    frame_header.salt_2 = state.salt_2
    frame_header.db_size_after_commit = 0
    frame_header.checksum_1, checksum_2 = updated cumulative
    writer.frames_pending.append((frame_header, page_image))

wal_commit(writer, new_db_size):
    require writer.frames_pending is not empty
    last = writer.frames_pending[-1]
    rewrite last.frame_header.db_size_after_commit = new_db_size
    recompute last.frame_header.checksum_1/checksum_2 with the new
        db_size_after_commit baked in
    write all pending frames to the WAL file at offset
        32 + (state.mx_frame * (24 + page_size))
    fsync WAL file
    state.mx_frame += len(writer.frames_pending)
    update state.wal_index for each frame appended
    writer.frames_pending = []
    release writer lock

wal_rollback(writer):
    discard writer.frames_pending without writing
    release writer lock
    # frames not written to disk == frames that don't exist
```

A crash mid-transaction (process killed between `wal_append_frame`
calls but before `wal_commit`) leaves the WAL file in one of two
states: (a) the partial frames never reached disk → no recovery
needed; (b) some partial frames did reach disk but the commit
frame (with `db_size_after_commit != 0`) didn't → on next open,
the cumulative checksum still validates each frame, but no commit
boundary follows them, so they are excluded from `mx_frame` and
are overwritten by the next writer. Either way: no torn
transaction is visible.

## Checkpoint protocol

Checkpoint folds committed WAL frames into the main database file
and resets the WAL.

```
wal_checkpoint(state, db_file):
    acquire exclusive lock (no readers or writers)
    for f in 1..=state.mx_frame:
        if f is the LATEST frame for its page_number in wal_index:
            read frame f's page image from WAL
            write that page image to db_file at
                (page_number - 1) * page_size
    fsync db_file

    # Reset WAL in place: bump checkpoint_sequence, roll salts,
    # rewrite WAL header. Frames past the new header become
    # implicitly invalid because their salts no longer match.
    state.checkpoint_sequence += 1
    state.salt_1 = random_u32()
    state.salt_2 = random_u32()
    rewrite WAL header at offset 0 with the new fields and
        recomputed checksum_1/checksum_2
    state.mx_frame = 0
    state.wal_index = empty
    release lock
```

We do not truncate the WAL file at checkpoint. Mainline doesn't
either — it overwrites in place — because truncating contends
with readers holding stale snapshots. The salt-roll invalidates
old frames implicitly: any reader that opens after the
checkpoint sees the new salts in the header, and validation of
old frames fails (salt mismatch), so they vanish from the live
region. The next writer overwrites them.

A "FULL" checkpoint variant additionally truncates the file to
32 bytes once every reader has released its snapshot; "PASSIVE"
and "RESTART" variants do not. v1 leap-WAL emits PASSIVE only;
the file grows to its high-water mark over the database
lifetime, which matches mainline's default behaviour.

## Recovery on open

When opening a database with an existing WAL file:

1. If the WAL file is shorter than 32 bytes, treat as fresh.
2. Decode the WAL header. If the header checksum is invalid,
   reset (start fresh, salts randomized).
3. Initialize cumulative checksum state from the WAL header's
   `(checksum_1, checksum_2)`.
4. Scan frames forward. For each frame:
   a. Verify `salt_1`/`salt_2` match the WAL header.
   b. Recompute cumulative checksum; verify
      `checksum_1`/`checksum_2` match.
   c. If either check fails, stop scanning.
5. Among the frames that passed both checks, find the largest
   `frame_number F` with `db_size_after_commit != 0`. Set
   `mx_frame = F`. (If no such frame exists, `mx_frame = 0`.)
6. Build `wal_index` from frames `1..=mx_frame`.

Frames after `mx_frame` (validated or not) are dead: they
represent in-progress transactions that didn't commit, and they
will be overwritten by the next writer. Recovery does not erase
them; it just doesn't consult them.

## Concurrency model (v1: single-writer, multi-reader)

- One writer at a time, gated by an exclusive writer lock on the
  WAL.
- Any number of readers concurrent with the writer; each reader
  snapshots `(mx_frame, wal_index)` at session start.
- Checkpoint requires no readers AND no writer. v1 chooses
  PASSIVE-only semantics: checkpoint runs to the highest frame
  that no reader is holding; with v1's "snapshot at open"
  policy, this means checkpoint waits for all open readers to
  close.

The lock implementation is target-specific (POSIX `fcntl`, byte
ranges on Windows, in-process mutex for `:memory:`). The spec
says only "exclusive" or "shared"; targets map.

## Salt discipline

Salts roll on every checkpoint. Frames written before checkpoint
N have `(salt_1, salt_2)` from before; frames written after have
new salts. A reader validating frames compares each frame's salt
against the **current WAL header salts**. Any mismatch ends the
live region.

Salts are 32-bit random values. Generation is target-specific
(targets must use a cryptographically-acceptable RNG; predictable
salts allow a malicious file to forge frame checksums). Mainline
uses `sqlite3_randomness`; leap-WAL targets use platform-native
secure RNGs.

## Page size invariant

The WAL header's `page_size` MUST equal the database header's
`page_size`. Mismatch is a corruption condition; recovery treats
the WAL as fresh and resets it.

If the database's page size changes (only possible via VACUUM
into a new file, which is a separate operation), the WAL must
have been checkpointed and reset first.

## Mainline interop

A WAL written by leap is replayable by mainline iff:

1. Magic number is one of the two valid values.
2. `file_format_version == 3007000`.
3. Page size matches the database.
4. Salts and checksums validate frame-by-frame.
5. At least one commit frame exists OR the WAL is empty past the
   header.

Mainline-written WAL is replayable by leap iff the same
conditions hold. The fixture `tests/fixtures/wal-mainline/` (to
be added) will hold a WAL file produced by mainline `sqlite3`
running an INSERT in WAL mode; the leap reader must replay it
and produce the expected post-state.

## Correctness pins

**W1. Frame size is exactly `24 + page_size`.** No padding, no
alignment, no per-frame metadata beyond the 24-byte header.

**W2. Commit marker is `db_size_after_commit != 0` on the LAST
frame of the transaction.** All earlier frames in the
transaction MUST have `db_size_after_commit == 0`. Setting it on
an interior frame would let recovery treat a partial transaction
as committed.

**W3. Cumulative checksum starts from the WAL header's
checksum.** Frame 1's input checksum state is `(header.checksum_1,
header.checksum_2)`. Frame N>1 starts from frame N-1's running
state. The header's own checksum is computed over bytes 0..24
with initial state `(0, 0)`.

**W4. Checksum endianness is selected by magic.** `0x377F0682`
→ little-endian u32 reads of page bytes; `0x377F0683` →
big-endian. Leap emits big-endian. Readers accept either.

**W5. Salt-on-frame must match WAL-header salt.** Validation step
1; mismatch invalidates the frame and ends the live region.

**W6. Frames past `mx_frame` are inert.** Recovery never applies
them; readers never consult them; the next writer overwrites
them at offset `32 + (mx_frame * (24 + page_size))`.

**W7. Latest-write-wins in wal_index.** When a page appears in
multiple frames within `[1, mx_frame]`, the highest-numbered
frame is authoritative for reads and for checkpoint.

**W8. Checkpoint resets salts.** After checkpoint,
`(salt_1, salt_2)` are fresh random values, `checkpoint_sequence`
+= 1, `mx_frame = 0`. The WAL file's bytes past offset 32 are not
zeroed; they become invalid by salt mismatch.

**W9. fsync once per commit.** `wal_commit` calls fsync on the
WAL file exactly once, after writing all pending frames including
the commit frame. No fsync is required for non-commit frame
appends within a transaction.

**W10. Atomic commit boundary.** A reader opening the database
after a crash sees either all frames of a transaction (commit
frame reached disk) or none (commit frame did not reach disk).
There is no torn-transaction state. The proof: the commit frame
is the LAST frame of the transaction, and `mx_frame` is defined
as the latest frame with `db_size_after_commit != 0`; if that
frame is missing, all earlier frames of the transaction are past
`mx_frame` and inert.

**W11. Mainline-readable.** A WAL produced by leap-WAL must be
recoverable by mainline `sqlite3` opening the database. Tested
by writing N rows via leap, then running `sqlite3 db "SELECT
COUNT(*)..."` and verifying the count.

**W12. Mainline-writable.** A WAL produced by mainline opening a
leap-written database (or vice versa) must be recoverable by
leap-WAL. Tested with a fixture WAL captured from mainline.

**W13. Page size invariant.** WAL header `page_size` ==
database header `page_size`. Mismatch → reset WAL.

**W14. No invented helpers.** Per §Generation scope. Targets
emit only what `shapes.json` declares plus what this spec
explicitly requires.

## fsync discipline by synchronous level

The fsync calls in `wal_commit`, `wal_checkpoint`, and the
file-format atomic-rename commit are gated by the connection's
`SyncLevel` — a closed enum `{Off, Normal, Full, Extra}` whose
**canonical home is this part's `shapes.json` `types.SyncLevel`**.
Every fsync site lives in storage, so SyncLevel is owned here;
`parts/compiler/parts/statements/pragma/master.md` §Synchronous
semantics (pins S1..S6) is the user-facing surface that maps
`PRAGMA synchronous = X` onto the same enum and re-imports it.

The matrix below is **normative**: targets MUST consult
`connection_get_synchronous(state)` at each site and skip or
issue the fsync per the table.

| Site                                  | OFF | NORMAL | FULL | EXTRA |
|---------------------------------------|-----|--------|------|-------|
| WAL frame append (interior frame)     |  no |   no   |  no  |  no   |
| WAL commit-frame write (`wal_commit`) |  no |   no   |  yes |  yes  |
| WAL checkpoint (`wal_checkpoint`)     |  no |  yes   |  yes |  yes  |
| Directory fsync after WAL replace     |  no |   no   |  no  |  yes  |
| File-format atomic-rename commit      |  no |  yes   |  yes |  yes  |
| File-format parent-dir fsync          |  no |   no   |  no  |  yes  |

**W15. NORMAL gates per-commit fsync off, checkpoint fsync on.**
At `NORMAL` the WAL accumulates frames into the page-cache /
OS-buffer layer between checkpoints; only the checkpoint pays an
fsync. This matches mainline's WAL-mode default. Pin W9 is
relaxed under `NORMAL`: the "fsync once per commit" obligation
applies only when the connection's level is FULL or EXTRA.

**W16. FULL fsyncs the WAL on every commit.** At `FULL` (or
EXTRA), `wal_commit` MUST call fsync after writing the commit
frame, consistent with the original W9 pin.

**W17. EXTRA additionally fsyncs the directory.** At `EXTRA`,
after a WAL replacement (file-format atomic rename) or
checkpoint, the parent directory of the WAL file is fsynced so
the WAL file's metadata is durable across an OS crash. At lower
levels this fsync is skipped.

**W18. OFF skips all fsyncs.** At `OFF`, `wal_commit`,
`wal_checkpoint`, the file-format atomic-rename commit, and the
directory fsync ALL become no-ops. Durability is delegated to
the OS page cache; an OS crash may lose committed transactions
or corrupt the database. This matches mainline `synchronous=OFF`
semantics.

## Multi-process coordination

The reader/writer/checkpointer protocols above describe a
**single-process** WAL session. Two OS processes opening the same
database in WAL mode must agree on `(mx_frame, wal_index, salts,
n_backfill)` even though each has its own `WalState` value. That
agreement is delegated to a sibling part:
**`parts/storage/parts/wal-shm/`** — the wal-index shared-memory
file `{db_path}-shm`, with byte-range lock protocols on it.

In a multi-process build, a `WalState` is a thin process-local
view; the authoritative `mx_frame`, the page→frame hash table,
and the read-mark slots all live in the shm file and are consulted
under named locks (WRITE, CHECKPOINT, RECOVER, READ(0..4)).

Lock-acquisition responsibilities (delegated to wal-shm):

- `wal_open` opens shm; if shm is missing/stale, shm_recover
  rebuilds it from WAL frames (the WAL is authoritative;
  shm is volatile coordination state).
- `wal_begin_write` acquires EXCLUSIVE on WRITE via
  `shm_writer_begin`.
- `wal_commit` updates the shm header (both copies, with a barrier
  between) AFTER the WAL fsync has completed; releases WRITE.
- `wal_open` for a reader claims a READ(k) slot and pins
  `read_marks[k]` to its mx_frame.
- `wal_checkpoint` acquires EXCLUSIVE on CHECKPOINT and clamps
  `n_backfill` to the slowest active reader's mark.

The shm file is **NOT part of the durable on-disk contract**: pin
W11 (mainline-readable) and pin W12 (mainline-writable) require
only that the WAL itself round-trip; mainline always rebuilds shm
from WAL on first open. Pin SHM1 in wal-shm restates this.

A **single-process build** that knows it is the sole opener may
elide wal-shm entirely and use the in-process `wal_index` field
of `WalState`. A **multi-process build** routes every `wal_index`
read and update through wal-shm. The decision is a target build
flag, not a spec branch: the function-level surface defined here
remains the same.

See `parts/storage/parts/wal-shm/master.md` for the shm file
layout, the eight named locks, the read-mark protocol, and pins
SHM1..SHM22.

## Phase pins

- **Phase W0** — spec only (this part). `shapes.json` declares
  the type+function surface. NO target code emitted yet.
- **Phase W1** — single-target prototype (Rust). Implements
  `wal_open`, `wal_append_frame`, `wal_commit`, `wal_read_page`,
  `wal_checkpoint`. Roundtrip with mainline on a 1-row commit.
- **Phase W2** — second target (C) for parity. Same shape
  surface, byte-identical WAL output on the W1 fixture.
- **Phase W3** — multi-page commits + multi-commit recovery
  fixtures.
- **Phase W4** — checkpoint + salt-roll fixtures; verify a
  post-checkpoint WAL file is interpreted as empty by both leap
  and mainline.
- **Phase W5** — concurrency: shared-lock readers vs exclusive
  writer; one writer + N readers stress test.
- **Phase W6** — async I/O backend integration (io_uring on
  Linux, kqueue on macOS/BSD); benchmark lane 4 numbers.

## Regeneration envelope

- Spec line budget: ~300 lines (this file).
- shapes.json: ~100 lines.
- Target line budget (Phase W1+): ~600–900 lines per target. The
  encode/decode of frames + checksum + header is structurally
  similar to fileformat-write; expect comparable size.
- No external deps beyond stdlib + the io-backend part.
- Standalone runner per target for fixture-based smoke; library
  module for production callers.

## Open questions (for follow-up phases)

1. **wal-index file (`-shm`).** Mainline maintains a separate
   shared-memory file `{db_path}-shm` with a hash table for fast
   page→frame lookup. v1 leap-WAL builds wal_index in process
   memory at session open. Phase W5 must decide whether to add
   `-shm` for cross-process visibility (required for full
   mainline interop in concurrent multi-process scenarios) or
   stick with per-process index (simpler, fine for single-process
   use, breaks if mainline and leap have the same database open
   simultaneously across processes).

2. **WAL-index endianness.** If we add `-shm`, mainline's format
   is host-endian (not big-endian). Cross-platform readers of the
   same database file would have to handle that. Defer to W5.

3. **Truncating checkpoint vs in-place reset.** v1 picks in-place
   reset (mainline's PASSIVE default). If benchmark lane 4 shows
   the WAL file growing unboundedly under sustained write load,
   add a TRUNCATE checkpoint variant in W4.

4. **Read-snapshot lifetime.** v1 readers snapshot at open and
   hold for the session. Mainline allows readers to advance
   their snapshot at statement boundaries. Defer; v1 simplicity
   buys us isolation, mainline parity buys us throughput.

5. **Shared-memory locking primitives.** Mainline uses
   POSIX-advisory + Windows byte-range. If we add `-shm`, we'll
   need a target-neutral lock vocabulary. Punt to W5.
