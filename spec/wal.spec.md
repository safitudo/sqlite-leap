# WAL (Write-Ahead Log) — language-neutral spec

## Scope decomposition

WAL is a multi-phase feature. Landing it in one pass would collide with the existing flush-on-close storage model (see `durability.spec.md`) and require concurrent rewrites across storage / pager / file-io layers. The spec is therefore decomposed:

- **Phase 4a — WAL read-side consume + checkpoint-on-open.** Open a database that has a `<path>-wal` sidecar file (produced by mainline SQLite in WAL mode); parse the WAL frames; overlay committed frames onto the in-memory image; checkpoint by rewriting the main DB with merged state and truncating the WAL. Writes continue via the existing flush-on-close atomic-rename model (no write-side WAL in 4a).
- **Phase 4b — WAL write-side + incremental commit.** Re-architect the storage layer so that COMMIT appends WAL frames, COMMIT boundaries are fsynced, and checkpoint happens periodically or on close. Requires storage/pager rework. NOT in 4a scope.
- **Phase 4c — concurrent readers / shared memory.** `<path>-shm` file, wal-index, reader-writer visibility. NOT in 4a or 4b.

Phase 4a is the minimum shippable sub-phase. It gates **bidirectional file-format compatibility with mainline SQLite in WAL mode** — a published Done criterion for sqlite-leap. It does NOT gate the L4 INSERT throughput benchmark lane (that needs 4b).

## Phase 4a — WAL read-side consume + checkpoint-on-open

### WAL file format (normative — matches mainline SQLite WAL, big-endian integers)

#### WAL header (32 bytes, at file offset 0)

```
bytes  0.. 3 : magic number (big-endian u32)
                 0x377f0682 (little-endian-native frames)
                 0x377f0683 (big-endian-native frames)
bytes  4.. 7 : file format version (big-endian u32) = 3007000 decimal = 0x002DE218 hex (bytes: 00 2D E2 18). Cross-corroboration pin 2026-04-18: both C and Rust Phase 4a agents flagged that earlier drafts conflated this with 0x002DE098 (= 3006616 decimal) — the CORRECT hex representation of decimal 3007000 is 0x002DE218, and that is what mainline SQLite writes. Engines MUST validate against 0x002DE218 to accept mainline-written WALs.
bytes  8..11 : page size (big-endian u32) — MUST match main DB's page size (4096 in v1)
bytes 12..15 : checkpoint sequence number (big-endian u32)
bytes 16..19 : salt-1 (big-endian u32, random)
bytes 20..23 : salt-2 (big-endian u32, random)
bytes 24..27 : checksum-1 (big-endian u32) — running checksum over bytes 0..23
bytes 28..31 : checksum-2 (big-endian u32) — second 32-bit half of checksum
```

#### WAL frame (24-byte header + page-size bytes body, repeating)

Frame 0 starts at file offset 32. Frame N starts at offset `32 + N * (24 + page_size)`.

```
Frame header:
bytes  0.. 3 : page_number (big-endian u32) — the main-DB page this frame updates
bytes  4.. 7 : db_size_after_commit (big-endian u32) — non-zero on the LAST frame
                of a commit transaction (= new DB page count); zero on non-commit
                frames. This is the commit marker.
bytes  8..11 : salt-1 (big-endian u32) — MUST equal header's salt-1
bytes 12..15 : salt-2 (big-endian u32) — MUST equal header's salt-2
bytes 16..19 : checksum-1 (big-endian u32) — running checksum
bytes 20..23 : checksum-2 (big-endian u32)

Frame body:
bytes 24..(24+page_size-1) : page image (full page_size bytes)
```

#### Checksum algorithm (Fibonacci-style 32-bit, matches mainline)

Initial state `(s0, s1)` = header's salt-1, salt-2 for frame 0; for frame N > 0 carry state forward from frame N-1. Process 8-byte chunks of the frame header (bytes 0..7) + frame body (bytes 24..24+page_size) as big-endian u32 pairs:

```
for each 8-byte chunk (x_i, y_i):
    s0 = s0 + x_i + s1   (wrapping u32 add)
    s1 = s1 + y_i + s0   (wrapping u32 add)
```

Final (s0, s1) MUST equal the frame header's checksum-1, checksum-2 (at offsets 16..19, 20..23). If mismatch, the frame is corrupt or incomplete — halt frame processing, treat this and all subsequent frames as non-committed.

### Committed-frame recovery rule

When opening a DB with a `<path>-wal` sidecar:

1. Read WAL header (32 bytes). Validate magic, format version, page size.
2. Walk frames sequentially. For each frame:
   - Verify salts match header's salts.
   - Verify checksum matches the Fibonacci-style state. If not, STOP — this frame and all subsequent are not committed.
   - If `db_size_after_commit > 0`: this frame ends a commit transaction. All frames from the last commit marker (or from frame 0 if this is the first) are COMMITTED. Advance "last committed frame index" to this frame.
3. Build a page-index map: for each `page_number`, the latest COMMITTED frame's body is the authoritative page image. Uncommitted frames (past the last commit marker) are discarded.
4. If `db_size_after_commit` on the last commit marker is non-zero, the DB's page count may have grown — update the in-memory page count accordingly.

### Phase 4a open protocol

Extends `durability.spec.md` § "Open protocol":

1. Unlink `<path>.leap-stage` if present (existing behaviour).
2. If `<path>-wal` exists AND `<path>` exists AND `<path>` has a valid DB header:
   a. Read `<path>` into RAM (existing behaviour).
   b. Read `<path>-wal` frames per § "Committed-frame recovery rule" above.
   c. For each page_number in the page-index map, overwrite the in-RAM page with the frame body.
   d. The in-RAM image now reflects the post-WAL state.
   e. **Checkpoint-on-open**: write the merged in-RAM image back to `<path>` via the existing atomic-rename protocol (`durability.spec.md` § "Commit protocol"). On success, unlink `<path>-wal`. The WAL has been absorbed; subsequent mainline opens see a clean main DB with no pending WAL.
3. Else if `<path>-wal` exists but `<path>` is absent or invalid: raise `STORAGE_WAL_ORPHANED { wal_path }`. Pure defensive error; should never occur in a well-formed setup.
4. Else: no WAL to consume. Proceed with Phase 3d's normal open protocol.

### Phase 4a write path

Unchanged from Phase 3d. Writes flush to main DB via atomic-rename on close. Leap NEVER produces a `<path>-wal` file. A mainline process that subsequently opens a leap-written DB with `PRAGMA journal_mode=WAL` will begin generating a fresh WAL as it mutates — and the next leap open will consume it per § "Phase 4a open protocol".

### Phase 4a error conditions

- `STORAGE_WAL_CORRUPT_HEADER { wal_path, reason }` — magic / format version / page size mismatch.
- `STORAGE_WAL_ORPHANED { wal_path }` — WAL exists but main DB is missing or invalid.
- `STORAGE_WAL_CHECKSUM_MISMATCH` — treated as "truncated WAL", not as error. Frames after the mismatch are discarded as uncommitted. Not a halt-execution error; open proceeds with state-up-to-last-valid-commit.

### Phase 4a non-goals (restated)

- Writing WAL (`<path>-wal` creation / append) — Phase 4b.
- Shared memory (`<path>-shm`) — Phase 4c.
- PRAGMA journal_mode switching — future.
- WAL2 — not on roadmap.
- Incremental checkpoint (partial WAL drain) — future. 4a does a full checkpoint on open, always.

### Test authority (Phase 4a)

`tests/cross-build/phase4a.json` (if any) is the executable specification for behaviour that can be tested without mainline cooperation. The substantive gate is `tests/roundtrip_wal_readside.py`: a Python harness that:

1. Uses mainline `sqlite3` (3.41.2+) to create a DB in WAL mode and insert rows WITHOUT checkpointing (leave `<path>-wal` with uncheckpointed frames).
2. Closes mainline.
3. Opens the same path with leap; verifies: (a) all inserted rows are visible; (b) after close, `<path>-wal` no longer exists; (c) reopening with mainline sees the same rows.

If this round-trip passes on BOTH C and Rust builds, Phase 4a is green.

## Phase 4b — WAL write-side + incremental commit

### Scope

Phase 4a made leap able to consume mainline-written WAL sidecars (read-side + checkpoint-on-open). Phase 4b makes leap able to PRODUCE WAL sidecars of its own: COMMIT appends frames to `<path>-wal`, boundaries are fsynced, and checkpoints run either periodically or at close. This is the phase that unlocks the L4 INSERT throughput benchmark (WAL mode, single writer) and that makes mainline able to OPEN-AND-READ a leap-written DB that still has an uncheckpointed `<path>-wal` attached.

Phase 4b depends on Phase 5a (I/O backend abstraction — `spec/io-backend.spec.md`) for the async I/O seam. It can land correctness-first on the sync backend, with 5b plugging in io_uring afterward for the L4 lane.

### Write-side protocol

#### Opening in WAL-write mode

When leap opens a DB for writing AND the DB's header declares WAL mode (file-format byte 18 = 2, byte 19 = 2) OR the user explicitly set `PRAGMA journal_mode=WAL` in-session (future), leap enters WAL-write mode.

In WAL-write mode, the open protocol augments Phase 4a as follows:

1. Run Phase 4a's read-side consume + checkpoint (absorb any pending WAL frames, unlink the WAL).
2. Create a FRESH `<path>-wal` file: write a new 32-byte header (§ "WAL header") with:
   - magic = `0x377f0682` (LE-native frames — leap is LE-native on both targets in v1).
   - format version = `0x002DE218` (= 3007000 decimal; matches mainline; see Phase 4a pin).
   - page size = 4096.
   - checkpoint sequence = previous checkpoint's seq + 1 (tracked in-memory; starts at 0).
   - salt-1, salt-2 = two fresh u32 randomness values (source: `/dev/urandom` on Unix).
   - checksum-1, checksum-2 = Fibonacci checksum over bytes 0..23 with initial state (0, 0).
3. `fsync` the WAL file and its parent directory.
4. Leap is now in "WAL-write" open state; subsequent mutations append frames rather than rewriting the main DB.

#### COMMIT protocol

When a statement or batch completes mutating pages in memory AND the session is in WAL-write mode:

1. For each dirty page in memory (maintained by the pager's dirty-map):
   a. Build a 24-byte frame header (page_number, db_size_after_commit, salt-1, salt-2, checksum-1, checksum-2).
   b. For every frame EXCEPT the last of this commit, `db_size_after_commit = 0` (non-commit marker). For the LAST frame of the commit, `db_size_after_commit = new DB page count` (commit marker).
   c. Fibonacci checksum carries forward from the previous frame (or from the header's initial state for frame 0). Process the 8 frame-header bytes + page_size body bytes in 8-byte chunks per § "Checksum algorithm".
   d. Append frame header + page body to `<path>-wal`.
2. After the final frame is appended, `fsync(<path>-wal)`. This is the **commit point**; the commit is durable after this fsync succeeds.
3. If fsync fails: raise `STORAGE_WAL_COMMIT_FAILED { reason }`. The frames are physically present on disk but unflushed; the next open will detect them as uncommitted (the last frame won't have a committable checksum / won't be read past the last fsynced boundary) and will discard them per Phase 4a recovery rules. No mid-state corruption.
4. Clear the in-memory dirty-map. The page image now lives in WAL; in-memory page cache is consistent with what a reader would merge.

#### Checkpoint protocol

Checkpoint is when WAL frames are merged back into the main DB file and the WAL is truncated. Triggers:

- **On close** (always). Leap never leaves a WAL behind after a clean close.
- **On WAL size threshold** (future / optional). Mainline defaults to 1000 frames before auto-checkpoint.
- **On explicit `PRAGMA wal_checkpoint`** (future).

Phase 4b v1 implements close-time checkpoint only. The size-threshold + PRAGMA variants are future.

Close-time checkpoint:

1. Read WAL header and frames.
2. Apply the committed-frame page-index map to the in-memory image (exactly like Phase 4a).
3. Write the merged image to `<path>` via Phase 3d atomic-rename.
4. Unlink `<path>-wal`.
5. Release handle.

This is identical to Phase 4a's checkpoint-on-open path — the implementation SHOULD share code, with Phase 4a and Phase 4b both calling into a single `checkpoint_and_unlink(...)` helper.

### Recovery after partial WAL write

If leap crashes mid-COMMIT (between step 1 and step 2 of the COMMIT protocol above):

- Some frames are physically on disk but the fsync has not returned.
- The next open runs Phase 4a recovery: walks frames, verifies checksums.
- The last frame's checksum will be mathematically wrong (because its bytes were never fully flushed) OR its db_size_after_commit will be 0 (no commit marker reached), OR it will be truncated.
- Per Phase 4a, the recovery halts at the first checksum mismatch; prior commit markers (if any) are respected; the in-flight commit is discarded.

This means: **every fsynced commit is durable; every un-fsynced commit is cleanly discarded. No torn state.** This is the same durability property as Phase 3d atomic-rename, extended to incremental commit granularity.

### Salts and reuse

When a checkpoint runs and the WAL is unlinked, the next open creates a fresh WAL with NEW salts. This prevents a stale WAL from a previous session (resurrected by filesystem weirdness or backup) from being mistakenly replayed: its salts won't match. Mainline uses the same design.

### Error conditions (Phase 4b additions)

- `STORAGE_WAL_COMMIT_FAILED { reason }` — fsync failed at a commit boundary. The transaction is NOT committed from the caller's point of view.
- `STORAGE_WAL_WRITE_IO { reason, operation }` — any other I/O failure during WAL writing.
- `STORAGE_WAL_SALT_GENERATION_FAILED` — /dev/urandom (or equivalent) could not be read when creating a fresh WAL header. Very rare; fatal.

### Phase 4b test authority

Two gates:

1. **`tests/cross-build/phase4b.json`** — language-neutral fixtures that don't require mainline cooperation:
   - Single-statement INSERT followed by close: verifies WAL was written, frames are well-formed per spec, checkpoint-on-close drained the WAL, main DB has the inserted row.
   - Multiple INSERTs across multiple COMMITs: verifies each COMMIT's last frame is marked, checksums chain correctly, recovery-on-reopen works.
   - Simulated crash: write partial WAL (truncate at an un-fsynced boundary), reopen, verify the partial commit is discarded.
2. **`tests/roundtrip_wal_writeside.py`** — Python harness:
   - Leap writes a DB with INSERTs in WAL mode, close.
   - Mainline opens the same path AND its `<path>-wal` (if any left uncheckpointed).
   - Mainline verifies: same rows visible.
   - Mainline closes without checkpointing.
   - Leap reopens (runs Phase 4a consume on the remaining WAL) — still sees same rows.

### Phase 4b non-goals (restated)

- **Concurrent readers** — that's Phase 4c. Phase 4b is single-writer, single-reader, in a single process. No shared-memory region (`<path>-shm`) is created.
- **Incremental checkpoint (partial drain)** — v1 always does a full checkpoint on close. Mid-session checkpointing is future.
- **`PRAGMA journal_mode` switching** — v1 infers WAL mode from the file-format bytes and the build-time default. Runtime switching is future.
- **WAL2** — not on roadmap.
- **Auto-checkpoint based on WAL size** — future.

### Cross-build equivalence (Phase 4b)

This is load-bearing. Both C and Rust builds MUST:
- Generate identical WAL header bytes given identical salt inputs (determinism at the byte level; the Fibonacci-checksum and layout are spec-pinned).
- Append frames in identical order and with identical framing (same frame-header layout, same checksum carry, same page-image byte serialization).
- Raise identical error conditions in identical scenarios.
- Consume each other's WAL bytes round-trip-cleanly (C-written WAL, opened and recovered by Rust, matches the in-memory image, and vice versa).

The `phase4b.json` fixture MUST exercise a path where the harness can verify the on-disk WAL bytes against a canonical expected sequence (e.g., a fixture that seeds salts via a test-only `LEAP_WAL_SALT_OVERRIDE` env var so WAL bytes become deterministic).

### Implementation sequencing (recommended)

1. **Phase 5a first** (I/O backend abstraction, `io-backend.spec.md`). Phase 4b writes a LOT of I/O calls; having them behind the abstraction keeps the 4b codepath backend-agnostic.
2. **Phase 4b correctness on sync backend**. Get the semantics right; byte-identical cross-build.
3. **Phase 5b io_uring plugin**. Swap in the async backend for Linux; measure L4. No behavioural change, just throughput.

Trying to land 4b + 5b together without 5a first is a known anti-pattern — storage code gets riddled with `#ifdef LINUX` or `cfg(target_os)` branches that are painful to unwind. Spec pin: 5a is a hard prerequisite for 4b.

### Phase 4b as an L4 gate

L4 (INSERT throughput, WAL mode, single writer) per `spec/bench-lanes.spec.md` § "Lane 4" measures INSERT rate inside a single transaction. Phase 4b correctness makes the lane measurable; Phase 5b (io_uring) makes it FAST. The published number MUST come from the Linux x86_64 publication platform with io_uring active; macOS numbers on the kqueue backend (Phase 5c) are informational.
