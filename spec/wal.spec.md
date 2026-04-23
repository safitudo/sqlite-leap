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

### Phase 4a MVP status update (2026-04-21)

The Phase 4a MVP refusal of multi-frame WALs (`STORAGE_WAL_CORRUPT_HEADER { reason: "multi-frame-not-implemented" }`) is LIFTED in Phase 4b. The multi-frame recovery rule defined in § "Committed-frame recovery rule" is now a required-by-both-phases implementation. The `phase4a.json` fixture still exercises only the error paths and the zero-frame case; multi-frame recovery is tested by `phase4b.json`.

### Test authority (Phase 4a)

`tests/cross-build/phase4a.json` (if any) is the executable specification for behaviour that can be tested without mainline cooperation. The substantive gate is `tests/roundtrip_wal_readside.py`: a Python harness that:

1. Uses mainline `sqlite3` (3.41.2+) to create a DB in WAL mode and insert rows WITHOUT checkpointing (leave `<path>-wal` with uncheckpointed frames).
2. Closes mainline.
3. Opens the same path with leap; verifies: (a) all inserted rows are visible; (b) after close, `<path>-wal` no longer exists; (c) reopening with mainline sees the same rows.

If this round-trip passes on BOTH C and Rust builds, Phase 4a is green.

## Phase 4b — WAL write-side + incremental commit

### Scope

Phase 4a made leap able to consume mainline-written WAL sidecars (read-side + checkpoint-on-open). Phase 4b makes leap able to PRODUCE WAL sidecars of its own: a COMMIT appends frames to `<path>-wal`, boundaries are fsynced, and checkpoints run either periodically or at close. This is the phase that unlocks the L4 INSERT throughput benchmark (WAL mode, single writer) and that makes mainline able to OPEN-AND-READ a leap-written DB that still has an uncheckpointed `<path>-wal` attached.

Phase 4b depends on Phase 5a (I/O backend abstraction — `spec/io-backend.spec.md`) for the async I/O seam. It can land correctness-first on the sync backend, with 5b plugging in io_uring afterward for the L4 lane.

### Session activation (Phase 4b v1)

A session enters WAL-write mode when ALL of the following hold:

1. The session is disk-backed (`open_database(path)`, not `create_memory_database()`).
2. The environment variable `LEAP_WAL_APPEND` is set to `"1"` at process start, OR the main DB's file-format bytes 18 and 19 both equal 2 (mainline's "WAL mode" declaration), OR a future-reserved `PRAGMA journal_mode=WAL` has been issued (v1 accepts this as a no-op and records the intent — future work wires it through).
3. No Phase 4a error has been raised during open.

If any condition is false, the session falls back to Phase 3d atomic-rename-on-close (existing behaviour). This gate is observable: `LEAP_WAL_APPEND=1` is the authoritative v1 activation knob for benchmarks and tests.

### Pager dirty-set — the page-granular write contract

Phase 4b requires the storage layer to know WHICH pages changed since the last commit so it can emit a frame only for those pages, not the entire image. The language-neutral contract:

- Each disk-backed Database maintains a **committed image**: the byte sequence that is authoritative on disk after the most recent successful commit (either the main file's contents at open time, or the image produced by the most recent WAL-append commit).
- The committed image is partitioned into fixed-size **pages** of `page_size` bytes (v1: 4096). Page numbering is 1-based, matching mainline SQLite's convention. Page N occupies bytes `(N-1) * page_size .. N * page_size - 1`.
- On each commit, the storage layer produces a **new image** (the bytes that would be written by the Phase 3d slurp path). The **dirty set** for this commit is the set of page numbers where the new image differs from the committed image, PLUS every new page numbered above the committed image's page count (growth pages).
- For pages in the dirty set, the writer emits exactly one WAL frame per page; non-dirty pages do not produce frames.
- On commit success (fsync of the last frame returns ok), the committed image is replaced by the new image atomically (in-memory).

The contract is deliberately silent on HOW the dirty set is computed. Two acceptable implementations:

- **Snapshot-diff:** serialise the new image, compare 4096-byte chunks against the committed image, emit a frame for each changed chunk. O(image_size) per commit; memory-light (no pager rework). This is the Phase 4b v1 implementation for both targets.
- **Pager-tracked:** every mutation path (`insert_row`, `update_row`, `delete_row`, B-tree split, freelist grow, schema change) marks affected pages in a per-session bitmap; commit iterates the bitmap. O(dirty_set_size) per commit. Future optimisation.

Both implementations MUST produce byte-identical WAL frame streams for identical mutation sequences. The snapshot-diff approach is the v1 canonical implementation because it is local to the commit path and does not require invasive changes to every mutation site.

### Write-side protocol

### Write-side protocol

#### Opening in WAL-write mode

When leap opens a disk-backed DB AND § "Session activation" conditions are satisfied, the session enters WAL-write mode.

Open protocol (extends Phase 4a):

1. Unlink `<path>.leap-stage` if present (Phase 3d cleanup).
2. If `<path>-wal` exists, process it per § "Committed-frame recovery rule" AND § "Phase 4a open protocol" step 2. The new multi-frame reader (§ "Committed-frame recovery — multi-frame implementation" below) must be in place for this step to succeed on a WAL that contains committed frames. After Phase 4a's checkpoint-on-open completes, `<path>-wal` has been unlinked; the main DB is now fully up-to-date.
3. If the session is entering WAL-write mode:
   a. Create a FRESH `<path>-wal` file: write a new 32-byte header (§ "WAL header") with:
      - magic = `0x377f0682` (LE-native frames — leap is LE-native on both targets in v1).
      - format version = `0x002DE218` (= 3007000 decimal; matches mainline; see Phase 4a pin).
      - page size = 4096.
      - checkpoint sequence = previous checkpoint's seq + 1 (tracked in-memory; starts at 0 on first entry per session; on a session that has already run through at least one checkpoint, the stored value persists and increments).
      - salt-1, salt-2 = two fresh u32 random values. Source: `/dev/urandom` (Unix). For deterministic fixtures, the environment variable `LEAP_WAL_SALT_OVERRIDE` MAY be set to the literal sixteen hex characters `<salt1_hex><salt2_hex>`; when present, the two u32 values are decoded from that string (big-endian) and used in place of randomness. This knob is TEST-ONLY; production code MUST NOT set it.
      - checksum-1, checksum-2 = Fibonacci checksum over bytes 0..23 with initial state `(0, 0)`.
   b. Write the 32-byte header to the WAL file.
   c. `fsync(<path>-wal)`. Parent-directory fsync is deferred to the first commit (avoids a gratuitous dir-sync for read-only sessions that happen to be in WAL-write mode).
4. Capture the **committed image** of the main DB at this point (the freshly-read bytes). On open, this equals the disk contents of `<path>`. All subsequent commits diff against this snapshot.
5. Leap is now in WAL-write mode; subsequent mutations append frames rather than rewriting the main DB.

Transient partial-WAL-header cleanup: if step 3b fails (I/O error writing the header), the WAL file may be partially or non-existent on disk. The caller raises `STORAGE_WAL_WRITE_IO { reason, operation: "open" }`; the file is best-effort unlinked. A subsequent open re-tries the sequence.

#### COMMIT protocol

A **commit** is the boundary at which in-memory mutations become durable. In v1, a commit is triggered by one of:

- Explicit SQL-level `COMMIT` statement (future — currently compiles to a no-op; see § "Compat with existing BEGIN/COMMIT tokens" below).
- Auto-commit after a single top-level mutating statement that is NOT inside a BEGIN/COMMIT block (future — currently folded into the close-time checkpoint).
- Session close (`close_database`) while in WAL-write mode and dirty. This is the only Phase 4b v1 commit trigger; it is sufficient to unlock the L4 benchmark because the lane 4 workload is a single BEGIN/COMMIT block.

The commit procedure:

1. Compute the dirty set per § "Pager dirty-set" (snapshot-diff the new image against the committed image).
2. If the dirty set is empty, the commit is a no-op; return success without writing frames.
3. Let `N` = the new image's page count (= ceil(|new_image| / page_size)). Append `|dirty_set|` frames to `<path>-wal`, one per dirty page, in ascending page-number order:
   a. Build a 24-byte frame header (page_number, db_size_after_commit, salt-1, salt-2, checksum-1, checksum-2).
   b. For every frame EXCEPT the last of this commit, `db_size_after_commit = 0` (non-commit marker). For the LAST frame of the commit, `db_size_after_commit = N` (commit marker).
   c. Fibonacci checksum carries forward from the previous frame (or from the header's initial state for the first frame after the WAL header: the header's post-validation state is `(checksum-1, checksum-2)` from the WAL header's bytes 24..31 — derived by running the checksum over the header's bytes 0..23 with seed `(0, 0)`).
   d. Compute checksum over 8-byte chunks of the frame header's bytes 0..7 (page_number + db_size_after_commit) followed by the page_size body bytes. See § "Checksum algorithm". The frame's `checksum-1`, `checksum-2` fields (bytes 16..23) are the resulting `(s0, s1)` values.
   e. Append the full frame (24-byte header + page_size body bytes) to `<path>-wal`.
4. After the final frame is appended, `fsync(<path>-wal)`. This is the **commit point**; the commit is durable after this fsync succeeds.
5. On the FIRST successful commit of a session (where the WAL transitions from zero-frame to one-or-more-frames), additionally `fsync` the parent directory of `<path>` to ensure the WAL file's inode creation is durable. Subsequent commits do not re-fsync the directory.
6. If any step above fails: raise `STORAGE_WAL_COMMIT_FAILED { reason }` with `reason` naming the failing operation (`"write"`, `"sync"`, `"sync_dir"`). The frames MAY be physically present on disk but unflushed; the next open's recovery walk (§ "Committed-frame recovery rule") will detect the last frame as un-fsynced (its checksum won't have a committable chain or its db_size_after_commit won't be reached, OR simply: the WAL file will be shorter than the last-attempted-commit because write() failed mid-write). In all such cases, partial commits are cleanly discarded. No torn state.
7. On commit success, promote the new image to the committed image (atomic in-memory pointer swap). Clear any pager-tracked dirty bitmap.

#### Compat with existing BEGIN/COMMIT tokens

Phase 4b v1 does NOT wire the SQL-level `BEGIN` and `COMMIT` tokens to the per-statement commit path. They remain compile to `[Init, Halt]` as in prior phases; the net effect of a `BEGIN ... COMMIT` block is one close-time commit that emits frames for all pages touched by statements in the block. A future phase may introduce true per-statement autocommit (one WAL flush per statement) and true `COMMIT`-triggered flushing; for v1, the unit of commit is `close_database`, which is sufficient for the L4 benchmark (one giant transaction, one commit).

This is a spec deliberate: the critical path for benchmark unlock is eliminating O(db_size) work on close, not adding fsyncs mid-transaction. Adding more fsyncs would slow the benchmark, not accelerate it.

#### Committed-frame recovery — multi-frame implementation (supersedes Phase 4a MVP)

Phase 4a's MVP refused multi-frame WALs with `STORAGE_WAL_CORRUPT_HEADER { reason: "multi-frame-not-implemented" }`. Phase 4b lifts this refusal: a WAL file with frames is walked and its committed frames are overlaid onto the in-memory image, exactly as § "Committed-frame recovery rule" already prescribes. Concretely:

1. Read and validate the 32-byte WAL header per Phase 4a. Capture the header's post-checksum state: `(h_s0, h_s1) = (header.checksum-1, header.checksum-2)` (bytes 24..31 of the header).
2. Let `running = (h_s0, h_s1)`. Walk frames sequentially starting at file offset 32. For each frame `F_i`:
   a. Read 24 frame-header bytes + `page_size` body bytes. If fewer bytes remain in the file, the WAL is truncated at this point; stop walking (frames from the last commit marker onward are discarded — see step 3).
   b. Verify `F_i.salt-1 == header.salt-1` AND `F_i.salt-2 == header.salt-2`. If not, stop walking; all frames from the last commit marker onward are discarded.
   c. Compute `(new_s0, new_s1)` by applying the Fibonacci checksum to `F_i`'s header bytes 0..7 followed by body bytes, with input state `running`. Compare `(new_s0, new_s1)` against `(F_i.checksum-1, F_i.checksum-2)`. If not equal, stop walking; discard as in (b).
   d. Update `running = (new_s0, new_s1)`.
   e. Note `F_i`'s `page_number` and `db_size_after_commit` fields. If `db_size_after_commit > 0`, record that all frames from `F_last_commit + 1` through `i` (inclusive) form one **committed commit**, advance `F_last_commit = i`, and note the committed DB page count as `db_size_after_commit`.
3. After the walk, the committed commits are the frames in `[0 .. F_last_commit]`. Any frames past `F_last_commit` are discarded (uncommitted).
4. Build a **page-index map**: for each `page_number` appearing in any committed frame, the body of the LAST (highest index) such committed frame is the authoritative page image. Walk committed frames in ascending order; for each, overwrite the map entry for its `page_number`.
5. Apply the page-index map to the in-memory image: for each `(page_number, body)` entry, the in-memory bytes at offset `(page_number - 1) * page_size` are replaced with `body`. If the image is shorter than `page_number * page_size` (growth case), extend it with the overlaid body (and zero-fill any intervening pages).
6. If the last committed commit's `db_size_after_commit` is non-zero, truncate (or extend) the in-memory image to exactly `db_size_after_commit * page_size` bytes. This handles both DB growth AND shrinkage across commits.
7. The in-memory image is now the post-recovery state. Proceed to checkpoint (§ "Checkpoint protocol") as in Phase 4a.

Notes on correctness:

- **Torn frames** (step 2a): a crash mid-frame-write leaves a WAL whose tail is truncated. The walk stops at the truncated frame; no partial body is interpreted.
- **Un-fsynced frames** (step 2c): a crash between frame body write and fsync leaves the kernel free to have written none, some, or all of the last commit's frames. The checksum chain catches this: any frame whose body was never flushed produces a wrong checksum when read back, and the walk halts. If a checksum IS valid, the frame WAS flushed (or the kernel wrote ahead-of-order, in which case the checksum chain still catches any subsequent unflushed frame).
- **Salt rejection** (step 2b): a stale WAL from a previous session (or a resurrected backup) has salts that don't match the header; the first frame with a salt mismatch halts the walk. The fresh header created on the next session's WAL-write mode entry ensures subsequent opens see only this session's frames.
- **Empty-WAL regression**: a WAL file that is exactly 32 bytes (header only, no frames) produces an empty page-index map; the overlay is a no-op. This is the Phase 4a zero-frame case — unchanged.

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

This is load-bearing at the WAL layer. Both C and Rust builds MUST:

- Generate identical WAL header bytes given identical salt inputs. The header's 32 bytes are entirely spec-pinned; determinism is mechanical.
- For a given (main-DB bytes on disk, in-memory new-DB bytes, salts) triple: produce identical WAL frames — identical page_number ordering, identical commit-marker placement, identical Fibonacci checksum chain, identical body bytes.
- Raise identical error conditions in identical scenarios.
- Consume each other's WAL bytes round-trip-cleanly — C-written WAL opened and recovered by Rust reproduces the same in-memory image, and vice versa.

Scope clarification: the "WAL frame body bytes" are drawn directly from the engine's serialised main-DB image. If C and Rust disagree on how they serialise the logical DB state into bytes (for example, different page-count layouts or different freelist bookkeeping), their WAL frames will mechanically differ at the body level even when every frame's envelope is correctly formed. Byte-identity at the WAL layer therefore inherits any prior byte-identity divergence at the storage-serialisation layer. Phase 4b's cross-build gate is: given identical input DB bytes and identical in-memory post-mutation bytes, the WAL produced is byte-identical. Divergence in upstream serialisation is a separate concern and is addressed by the bidirectional-roundtrip suite (which is logical-level, not byte-level).

The `phase4b.json` fixture exercises deterministic paths where both WAL headers AND frame envelopes are comparable byte-for-byte (the 32-byte header is always byte-identical between the two targets when `LEAP_WAL_SALT_OVERRIDE` is set; frame envelopes match when the underlying serialisation matches).

### Implementation sequencing (recommended)

1. **Phase 5a first** (I/O backend abstraction, `io-backend.spec.md`). Phase 4b writes a LOT of I/O calls; having them behind the abstraction keeps the 4b codepath backend-agnostic.
2. **Phase 4b correctness on sync backend**. Get the semantics right; byte-identical cross-build.
3. **Phase 5b io_uring plugin**. Swap in the async backend for Linux; measure L4. No behavioural change, just throughput.

Trying to land 4b + 5b together without 5a first is a known anti-pattern — storage code gets riddled with `#ifdef LINUX` or `cfg(target_os)` branches that are painful to unwind. Spec pin: 5a is a hard prerequisite for 4b.

### Phase 4b as an L4 gate

L4 (INSERT throughput, WAL mode, single writer) per `spec/bench-lanes.spec.md` § "Lane 4" measures INSERT rate inside a single transaction. Phase 4b correctness makes the lane measurable; Phase 5b (io_uring) makes it FAST. The published number MUST come from the Linux x86_64 publication platform with io_uring active; macOS numbers on the kqueue backend (Phase 5c) are informational.
