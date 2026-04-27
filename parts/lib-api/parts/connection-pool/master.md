---
name: lib-api/connection-pool
kind: leaf
emits:
  rust:   { path: src-rust/connection_pool.rs }
  c:      { path: src-c/lib_api/connection_pool.c, headers: [src-c/lib_api/connection_pool.h] }
  zig:    { path: src-zig/lib_api/connection_pool.zig }
  go:     { path: src-go/lib_api/connection_pool.go }
  python: { path: src-python/lib_api/connection_pool.py }
---

# Connection pool: bounded multi-connection sharing

A `ConnectionPool` is a bounded set of `Connection` handles to the
same database file. Each connection carries its own per-step VDBE
state and its own prepared-statement cache; all connections in the
same pool share the underlying storage substrate (in-memory `Database`
in v1; pager + WAL in the on-disk follow-up). A connection is
checked out via `acquire`, used to run SQL, and returned to the pool
on drop / dispose.

This part is the canonical "many readers / serialized writer" surface
described in §lib-api master.md as a deferred sub-part.

## Scope (v1)

Admitted:

- `pool_new(path, max)` — opens (or attaches to) the database at
  `path`, allocates the pool with capacity `max ≥ 1`. The pool
  holds zero connections initially; connections are created lazily
  by `acquire`.
- `pool_acquire(pool)` — returns an in-use `PooledConnection`
  bound to one slot of the pool. If the pool is at capacity AND
  every slot is checked out, the call BLOCKS the caller (Pin 4)
  until a slot is returned.
- `connection_execute(conn, sql)` — executes `sql` against the
  connection's view of the shared database. v1 admits the same
  statement surface as `lib-api/prepared-statement` (SELECT,
  INSERT, UPDATE, DELETE; DDL via Done-on-step).
- `connection_drop(conn)` — automatic at scope exit / dispose.
  Returns the slot to the pool. If the connection is poisoned
  (Pin 6), the slot is freed but the underlying connection state
  is discarded; the next `acquire` of that slot reconstructs.

Deferred:

- Async / non-blocking `try_acquire` with a deadline — admitted at
  spec shape level (`AcquireResult::WouldBlock` is reserved) but not
  required in v1.
- Per-connection transaction affinity / sticky writer — covered by
  the underlying VDBE's transactional opcodes; the pool surface is
  intentionally agnostic.
- Health-check probes that run synthetic SQL on idle connections —
  v1 marks a connection poisoned only on observed runtime error
  (Pin 6); a periodic-probe surface is a follow-up.

## Declared shapes (`shapes.json`)

- `ConnectionPool { path, max, slots: list<Slot> }` — an opaque
  pool record. `path` is the logical database identifier (in v1,
  every distinct `path` yields a distinct shared store; same `path`
  reused in the same process attaches to the same store). `max` is
  the capacity bound. `slots` is a list of length `max` of `Slot`
  records.
- `Slot { state: SlotState, conn: optional<Connection> }` —
  `SlotState ∈ { Free, InUse, Poisoned }`. A `Free` slot may carry a
  cached `Connection` (fast re-acquire); an `InUse` slot has handed
  its `Connection` to a `PooledConnection`; a `Poisoned` slot is
  reclaimed by the next `acquire`.
- `Connection { prepared_cache: map<sql, PreparedStatement>,
  shared: SharedDb }` — owns its own prepared-statement cache;
  borrows the shared substrate through `SharedDb`.
- `SharedDb` — the shared substrate. Conceptually holds the
  `Database` (v1, in-memory) or the pager + WAL (on-disk follow-
  up). Multiple `Connection`s reference the same `SharedDb`.
- `PooledConnection` — a connection-and-slot-handle wrapper. Drop
  / dispose returns the slot.
- `AcquireResult` — variant: `Ready(PooledConnection) |
  WouldBlock`. v1 always returns `Ready` (after blocking).
- `PoolError` — variant: `CapacityZero | OpenFailed(reason) |
  ExecuteError(RuntimeCondition)`.
- Functions `pool_new`, `pool_acquire`, `connection_execute`,
  `connection_drop_returning_slot`.

## Algorithm

### `pool_new(path, max)`

```
if max < 1:
    return Err(CapacityZero)
shared = open_or_attach_shared(path)        # may produce OpenFailed
slots = list of `max` Slot{ state=Free, conn=absent }
return Ok(ConnectionPool { path, max, slots, shared })
```

`open_or_attach_shared` is the v1 hook that returns an existing
`SharedDb` for `path` if any connection in this process has already
attached, else creates a fresh one.

### `pool_acquire(pool)`

```
loop:
    under pool.lock:
        for i in 0..pool.max:
            if pool.slots[i].state == Poisoned:
                pool.slots[i] = Slot{ state=Free, conn=absent }   # health
            if pool.slots[i].state == Free:
                if pool.slots[i].conn is absent:
                    pool.slots[i].conn = make_connection(pool.shared)
                pool.slots[i].state = InUse
                return Ready(PooledConnection{ pool, slot=i })
        # no free slot; wait on pool.cond until a slot is returned
        pool.cond.wait(pool.lock)
```

The `pool.cond` notifier is signalled by every connection-drop
that returns a slot. The loop is mandatory: a wakeup may be
spurious or another waiter may steal the slot.

### `connection_execute(conn, sql)`

```
program = prepared_cache.get_or_compile(sql, conn.shared.schema)
state   = VdbeState::new(program, conn.shared)
status  = execute_program(program, state, conn.shared.lock())
                                          # serializes against
                                          # other connections that
                                          # touch shared mutable
                                          # state
match status:
    Ok           -> return Ok(rows_or_done)
    Error(cond)  -> mark this connection's slot Poisoned;
                    return Err(ExecuteError(cond))
```

The compiled program lives in the per-connection cache so every
connection prepares each distinct SQL string at most once. The
shared substrate's lock is taken for the duration of `step` —
this matches single-thread-at-a-time write semantics; concurrent
reads in v1 are also serialized (the on-disk follow-up may admit
shared-read locks via a reader-writer split — same shape).

### `connection_drop_returning_slot(slot_handle)`

```
under pool.lock:
    if connection was poisoned during execute:
        pool.slots[i] = Slot{ state=Poisoned, conn=absent }
    else:
        pool.slots[i].state = Free
        # pool.slots[i].conn is preserved, prepared cache reused next acquire
    pool.cond.notify_one()
```

## Correctness pins

1. **Capacity is bounded.** A pool with `max=N` hands out at most
   `N` `PooledConnection` instances simultaneously. The (N+1)th
   `acquire` BLOCKS until at least one outstanding connection is
   dropped. A pool with `max=0` is rejected at `pool_new` with
   `PoolError::CapacityZero`.

2. **One pool, one shared substrate.** All connections in the same
   pool see the same shared store. An `INSERT` issued through one
   `PooledConnection` and committed is visible to a subsequent
   `acquire`-then-`SELECT` on a different `PooledConnection` of the
   same pool.

3. **Per-connection prepared cache.** Each `Connection` keeps its
   own `prepared_cache` keyed by SQL text. The cache survives
   drop-then-reacquire of the same slot (the `Slot` retains its
   cached `Connection` while `Free`). Distinct connections may
   double-compile the same SQL; this is by design (Lane 4 win is
   per-connection prepare-once, NOT a shared-program cache).

4. **`acquire` blocks when full.** Implementations expose a
   blocking call. The block is on a condition variable / channel /
   equivalent that is signalled by every drop. A waiter MUST loop:
   wakeup is not a guarantee that a slot is free; another waiter
   may acquire it first.

5. **Drop returns the slot.** `PooledConnection`'s drop / dispose /
   `__exit__` MUST return the slot to the pool. A `Drop` that
   panics or unwinds MUST still mark the slot Free or Poisoned —
   never leave it InUse. (In Rust this is a panic-safe Drop; in
   Python this is a try/finally inside `__exit__`; in Go this is
   `defer pool.release(slot)`.)

6. **Poisoned connections are dropped, replaced lazily.** A
   `Connection` whose `connection_execute` produced
   `RuntimeCondition::Error(_)` for a non-recoverable failure (Pin
   6.1) is marked Poisoned at drop. The next `acquire` of that
   slot:
   - resets the slot to `Free, conn=absent`,
   - constructs a fresh `Connection` against the shared substrate.
   The pool capacity does NOT shrink; replacement is lazy.

   6.1. **Recoverable vs poisoning.** In v1, every
   `RuntimeCondition` returned through `connection_execute` is
   considered poisoning. Future revisions MAY classify a subset
   (e.g. `ConstraintViolation`) as recoverable; this is a spec
   widening, not narrowing.

7. **Pool is shareable across threads; connection is not.** The
   pool itself is safe to send between threads and accessed
   concurrently (the spec mandates an internal lock on the slot
   table — Pin 4 already implies this). A `PooledConnection`,
   once acquired, is owned by exactly one thread until dropped;
   sharing a single connection across threads is undefined. This
   matches `Send + !Sync` in the Rust target and the equivalent
   discipline in C / Zig / Go / Python targets.

8. **No leakage of internals.** `Connection` does not expose the
   raw `Database` / pager / WAL handle. Every interaction goes
   through `connection_execute`. This guarantees the shared lock
   in Pin 4 / Pin 7 is taken on every shared-substrate touch.

## Ambiguities and v1 scope decisions

- **`path` semantics in v1.** v1 stores everything in-memory; `path`
  is a logical pool key. Two `pool_new(":memory:abc", _)` calls in
  the same process MAY share substrate or MAY each open a fresh one
  — v1 picks per-pool-fresh (the simpler shape) and pins a
  follow-up for path-keyed attach.
- **Re-entrant acquire.** Calling `acquire` from a thread that
  already holds a `PooledConnection` of the same pool is admitted
  only if the pool has capacity ≥ 2; otherwise it deadlocks. v1
  does not detect this; the caller is responsible for sizing.
- **`max` bound.** No upper limit beyond the platform's. v1 admits
  any `usize` ≥ 1.
- **Statement surface.** `connection_execute` admits any single
  statement the underlying prepare/step pipeline admits (SELECT,
  INSERT, UPDATE, DELETE, DDL-as-Done). Multi-statement strings
  are deferred to the same follow-up as in
  `lib-api/prepared-statement`.

## Regeneration envelope

- Line budget: ~300-450 lines per target. The bulk is the slot-table
  state machine + the wait/notify path + the drop guard. Execute is
  short (delegates to the existing prepare/step pipeline).
- No new VDBE opcodes; no schema additions.
- Imports the target's standard concurrency primitives (Rust:
  `std::sync::{Arc, Mutex, Condvar}`; C: pthread mutex + cond; Go:
  `sync.Mutex` + `sync.Cond` or buffered channel; Python:
  `threading.Lock` + `threading.Condition`; Zig: `std.Thread.Mutex`
  + `std.Thread.Condition`). No external crates.

## Smoke probe (structural)

1. `pool_new(":mem:p1", 0)` returns `PoolError::CapacityZero`.
2. `pool_new(":mem:p1", 4)` succeeds.
3. Acquire 4 in a row from a `max=4` pool, then call `acquire` from
   a 5th caller on a separate thread: the 5th call BLOCKS until one
   of the first four is dropped.
4. Two sequential acquires of the same slot reuse the cached
   Connection's prepared cache (Pin 3): preparing `"SELECT 1"`
   compiles once on the first acquire; the second acquire hits the
   cache.
5. `INSERT` via connection A, drop A, acquire B, `SELECT` via B
   sees the inserted row (Pin 2, shared substrate).
6. A `connection_execute` that returns `ExecuteError(_)` followed
   by drop marks the slot Poisoned; the next acquire of that slot
   yields a fresh connection (Pin 6).
7. Pool is `Send + Sync` in Rust; spawning N threads each
   acquiring → executing → dropping in a loop terminates without
   deadlock (Pin 7).
