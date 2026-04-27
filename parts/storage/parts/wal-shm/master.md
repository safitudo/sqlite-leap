---
name: storage/wal-shm
kind: leaf
shapes: ./shapes.json
inherits:
  - /parts/storage/parts/wal/master.md
---

# Part: storage/wal-shm

Multi-process coordination layer for the WAL. Adds the **wal-index**
shared-memory file (`{db_path}-shm`) and the byte-range lock
protocols that let multiple OS processes safely share a database in
WAL mode. The on-disk WAL itself (frame format, checksums, salts,
recovery) is owned by `parts/storage/parts/wal/`; this part adds
ONLY the cross-process visibility surface.

This is the foundational design pass. **No target code is emitted
from this part yet.** Deliverables: this spec + `shapes.json`.

## Why a wal-index

The base WAL part rebuilds an in-process `(page_number → frame_no)`
map at session open by scanning frames forward. That is correct for
a single-process database but breaks when two processes have the
same database open in WAL mode: process B's writer appends frames
that process A's in-process index never learns about. Mainline
solves this with a shared file the OS maps into every connecting
process. Each process sees the same map; updates from one process
are visible to all. The file is conventionally treated as
**volatile**: if it is missing, stale, or unreadable, it is
reconstructed from the WAL frames.

The shm file is **not part of the durable on-disk contract**. It is
a coordination cache. Mainline never relies on its contents
surviving a crash; recovery rebuilds it from the WAL.

## File layout — `{db_path}-shm`

A single file with the path `{db_path}-shm`. It is composed of
fixed-size **regions**, each `32768` bytes (32 KiB). Region 0
contains the wal-index header and the first portion of the
`page_number → frame_no` hash table. Subsequent regions extend the
hash table as the WAL grows. The file is host-endian for
multi-byte fields (mainline behaviour); two processes on the same
host therefore agree on byte order.

```
[Region 0  32 KiB]
  [WalIndexHeader  136 bytes]   (two copies, see below)
  [Checkpoint info  ~40 bytes]
  [Hash slots + page_number array — fills the rest of region 0]
[Region 1  32 KiB]
  [Hash slots + page_number array]
...
```

Each region holds slots for `HASHTABLE_NPAGE` page entries (4096
in mainline). Region 0 is special because its head is consumed by
the header; it holds `HASHTABLE_NPAGE_ONE` (4062 in mainline)
entries.

### WAL-index header (136 bytes, host-endian)

The header is stored TWICE back-to-back at offset 0 of region 0,
each copy 48 bytes followed by a `(checksum_1, checksum_2)` pair.
A reader accepts the header iff both copies are byte-identical AND
the checksum validates. Two copies guard against torn writes: a
writer updates copy 1, memory-barriers, updates copy 2; a reader
that sees a mismatch retries.

| Offset | Width | Field                  | Notes                                         |
|--------|-------|------------------------|-----------------------------------------------|
| 0      | 4     | version                | `3007000`                                     |
| 4      | 4     | unused                 | Zero                                          |
| 8      | 4     | change_counter         | Monotonic; +1 on each transaction commit      |
| 12     | 1     | is_init                | 1 once header has been initialized            |
| 13     | 1     | big_endian_checksums   | 1 if WAL magic is `0x377F0683`                |
| 14     | 2     | page_size_encoded      | Same encoding as DB header field              |
| 16     | 4     | mx_frame               | Largest valid commit frame in WAL             |
| 20     | 4     | n_page                 | DB size in pages as of mx_frame's commit      |
| 24     | 8     | frame_checksum         | (s0,s1) cumulative through mx_frame           |
| 32     | 8     | salts                  | Copy of WAL header (salt_1, salt_2)           |
| 40     | 8     | checksum               | (c0,c1) Fibonacci checksum over bytes 0..40   |

This 48-byte record appears twice (offsets 0 and 48). Bytes
96..136 hold the **checkpoint info block**:

| Offset | Width | Field                  | Notes                                         |
|--------|-------|------------------------|-----------------------------------------------|
| 96     | 4     | n_backfill             | # of WAL frames already copied to main DB     |
| 100    | 20    | read_marks[5]          | Five `u32` read marks (see §Read marks)       |
| 120    | 8     | locks_byte_pad         | Reserved; the next 8 bytes carry the locking  |
|        |       |                        | byte range (logical, not stored data)         |
| 128    | 4     | n_backfill_attempted   | Optimistic checkpoint advance counter         |
| 132    | 4     | reserved               | Zero                                          |

### Hash table region

Following the header in region 0 (and filling regions 1..N), each
region carries:

- A **page-number array** `aPgno[HASHTABLE_NPAGE]`: for slot `k`,
  `aPgno[k] = page_number` of the WAL frame whose region-relative
  index is `k`. Frame number is `region_index * HASHTABLE_NPAGE + k
  + 1` (with the offset adjusted for region 0's smaller capacity).
- A **hash slot array** `aHash[HASHTABLE_NSLOT]` (`NSLOT = 8192`
  in mainline, exactly `2 × NPAGE`): each slot holds a 16-bit
  index into `aPgno` for that region (+1, with 0 meaning "empty").

Lookup: hash the page number → probe `aHash` linearly → resolve to
`aPgno` index → frame number. **Latest frame for a page wins**:
the writer probes for the existing entry and overwrites it if the
incoming frame number is higher.

The hash function is the published mainline form:
`hash(p) = (p * 383) mod NSLOT`. Linear probing with wrap-around
within the region.

## Read marks (max 5)

The header reserves five `u32` read marks. Each mark records an
`mx_frame` that some reader has pinned. A reader, when opening a
snapshot, must:

1. Acquire shared READ lock on one of the five `READ(k)` byte-range
   slots (k ∈ {0..4}).
2. Atomically write its current `mx_frame` into `read_marks[k]`
   under that lock (or accept the existing mark if it already
   matches).
3. Use `(mx_frame, wal_index)` as its snapshot.

Mark `k = 0` is **special**: it is permanently pinned at value `0`.
A reader holding READ(0) sees no WAL frames and reads only from
the main database file; this is the fallback when all other marks
are taken or when the WAL is empty.

A checkpointer may not advance `n_backfill` past the smallest
non-zero `read_marks[k]` for which any reader holds READ(k). That
is the checkpoint barrier.

When a reader finishes, it releases READ(k) but DOES NOT clear
`read_marks[k]`. The mark stays as a hint until another reader
reuses or rewrites it under the lock. A stale mark held by no
active reader is harmless: the next checkpointer that wants to
advance past it will probe READ(k) and, finding no holder,
overwrite the mark.

## Lock vocabulary

The shm file carries a **logical locking byte range** (offset
`120`, 8 bytes — never read or written as data, only locked). The
following named locks live there:

| Name           | Byte offset | Width | Purpose                                |
|----------------|-------------|-------|----------------------------------------|
| WRITE          | 120         | 1     | Single writer at a time                |
| CHECKPOINT     | 121         | 1     | Single checkpointer at a time          |
| RECOVER        | 122         | 1     | Held during shm reconstruction         |
| READ(0)        | 123         | 1     | Reader using "no WAL" snapshot         |
| READ(1)        | 124         | 1     | Reader pinning read_marks[1]           |
| READ(2)        | 125         | 1     | Reader pinning read_marks[2]           |
| READ(3)        | 126         | 1     | Reader pinning read_marks[3]           |
| READ(4)        | 127         | 1     | Reader pinning read_marks[4]           |

Each lock is acquired in either **SHARED** or **EXCLUSIVE** mode.
The protocol below is normative.

The mapping of these logical locks onto OS primitives is
target-specific (POSIX `fcntl` byte-range advisory, Windows
`LockFileEx`, in-process mutex for `:memory:` and for unit tests).
The spec names locks; targets translate.

## Reader protocol

```
shm_reader_open(state) -> ReaderHandle:
    open or create {db_path}-shm
    if shm size < 32768 OR header copies disagree OR checksum invalid:
        run shm_recover(state)        # see below
    loop:
        snapshot mx_frame = header.mx_frame
        if mx_frame == 0:
            acquire SHARED on READ(0)
            return ReaderHandle { mark_index: 0, mx_frame: 0 }
        for k in 1..5:
            if read_marks[k] == mx_frame:
                if try_acquire SHARED on READ(k):
                    return ReaderHandle { mark_index: k, mx_frame }
        # No mark equals current mx_frame; try to claim one.
        for k in 1..5:
            if try_acquire EXCLUSIVE on READ(k):
                read_marks[k] = mx_frame
                downgrade EXCLUSIVE → SHARED on READ(k)
                return ReaderHandle { mark_index: k, mx_frame }
        # All five marks busy; either retry or fall back to READ(0).
        acquire SHARED on READ(0)
        return ReaderHandle { mark_index: 0, mx_frame: 0 }

shm_reader_close(handle):
    release SHARED on READ(handle.mark_index)
    # read_marks[k] is left as a hint; not cleared.
```

The reader's `wal_index` lookup uses the shm hash table directly,
NOT a per-process copy. This is the whole point: a writer in
process B that updates the hash table is visible to a reader in
process A on its next probe.

## Writer protocol

```
shm_writer_begin(state) -> WriterHandle:
    acquire EXCLUSIVE on WRITE
    re-read header; if header changed under us, refresh local view
    return WriterHandle { ... }

shm_writer_append(handle, page_number, frame_no):
    region = (frame_no - 1) / HASHTABLE_NPAGE
    if region >= mapped_regions:
        extend shm file by 32 KiB; map region
    slot = (page_number - 1) within region
    aPgno[region][slot] = page_number
    insert into aHash[region] via linear probe;
        if existing entry for page_number found, overwrite
        (latest-wins inside the region)

shm_writer_commit(handle, new_mx_frame, new_n_page):
    write header copy 1 (mx_frame, n_page, frame_checksum, change_counter+1)
    memory barrier
    write header copy 2 (identical bytes)
    memory barrier
    release EXCLUSIVE on WRITE
```

The commit ordering is critical: the WAL fsync (durability) must
have already completed at the file level before the shm header is
updated. Readers that see the new `mx_frame` MUST be able to read
the underlying WAL frames durably.

## Checkpointer protocol

```
shm_checkpoint(state, db_file):
    acquire EXCLUSIVE on CHECKPOINT
    # Determine how far we can backfill: smallest read mark in use.
    barrier_frame = mx_frame
    for k in 1..4:
        if any process holds SHARED on READ(k) AND read_marks[k] != 0:
            barrier_frame = min(barrier_frame, read_marks[k])
    for f in (n_backfill+1) .. barrier_frame:
        if f is the LATEST frame for its page within [1, barrier_frame]:
            copy frame f's page image into db_file
    fsync db_file
    n_backfill = barrier_frame
    if barrier_frame == mx_frame AND no readers on READ(1..4):
        # Full reset path: salt-roll WAL, zero shm header, mx_frame=0.
        run wal_checkpoint_reset(state)
        zero shm header (both copies); rebuild on next access.
    release EXCLUSIVE on CHECKPOINT
```

The CHECKPOINT lock excludes other checkpointers but NOT writers
or readers. The exclusion of writers and readers happens
implicitly via the `barrier_frame` calculation: a checkpoint
copies only frames behind the slowest reader, and the WAL itself
is appended past `mx_frame` by writers without disturbing earlier
frames.

## Recovery — shm missing or stale

```
shm_recover(state):
    acquire EXCLUSIVE on RECOVER
    # Re-check after lock; another process may have recovered already.
    if shm now valid: release; return.
    truncate shm to 32768 bytes (one region)
    rebuild header from the WAL:
        salts = read from WAL header
        scan WAL frames forward applying base wal protocol;
        record mx_frame = largest valid commit frame
        record frame_checksum at mx_frame
        n_page = db_size_after_commit on the mx_frame
    rebuild hash table:
        for f in 1..mx_frame:
            shm_writer_append(.., page_number_of_frame[f], f)
    write both header copies; recompute checksum
    release EXCLUSIVE on RECOVER
```

Recovery is idempotent and side-effect-free against the WAL: it
reads frames but never writes them. Two processes racing into
recovery serialize on the RECOVER exclusive lock; the loser
re-reads the now-valid header and proceeds.

A shm whose `version` field does not match the build's `version`
is treated as stale and triggers recovery.

## Multi-process coordination — overall protocol

1. Open shm; if invalid, recover.
2. Reader: claim a READ slot, snapshot mx_frame.
3. Writer: hold WRITE exclusive, append frames to WAL, fsync per
   the base wal pin matrix, then update shm header.
4. Checkpointer: hold CHECKPOINT exclusive, advance n_backfill up
   to the slowest reader's barrier_frame.
5. On any inconsistency (header checksum, version, torn copies),
   acquire RECOVER exclusive and rebuild shm from WAL frames.

Locks are independent: a reader holds only READ(k); a writer
holds WRITE; a checkpointer holds CHECKPOINT. A single process
acting as all three holds all three locks (no deadlock because
the order is fixed: WRITE < CHECKPOINT < RECOVER < READ(k)).

## Correctness pins

**SHM1. Shm is volatile.** Nothing in `{db_path}-shm` is part of
the durable on-disk contract. If the file is missing, zero-length,
truncated, or its header fails validation, recovery reconstructs
it from WAL frames. No data loss results.

**SHM2. Header double-copy + checksum.** The wal-index header is
written twice back-to-back; readers accept it only if both copies
are byte-identical AND the Fibonacci checksum over bytes 0..40
validates. Mismatch triggers shm_recover.

**SHM3. Host-endian.** Multi-byte fields in the shm file are
host-endian. The shm is per-host coordination state; cross-host
sharing is not supported (mainline-equivalent).

**SHM4. Five read marks max.** Exactly five `read_marks[0..4]`.
Mark 0 is permanently pinned at value 0 ("no WAL" snapshot). Marks
1..4 are claimable by readers under the matching READ(k) lock.

**SHM5. Reader holds SHARED on READ(k) for the session.** A
reader's snapshot lifetime equals the lifetime of its READ(k)
SHARED lock. Releasing the lock invalidates the snapshot.

**SHM6. read_marks[k] write requires EXCLUSIVE on READ(k).**
Updating a mark is a writer operation on shared state and must
exclude all other readers of that slot. Once written, the writer
downgrades to SHARED for the duration of its read session.

**SHM7. Writer holds EXCLUSIVE on WRITE.** Only one writer
appends to the WAL+shm at a time. The lock is held from
`shm_writer_begin` through `shm_writer_commit`.

**SHM8. Checkpointer holds EXCLUSIVE on CHECKPOINT.** Only one
checkpointer at a time; readers and writers proceed concurrently.

**SHM9. Checkpoint barrier.** A checkpointer may not set
`n_backfill` past the smallest non-zero `read_marks[k]` whose
READ(k) is currently held SHARED by some reader. This is the
guarantee that a reader's frames remain in the WAL until the
reader closes.

**SHM10. Latest-frame-wins inside the hash table.** When a writer
appends a frame for a page that already has an entry in the
shm hash, the new (higher) frame number replaces the old. This
mirrors the in-process wal_index rule (W7).

**SHM11. Hash function pinned.** `hash(p) = (p * 383) mod NSLOT`,
linear probing within the region. Mainline-compatible; required
for any hypothetical future cross-implementation shm sharing.

**SHM12. Region size pinned.** `REGION_SIZE = 32768` bytes.
`HASHTABLE_NPAGE = 4096`, `HASHTABLE_NPAGE_ONE = 4062` (region 0
is smaller because of the header), `HASHTABLE_NSLOT = 8192`.

**SHM13. WAL fsync precedes shm header update.** The base wal
pin matrix (W9/W15/W16) governs WAL fsync timing. The shm header
update in `shm_writer_commit` MUST occur AFTER the WAL frames are
durable per the connection's SyncLevel. A reader seeing
`mx_frame = N` must be able to read frame N's bytes.

**SHM14. Lock ordering: WRITE < CHECKPOINT < RECOVER < READ(k).**
A process that needs multiple locks acquires them in this order.
This eliminates lock-ordering deadlock between cooperating
processes.

**SHM15. RECOVER serializes shm reconstruction.** Concurrent
recoveries serialize on EXCLUSIVE RECOVER. The loser re-checks
the header after acquiring and skips reconstruction if another
process completed it.

**SHM16. shm_recover is read-only against the WAL.** Recovery
reads WAL frames but never writes or truncates the WAL. It
writes only the shm file.

**SHM17. mx_frame monotonic per checkpoint epoch.** Within a
single (`salt_1, salt_2`) generation, `mx_frame` only increases.
Salt-roll at checkpoint resets `mx_frame` to 0 and starts a new
epoch.

**SHM18. Stale read mark is harmless.** A `read_marks[k]` value
left behind by a closed reader is a hint, not a holder. A
checkpointer probes READ(k) for actual holders; the absence of a
holder lets it ignore the mark.

**SHM19. Version mismatch triggers recovery.** If header
`version != 3007000`, the shm is treated as stale and
reconstructed. The new header is written with the build's
version.

**SHM20. Mainline-compatible byte layout.** The shm file's byte
layout (header fields, region size, hash function, read mark
count, lock byte offsets) matches mainline SQLite's published
wal-index format. A leap process and a mainline `sqlite3` process
can share a database in WAL mode without corrupting the shm. This
is tested by alternating opens/commits between leap and mainline
on the same database file.

**SHM21. No torn header observable.** Because the header is
written twice with a barrier between, a reader that sees a torn
state (copies disagree) retries until both copies match. No
reader ever proceeds with a partial header.

**SHM22. No invented helpers.** Per §Generation scope. Targets
emit only what `shapes.json` declares plus what this spec
explicitly requires. Lock primitives are imported from the target
mapping (POSIX `fcntl`, Windows `LockFileEx`, etc.); the spec
does not invent new lock APIs.

## Phase pins

- **Phase WS0** — spec only (this part). `shapes.json` declares
  the type+function surface. NO target code emitted yet.
- **Phase WS1** — single-target prototype (Rust). Implements
  `shm_open`, `shm_reader_open/close`, `shm_writer_begin/append/commit`,
  `shm_checkpoint`, `shm_recover`. POSIX `fcntl` byte-range locks.
  Roundtrip fixture: leap process A + leap process B writing
  alternately to the same database file.
- **Phase WS2** — second target (C). Same shape surface;
  byte-identical shm file from the WS1 fixture.
- **Phase WS3** — mainline interop. leap-WS + mainline `sqlite3`
  alternating on the same database; both readers see consistent
  state; no shm corruption.
- **Phase WS4** — Windows lock mapping (`LockFileEx`); WSL
  fallback for advisory locks.
- **Phase WS5** — `:memory:` and single-process target mappings:
  in-process mutex stand-in for byte-range locks.
- **Phase WS6** — fault-injection: shm truncated mid-update,
  shm deleted between connections, shm with corrupted hash
  table; verify recovery from each.

## Regeneration envelope

- Spec line budget: ~350 lines (this file).
- shapes.json: ~120 lines.
- Target line budget (Phase WS1+): ~700–1000 lines per target.
  Hash table + lock wrappers + recovery scan + header double-copy
  protocol; comparable to wal itself.
- No external deps beyond stdlib + the io-backend part + OS lock
  primitives (target mappings own the primitive selection).
- Standalone runner per target for two-process fixture smoke.

## Open questions (defer)

1. **Cross-host shm.** Network filesystems (NFS, SMB) do not
   reliably support advisory byte-range locks or shared mmap.
   Mainline disables WAL mode on detected NFS. Defer to WS4.

2. **Heap-memory vfs.** For `:memory:` databases the shm is a
   process-local data structure, not a file. Defer to WS5; the
   shape surface is the same.

3. **Snapshot-advance at statement boundaries.** Mainline lets
   readers advance their snapshot mid-session. v1 leap-WAL
   snapshots at open and holds for the session (base wal Open Q4).
   wal-shm inherits that decision; revisit jointly.

4. **Hash table linear-probe distance bound.** Mainline caps probe
   length at NSLOT to avoid pathological page-number patterns.
   Confirm bound; encode in shapes if needed.

5. **n_backfill_attempted optimistic advance.** Mainline uses this
   to let one checkpointer reserve an intent before doing the I/O.
   v1 leap may skip; it serializes checkpointers with EXCLUSIVE
   CHECKPOINT regardless. Decide at WS3.
