---
name: storage/locking
kind: leaf
inherits:
  - /parts/storage/master.md
  - /schema/shape.schema.json
emits:
  rust:   { path: src-rust/storage_lock.rs }
  c:      { path: src-c/storage/storage_lock.c, headers: [src-c/storage/storage_lock.h] }
  zig:    { path: src-zig/storage/storage_lock.zig }
  go:     { path: src-go/storage/storage_lock.go }
  python: { path: src-python/storage/storage_lock.py }
---

# Part: storage/locking

Concurrency-control state machine for the storage engine. Defines the
per-connection lock states and transitions for both **rollback-mode**
(single-file, advisory file lock on the main DB file) and **WAL-mode**
(shared-memory `*-shm` index with per-slot read/write/checkpoint
locks). Mainline SQLite's `lockingv3` model is the wire contract:
LEAP-SQLite's locking decisions must be byte-compatible at the file
boundary so that mainline processes can interleave with LEAP processes
without corruption.

This is an **inner concurrency primitive** — it owns no on-disk bytes
of its own (rollback mode). In WAL mode, the `*-shm` lock byte page is
a documented region of the shm file owned by `parts/storage/parts/wal`;
this part declares the *abstract* state machine, the wal sub-part owns
the bytes.

## Public surface

A storage `Database` holds exactly one `LockManager`. Every cursor open,
commit, and checkpoint walks the manager through a transition. The
manager exposes:

- `acquire(target)` — drive forward toward `target` state, raising
  `LOCK_BUSY` if some other process/connection holds an incompatible
  lock.
- `downgrade(target)` — drop privilege from a higher state to a lower
  one (`EXCLUSIVE → SHARED`, `RESERVED → SHARED`, `SHARED → UNLOCKED`).
  Cannot raise privilege; that requires `acquire`.
- `current()` — observation only; returns the present state.
- `mode()` — returns whether this manager is configured for rollback
  or WAL locking.

## State machine — rollback mode

Five states form a strictly ordered ladder:

```
UNLOCKED  →  SHARED  →  RESERVED  →  PENDING  →  EXCLUSIVE
```

Allowed forward transitions (no skipping):

| from | to | trigger |
|---|---|---|
| UNLOCKED  | SHARED    | first read on this connection |
| SHARED    | RESERVED  | first write on this connection (BEGIN of write txn) |
| RESERVED  | PENDING   | page-cache spill: forces blocking of new readers |
| PENDING   | EXCLUSIVE | commit body: writing main-file pages |

`PENDING` is the *only* state that blocks new SHARED acquisitions
while permitting existing ones to drain. `EXCLUSIVE` requires zero
other holders.

Allowed reverse transitions (privilege drop, never blocks):

| from | to |
|---|---|
| EXCLUSIVE | SHARED   |
| RESERVED  | SHARED   |
| SHARED    | UNLOCKED |
| PENDING   | SHARED   | (rollback path: aborted commit) |

Direct UNLOCKED→RESERVED, SHARED→PENDING, or any *upward* skip is a
spec violation and must raise `LOCK_INVALID_TRANSITION`.

## State machine — WAL mode

WAL mode does not use the rollback ladder on the main DB file. Instead
the `*-shm` shared-memory file carries a 136-byte locking page with
named byte-offsets for the following named lock slots (mainline
contract):

- `WRITE` — single writer permit.
- `CHECKPOINT` — checkpointer permit.
- `RECOVER` — WAL header recovery permit (held only during open).
- `READ_MARK[0..4]` — five reader slots, each pairing a u32 mark
  (`aReadMark[i]` in mainline) with one byte lock.

Transitions:

| operation | locks acquired | locks held during | locks released |
|---|---|---|---|
| begin read txn  | one `READ_MARK[i]` SHARED | duration of statement / txn | release on commit/rollback |
| begin write txn | `WRITE` EXCLUSIVE | duration of write | release on commit |
| checkpoint      | `CHECKPOINT` EXCLUSIVE + `READ_MARK[0]` EXCLUSIVE for restart | duration of checkpoint | release at end |
| recover         | `RECOVER` EXCLUSIVE | header rebuild only | release immediately |

Compatibility matrix (`X` = blocks, `.` = compatible):

```
            READ_MARK_S  WRITE_X  CHECKPOINT_X  RECOVER_X
READ_MARK_S      .          .          .            X
WRITE_X          .          X          .            X
CHECKPOINT_X     .          .          X            X
RECOVER_X        X          X          X            X
```

`READ_MARK[i]` slots are independently lockable; readers pick the
slot whose mark is `<=` the WAL's last commit mxFrame. Writer never
blocks readers (the WAL append-only design is the whole point);
checkpointer blocks only `READ_MARK[0]` while it resets the WAL.

## Correctness pins

1. **PIN 1 — Strict ladder.** In rollback mode, every `acquire(target)`
   must walk through every intermediate state in order. Skipping
   states is forbidden. If the caller asks for `EXCLUSIVE` from
   `UNLOCKED`, the manager internally walks `UNLOCKED → SHARED →
   RESERVED → PENDING → EXCLUSIVE`, raising `LOCK_BUSY` at the first
   step that fails and rolling all earlier acquired steps back to the
   pre-call state.

2. **PIN 2 — Pending blocks new readers.** Once any connection enters
   `PENDING`, the lock manager refuses to grant new `SHARED`
   acquisitions to other connections (they receive `LOCK_BUSY`).
   Existing `SHARED` holders are allowed to continue and complete.

3. **PIN 3 — Exclusive requires solitude.** `PENDING → EXCLUSIVE`
   succeeds only when zero other connections hold any lock above
   `UNLOCKED`. Otherwise raise `LOCK_BUSY`. This is the natural
   readers-drain barrier.

4. **PIN 4 — Reserved is unique.** At most one connection may hold
   `RESERVED` (or higher) at any moment. Concurrent `RESERVED` is a
   correctness bug and must raise `LOCK_BUSY` on the second attempter.

5. **PIN 5 — Downgrade is infallible (in-process).** A connection
   may always reduce its own privilege without consulting other
   connections. `EXCLUSIVE → SHARED` and `RESERVED → SHARED` retain
   the underlying SHARED grant; `SHARED → UNLOCKED` releases entirely.

6. **PIN 6 — Reverse-skip is allowed.** `EXCLUSIVE → SHARED` and
   `EXCLUSIVE → UNLOCKED` (via SHARED in one call) are both valid
   downgrade targets.

7. **PIN 7 — Idempotent re-acquire.** `acquire(state)` when already at
   exactly `state` is a no-op success. `acquire(lower)` when at a
   higher state is a spec violation (use `downgrade`).

8. **PIN 8 — WAL writer/reader independence.** A WAL writer holding
   `WRITE` does NOT block any `READ_MARK[*]` reader. Readers see a
   snapshot via mxFrame; new appended frames are invisible until they
   pick a higher mark.

9. **PIN 9 — WAL checkpoint restart-readers.** A checkpoint that
   intends to *reset* the WAL (truncate and recycle frame numbers)
   must additionally hold `READ_MARK[0]` exclusively, blocking new
   readers from picking the reset slot until the reset completes.
   Partial checkpoints (no reset) only need `CHECKPOINT`.

10. **PIN 10 — Recovery is exclusive.** Holding `RECOVER` blocks all
    other lock acquisitions. Released as soon as header reconstruction
    completes.

11. **PIN 11 — File-format compat.** In WAL mode, the byte-offsets
    of named locks within the `*-shm` page MUST match mainline's
    published layout (see `parts/storage/parts/wal`). Otherwise a
    mainline reader holding a lock at the byte level will not be
    visible to LEAP and vice versa.

12. **PIN 12 — Blocking policy is caller's concern.** `acquire`
    returns `LOCK_BUSY` immediately on contention; it does NOT spin
    or sleep. Any retry/backoff loop lives in the caller (typically
    pager or storage facade), where SQLite's `busy_handler` callback
    is composed.

13. **PIN 13 — Process-crash safety.** OS-level advisory file locks
    (rollback mode) and OS-level shm byte locks (WAL mode) MUST be
    released by the OS on process death so a crashed writer cannot
    permanently exclude others. This rules out pure-userspace
    spinlocks. In environments without OS-level advisory locks
    available, the manager runs in **single-process mode** (in-process
    Mutex) and emits a one-time `LOCK_SINGLE_PROCESS_MODE` diagnostic;
    it is documented that cross-process concurrent access is not
    safe in that configuration.

14. **PIN 14 — No reentrancy.** A connection that already holds
    `SHARED` and re-enters `acquire(SHARED)` on the same manager
    handle is idempotent (per PIN 7). But two sibling cursors on the
    same connection share one lock count; the manager refcounts at
    the connection level, not the cursor level. Releasing a shared
    cursor decrements; reaches zero only when all cursors close.

## Errors

- `LOCK_BUSY` — contention; the requested transition cannot complete
  without blocking another holder.
- `LOCK_INVALID_TRANSITION` — caller asked for a forward state skip
  or a privilege increase via `downgrade`.
- `LOCK_IO_ERROR` — underlying OS lock syscall failed for reasons
  other than contention (e.g. EBADF).
- `LOCK_SINGLE_PROCESS_MODE` — informational diagnostic emitted once
  on construction when OS-level advisory locks are unavailable. Not
  a hard failure.

## What this part does NOT own

- The retry / exponential-backoff loop. Lives in the storage facade
  or pager. This part's `acquire` is non-blocking.
- The on-disk byte layout of the `*-shm` lock page. Lives in
  `parts/storage/parts/wal`. This part declares the *named* lock
  slots and compatibility; the wal part materialises them.
- Deciding when to escalate `RESERVED → PENDING`. Pager makes that
  call when its dirty-page cache spills; this part only enforces
  that the transition is legal.
