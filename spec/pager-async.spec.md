# Pager — async I/O state machine — language-neutral spec (Phase 5)

Phase 5 extends the pager/storage layer to operate against an **async** I/O backend: submissions and completions are distinct events, and the pager explicitly models the time between a submission and its completion. This spec is complementary to `io-backend.spec.md` (§ "Phase 5a") and `wal.spec.md` (§ "Phase 4b"). The synchronous contract in `storage.spec.md` / `durability.spec.md` remains legal for targets where async I/O is not available (notably WASM); this spec defines the async-path behaviour that both C and Rust builds SHOULD target to unblock L4 (INSERT throughput).

## Scope and non-goals

**In scope (Phase 5):**
- An abstract state machine for the pager that models in-flight I/O explicitly.
- Ordering invariants for WAL frame writes and commit-fsync under async.
- Backpressure behaviour when the submission queue is full.
- Cancellation semantics (rollback, close) via a session-epoch counter.
- Single-writer + multi-reader concurrency discipline under async.

**Not in scope:**
- Concrete kernel/API mechanics — those live in `io-backend-iouring.spec.md` and `io-backend-kqueue.spec.md`.
- A second writer lane. The model remains single-writer; concurrency here means readers CAN submit concurrently with the writer, and multiple reads from the same reader can be outstanding.
- Shared-memory reader-writer visibility (wal-index / `<path>-shm`). That's Phase 4c.

## Abstract vocabulary

- **Submission** — a record matching `schema/io-submission.schema.json` handed to the backend.
- **Completion** — a record matching `schema/io-completion.schema.json` produced by the backend.
- **Submission queue (SQ)** — conceptual ordered list of submissions the pager has handed off but whose completions have not yet been observed. The backend may apply internal reordering within the bounds defined in `io-backend.spec.md` § "Ordering rules".
- **Completion queue (CQ)** — conceptual queue of completions the backend has produced but the pager has not yet consumed.
- **Epoch** — a monotonically increasing unsigned integer maintained per-session by the pager. Incremented on every rollback, close, or equivalent bulk-cancellation event. Stamped on every outgoing submission. On completion, any record whose stamped epoch is less than the pager's current epoch is dropped silently.
- **In-flight set (IFS)** — the multiset of `(user_data, epoch)` pairs for submissions the pager has handed to the backend but for which it has not yet received a completion OR whose completion has been received but deliberately dropped due to epoch staleness.

## Pager states

The pager occupies exactly one of the following states at any moment. Transitions are driven by SQL-level events (operation submitted by VDBE) and I/O events (completion observed).

```
                       +-------+
      (all sessions)   | IDLE  |
                       +---+---+
                           |
         SQL read   +------+-------+   SQL write
                    |              |
                    v              v
          +------------------+  +-------------------+
          | READ_SUBMITTED   |  | WRITE_SUBMITTED   |
          +---+----------+---+  +---+-----------+---+
              |          |          |           |
     all      |  timeout |  more    |           | all
  reads done  |  (opt)   |  writes  |           | writes done
              v          v          v           v
          +-------------------+  +-------------------+
          | READ_COMPLETING   |  | WRITE_COMPLETING  |
          +---+---------------+  +---+---------------+
              |                      |
              | all completions      | last write complete
              v                      v
              +------+         +-----+--------+
                     |         |
                     v         v
                  +--------------+
                  | FSYNC_SUBMITTED |
                  +-------+---------+
                          | fsync complete
                          v
                  +-----------------+
                  | FSYNC_COMPLETING|
                  +-------+---------+
                          | durable
                          v
                       COMMIT_ACK
                          |
                          v
                       back to IDLE
```

### State definitions

- **IDLE** — no I/O outstanding. The pager is free to accept any SQL-level op.
- **READ_SUBMITTED** — one or more read submissions are in the SQ. No write submissions. Additional reads MAY be submitted (multi-reader within a session). Writes MUST NOT be submitted in this state.
- **READ_COMPLETING** — reads are being drained from the CQ. The pager is NOT accepting new submissions; it is processing the completions it has already pulled.
- **WRITE_SUBMITTED** — one or more write submissions are in the SQ as part of an open transaction. All belong to the current writer session. Readers MAY ALSO submit reads concurrently (see § "Concurrency contract") but reads during writing observe pre-commit state by design — see § "Read visibility during writer".
- **WRITE_COMPLETING** — writes are draining from the CQ. Further writes MAY be submitted if the transaction is still open.
- **FSYNC_SUBMITTED** — the terminal fsync that seals a commit (for WAL: the fsync of the WAL sidecar after the commit-marker frame) has been handed to the backend. State MUST wait for the completion.
- **FSYNC_COMPLETING** — fsync completion observed; final bookkeeping (advancing last-commit-frame index, clearing dirty map) runs.
- **COMMIT_ACK** — transient state representing "commit observable from the outside". The SQL-level caller learns the commit succeeded here. Transitions immediately back to IDLE.
- **ROLLBACK_CANCELLING** (error path) — the pager has bumped the epoch; outstanding completions will be dropped. Any cancel submissions for in-flight ops have been issued. Stays here until either (a) all in-flight ops drain (completions observed then dropped) OR (b) the grace window expires (see § "Close / rollback deadline").
- **CLOSED** — terminal. Backend handles have been released; further submissions raise `STORAGE_SESSION_CLOSED`.

### Mandatory transitions

| From state        | Event                                       | To state            |
|-------------------|---------------------------------------------|---------------------|
| IDLE              | `SELECT` starts → first `io_read` submitted | READ_SUBMITTED      |
| IDLE              | `BEGIN` + first `io_write` submitted        | WRITE_SUBMITTED     |
| READ_SUBMITTED    | `io_read` completion observed               | READ_COMPLETING     |
| READ_COMPLETING   | CQ drained, no reads outstanding            | IDLE                |
| READ_COMPLETING   | another `io_read` submission queued         | READ_SUBMITTED      |
| WRITE_SUBMITTED   | all pre-commit writes submitted, `COMMIT` fires → `io_fsync` submitted | FSYNC_SUBMITTED |
| WRITE_SUBMITTED   | `io_write` completion observed              | WRITE_COMPLETING    |
| WRITE_COMPLETING  | more writes still pending in dirty map      | WRITE_SUBMITTED     |
| WRITE_COMPLETING  | all writes drained, `COMMIT` fires          | FSYNC_SUBMITTED     |
| FSYNC_SUBMITTED   | fsync completion observed, outcome=ok       | FSYNC_COMPLETING    |
| FSYNC_SUBMITTED   | fsync completion observed, outcome=error    | raise `STORAGE_WAL_COMMIT_FAILED`; → IDLE |
| FSYNC_COMPLETING  | bookkeeping done                            | COMMIT_ACK          |
| COMMIT_ACK        | (immediate)                                 | IDLE                |
| any active state  | `ROLLBACK` issued OR `close_database` called| ROLLBACK_CANCELLING |
| ROLLBACK_CANCELLING | IFS drained OR grace window expired       | IDLE or CLOSED      |

### Forbidden transitions (invariants)

- The pager MUST NOT transition from `WRITE_SUBMITTED` directly to `COMMIT_ACK` without going through `FSYNC_SUBMITTED` + `FSYNC_COMPLETING`. Commits without a durability barrier are forbidden.
- The pager MUST NOT issue a new `io_write` submission while in `FSYNC_SUBMITTED` or `FSYNC_COMPLETING`. The next writer transaction is blocked until `COMMIT_ACK`.
- The pager MUST NOT transition `CLOSED → any active state`. Close is terminal.

## Ordering invariants (WAL under async)

These are the load-bearing correctness rules. Any backend reordering that violates them is a spec bug in the backend.

1. **WAL frame ordering per commit.** For a single commit batching `N` dirty pages, the `N` write submissions MUST be ordered such that frame body bytes for frame `i` are durable before frame `i+1`'s are observable. The pager achieves this either by issuing linked submissions (`link_prior=true`) or by waiting for each completion before submitting the next. Backends MUST preserve the order; see `io-backend.spec.md` § "Ordering rules".

2. **Commit-marker-last.** The LAST frame of a commit carries the commit marker (`db_size_after_commit > 0`). Its write MUST be submitted AFTER all non-commit-marker frames of the same commit.

3. **Fsync-after-commit-marker.** The `io_fsync` that seals the commit MUST be submitted AFTER the commit-marker write AND MUST be ordered-after it. The commit is acknowledged to the VDBE ONLY when the fsync completion is observed with outcome=ok.

4. **Checkpoint-blocks-page-reuse.** A checkpoint operation (WAL → main-DB merge + WAL unlink) MUST complete its own fsync of the main DB file before any page whose image was in the checkpointed WAL can be reused for a new write. Concretely: the pager's page-to-frame index MUST NOT be cleared until the checkpoint's fsync-completion is observed.

5. **No read past the current commit epoch.** A reader MUST NOT observe a page image whose commit was not yet acknowledged. The pager SHOULD implement this by tagging in-memory page snapshots with a commit-epoch and filtering reads on that tag.

6. **Fsync_dir after rename.** When the checkpoint path performs an `io_rename` (for the atomic-rename commit of the main DB), a following `io_fsync_dir` on the parent directory MUST be ordered-after the rename completion. Required on ext4-without-dirsync; no-op on APFS.

## Concurrency contract (single-writer + multi-reader)

Under async, concurrent submissions are the norm. The pager enforces:

- **At most one open writer transaction per session.** A second `BEGIN` while in `WRITE_SUBMITTED` / `WRITE_COMPLETING` / `FSYNC_*` raises `STORAGE_WRITER_BUSY`.
- **Readers may submit reads while a writer is active.** Those reads observe the pre-commit state of the database (MVCC via the WAL frame index: reader sees the last-committed frame per page, not the in-flight dirty-map). This requires the pager to maintain a "last committed frame per page" snapshot at the moment the reader is born (at `BEGIN DEFERRED` or first read) and pin it until the reader is done.
- **Commit waits for reader quiesce** ONLY to the extent that the WAL's last-committed-frame index cannot be mutated while readers depend on the old value. In Phase 5 v1, the simple policy is: the writer's fsync-completion step publishes the new commit epoch atomically; readers born before that point continue reading their pinned epoch; readers born after observe the new epoch. No writer-reader blocking.
- **Checkpoint is cooperative.** A checkpoint runs only when: (a) no writer is in `WRITE_*` / `FSYNC_*`, AND (b) no reader is actively pinning a pre-checkpoint WAL epoch. If either is true, the checkpoint defers until they drain. In Phase 5 v1, the only checkpoint trigger is close-time (see `wal.spec.md` § "Phase 4b checkpoint protocol"); close is already a cooperative boundary, so the defer logic is trivial.

## Backpressure

The submission queue has a bounded capacity `SQ_CAPACITY` (backend-chosen; see platform specs — 128 for io_uring, 64 for kqueue). When the pager tries to submit and the SQ is full, the backend raises `IO_BACKEND_FULL_QUEUE` on the submission (delivered synchronously if the submission API is blocking, or as a rejected submission record if not).

Pager backpressure policy:

1. **Drain before submit.** Before submitting a new op, if the in-flight count is ≥ `SQ_CAPACITY / 2`, the pager SHOULD drain one completion from the CQ to make room. This is a cheap non-blocking poll; if the CQ is empty the pager proceeds anyway.
2. **Block-on-full (writer path).** If an actual `IO_BACKEND_FULL_QUEUE` is raised on a writer submission, the pager MUST block the calling VDBE opcode: it drains completions one-at-a-time from the CQ (blocking if the CQ is empty) until space frees, then re-submits. The VDBE caller observes this as a slow operation, not as an error.
3. **Reject-on-full (reader path, optional).** If a reader's submission hits `IO_BACKEND_FULL_QUEUE`, the pager MAY EITHER block (as above) OR reject with `STORAGE_READER_BACKPRESSURE`. v1 always blocks; rejection is reserved for a future "fast-fail reader" mode.
4. **No unbounded queueing.** The pager MUST NOT maintain its own unbounded pre-submission buffer in front of the backend's SQ. Unbounded buffering defeats backpressure and drives unbounded memory. If more than `SQ_CAPACITY` ops are logically pending, the excess MUST either block or propagate the full-queue condition per (2)/(3).

## Cancellation semantics

Cancellation covers three events:

1. **Transaction rollback.** `ROLLBACK` (implicit or explicit) makes every in-flight write meaningless. Pager protocol:
   a. Bump the session epoch by 1.
   b. For each in-flight submission with the old epoch, OPTIONALLY submit a `cancel` op with `cancel_target = user_data`. Backends that cannot cancel (e.g., a thread-pool whose worker is mid-syscall) MAY ignore the cancel op and let the syscall complete; the completion will still carry the old epoch and be dropped.
   c. Wait (with a grace window — see below) for the IFS to drain.
   d. Discard the dirty-map. The page cache is rewound to the last-committed epoch.
   e. Transition to IDLE.

2. **Database close.** `close_database` while I/O is in flight:
   a. Bump the session epoch (invalidates all outstanding submissions).
   b. For each open handle, submit a `close` op (last in its ordered chain after any already-submitted ops).
   c. Wait up to the close grace window (`CLOSE_GRACE_MS`, backend-chosen; default 5000 ms).
   d. On grace expiry, the pager emits a best-effort cancel for remaining submissions and releases handles anyway. Any resulting late completions arrive on a torn-down session and are dropped by the backend's epoch-check layer (handles are per-session).

3. **Backend crash / unrecoverable error.** If the backend raises `IO_BACKEND_BACKEND_CRASH` on any completion, the pager transitions to `ROLLBACK_CANCELLING`, bumps the epoch, and raises `STORAGE_IO_BACKEND_FAILED` to the caller. The session becomes CLOSED. Recovery requires a fresh `open_database`.

### Epoch stamping and drop discipline

- Every submission carries the epoch at submission time.
- Every completion carries the epoch echoed from its submission.
- The pager's completion consumer compares: if `completion.epoch < pager.current_epoch`, the completion is dropped silently (no user-visible effect, no error raised, no dirty-map update).
- Silent drop is correct because: if epoch advanced, every write from that epoch was invalidated by rollback-or-close; every read was targeting page-cache state that is now either gone (CLOSED) or irrelevant (post-rollback).

## Close / rollback deadline

- **Rollback grace:** 1000 ms default. If the IFS has not drained by then, the pager proceeds anyway. Any subsequent completions are dropped by epoch check.
- **Close grace:** 5000 ms default. Same semantics. The longer window exists because close MUST ensure any committed fsync actually landed durably; truncating a pending fsync is a durability violation.

Both grace windows are pager-level constants; backends do not observe them directly. A backend's own close of its submission/completion rings happens AFTER the pager releases the handle — by then the epoch guarantees correctness even if completions are still trickling in.

## Read visibility during writer

Per the WAL model (`wal.spec.md`), a read observes: for each page, the latest committed WAL frame (or the main-DB page if no frame). The writer's in-flight dirty pages are NOT visible to readers, by design. Implementation:

- The pager maintains two structures per session: `committed_frame_index` (page → last committed frame ID) and `dirty_map` (page → pending frame body, writer-only).
- A read consults `committed_frame_index` only, never `dirty_map`. It reads frame bytes from the WAL or the main DB.
- On commit (FSYNC_COMPLETING → COMMIT_ACK), `dirty_map` entries are promoted into `committed_frame_index` atomically (a single epoch-bump equivalent).

This ordering also means a read submitted at time `T` with epoch `E` CAN overlap a commit that publishes epoch `E+1` at time `T'` > `T`. The read sees epoch `E`'s image (its submission was stamped `E`). No torn read.

## New error conditions (Phase 5)

Added to the `STORAGE_*` surface:

- `STORAGE_SESSION_CLOSED` — submission attempted after close. Fields: `operation` (string).
- `STORAGE_WRITER_BUSY` — `BEGIN` attempted while another writer is active in the same session. Fields: none.
- `STORAGE_IO_BACKEND_FAILED` — the backend raised `IO_BACKEND_BACKEND_CRASH`. Fields: `reason` (string).
- `STORAGE_READER_BACKPRESSURE` — reader submission rejected due to full SQ in fast-fail mode (reserved; not raised in v1).

Backend-level errors (`IO_BACKEND_*`) surface through the completion record. The pager maps each to a `STORAGE_*` error before propagating to the VDBE:

| Backend condition           | Pager raises                                           |
|-----------------------------|--------------------------------------------------------|
| `IO_BACKEND_SHORT_READ`     | `STORAGE_FILE_IO { operation: "read" }`                |
| `IO_BACKEND_SHORT_WRITE`    | `STORAGE_FILE_IO { operation: "write" }`               |
| `IO_BACKEND_CANCELLED`      | silent drop (by design — cancellation is a local event)|
| `IO_BACKEND_EIO`            | `STORAGE_FILE_IO { operation: <op>, reason: "eio" }`   |
| `IO_BACKEND_ENOSPC`         | `STORAGE_DISK_FULL`                                    |
| `IO_BACKEND_ENOENT`         | `STORAGE_FILE_NOT_FOUND`                               |
| `IO_BACKEND_EACCES`         | `STORAGE_FILE_IO { operation: <op>, reason: "eacces" }`|
| `IO_BACKEND_EEXIST`         | `STORAGE_FILE_IO { operation: "open", reason: "eexist" }`|
| `IO_BACKEND_EINVAL`         | `STORAGE_FILE_IO { operation: <op>, reason: "einval" }`|
| `IO_BACKEND_EINTR`          | retried internally; never propagates                    |
| `IO_BACKEND_FULL_QUEUE`     | handled by backpressure; never propagates               |
| `IO_BACKEND_UNSUPPORTED`    | `STORAGE_IO_BACKEND_FAILED`                            |
| `IO_BACKEND_BACKEND_CRASH`  | `STORAGE_IO_BACKEND_FAILED`                            |
| `IO_BACKEND_TIMEOUT`        | pager-level retry once; then `STORAGE_FILE_IO`          |

## Test authority

Async-pager correctness is tested through the existing Phase 4b / future Phase 4c fixtures; the state machine itself is exercised indirectly when WAL correctness tests pass under the async backend. A dedicated fixture `tests/cross-build/phase5-pager-async.json` is introduced:

- **SM-1:** IDLE → READ_SUBMITTED → READ_COMPLETING → IDLE under a simple SELECT. Pass iff all completions observed before transition to IDLE.
- **SM-2:** Commit protocol: WRITE_SUBMITTED → FSYNC_SUBMITTED → COMMIT_ACK, with the invariant that fsync is submitted ONLY after all write completions. Verified by a harness that instruments the backend to log submission order.
- **SM-3:** Rollback during WRITE_SUBMITTED: epoch bump, IFS drains within grace, dirty-map cleared. Pass iff post-rollback state matches pre-BEGIN state byte-for-byte.
- **SM-4:** Close during FSYNC_SUBMITTED: close waits, fsync completes, commit is durable, then handles close. Pass iff the committed data is visible on reopen.
- **SM-5:** Backpressure: submit more ops than SQ_CAPACITY; pager blocks, drains, re-submits; final state correct.
- **SM-6:** Concurrent reader+writer: writer is mid-commit; reader sees pre-commit state; after writer's COMMIT_ACK, new reader sees post-commit state.

Cross-build equivalence: both C and Rust builds MUST produce identical observable behaviour on all SM-*. Byte-identity of WAL on-disk bytes is required (carried over from Phase 4b).

## Open questions (deliberately unresolved)

1. **Fast-fail reader mode.** `STORAGE_READER_BACKPRESSURE` is reserved but unused in v1. Decide based on L3 SELECT-throughput profiling after Phase 5b lands.
2. **Completion-batching threshold.** The pager currently drains completions one-at-a-time. Batched draining (consume up to K completions per syscall) may reduce per-op overhead; profile-driven.
3. **Per-handle epochs vs per-session epoch.** v1 uses one epoch per session. If future multi-database sessions exist, per-handle epochs would allow finer-grained cancellation. Deferred.
