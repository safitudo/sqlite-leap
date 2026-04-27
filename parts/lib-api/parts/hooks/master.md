---
name: lib-api/hooks
kind: leaf
emits:
  rust:   { path: src-rust/lib_api/hooks.rs }
  c:      { path: src-c/lib_api/hooks.c, headers: [src-c/lib_api/hooks.h] }
  zig:    { path: src-zig/lib_api/hooks.zig }
  go:     { path: src-go/lib_api/hooks.go }
  python: { path: src-python/lib_api/hooks.py }
---

# Hooks: commit / rollback / update / preupdate notifications

The hooks API gives the embedder runtime notification of database
mutations. Four installable callbacks, all per-connection, all
optional, all replaceable:

- **commit_hook** — fires immediately BEFORE a transaction commits;
  may veto the commit by returning non-zero.
- **rollback_hook** — fires AFTER a transaction is rolled back.
- **update_hook** — fires AFTER each successful row INSERT, UPDATE,
  or DELETE on a regular table, carrying (op, schema, table, rowid).
- **preupdate_hook** — fires BEFORE each row mutation, with access
  to old- and new-row values. Strictly richer than update_hook;
  installable independently.

Mainline SQLite published surface:
sqlite.org/c3ref/commit_hook.html, sqlite.org/c3ref/update_hook.html,
sqlite.org/c3ref/preupdate_hook.html.

## Scope (v1)

Admitted:

- `set_commit_hook(db, cb, user_data)` — install/replace/clear.
- `set_rollback_hook(db, cb, user_data)` — install/replace/clear.
- `set_update_hook(db, cb, user_data)` — install/replace/clear.
- `set_preupdate_hook(db, cb, user_data)` — install/replace/clear.
- Per-row firing on the v1 DML opcodes
  (`Insert`, `Update`, `Delete`) within the VDBE.
- Commit / rollback firing on the transaction-control opcodes
  (`Commit`, `Rollback`) and on implicit auto-commit / auto-rollback.
- Veto: a non-zero commit_hook return MUST cause the engine to
  promote the in-flight commit into a rollback (Pin 6).

Deferred:

- `wal_hook` (post-checkpoint notification) — covered by
  `/parts/storage/parts/wal` follow-up.
- `commit_hook` veto value semantics beyond zero/non-zero (mainline
  uses an int return; the spec models it as `CommitDecision`
  variant — see Pin 6).
- Trigger-internal updates firing the update_hook — admitted as
  Pin 11 but trigger compilation is itself v1.1.
- preupdate access to system tables (`sqlite_*`) — Pin 13 excludes.

## Declared shapes (`shapes.json`)

- `UpdateOp` — variant: `Insert | Update | Delete`.
- `UpdateNotification` — record `{ op, schema, table, rowid }`.
- `PreUpdateNotification` — richer record carrying op, table,
  rowid_old, rowid_new (rowid_new differs from rowid_old only when
  the UPDATE rewrites the rowid), plus `old_row` / `new_row`
  accessors (present-or-absent depending on op; see Pin 9).
- `CommitDecision` — variant: `Commit | Veto`.
- `CommitHookCallback`, `RollbackHookCallback`, `UpdateHookCallback`,
  `PreUpdateHookCallback` — callback shapes.
- `HooksState` — per-connection record holding all four optional
  callbacks + their user-data handles.
- Functions: the four `set_*_hook` plus `clear_*_hook` shorthands;
  internal `fire_*` entry points the VDBE / transaction layer call.

## Algorithm

### `set_commit_hook(db, callback, user_data)`

```
prior = db.hooks_state.commit
db.hooks_state.commit = present({ callback, user_data })
return prior   # for parity with mainline's "returns previous user_data"
```

(Targets that prefer to drop the prior-callback return MAY do so;
spec does not require it. mainline's published API returns the
previous user-data pointer.)

Same shape for `set_rollback_hook`, `set_update_hook`,
`set_preupdate_hook`.

### `fire_update(db, op, schema, table, rowid)` — VDBE-internal

Called by the VDBE immediately AFTER a successful `Insert`,
`Update`, or `Delete` opcode commits its row mutation to the
in-memory page state (still inside the transaction; not yet on
disk). Pseudo-code:

```
if db.hooks_state.update is absent:
    return
notif = UpdateNotification { op, schema, table, rowid }
(db.hooks_state.update.callback)(notif, db.hooks_state.update.user_data)
# return value is discarded — update_hook cannot veto
```

### `fire_preupdate(db, op, schema, table, rowid_old, rowid_new, old_row_accessor, new_row_accessor)`

Called BEFORE the corresponding row mutation, with accessors that
the callback uses to materialize old / new column values on demand
(spec deliberately abstracts this — see Pin 9).

```
if db.hooks_state.preupdate is absent:
    return
notif = PreUpdateNotification { op, schema, table,
                                 rowid_old, rowid_new,
                                 old_row_accessor, new_row_accessor }
(db.hooks_state.preupdate.callback)(notif, db.hooks_state.preupdate.user_data)
```

### `fire_commit(db) -> CommitDecision`

Called by the transaction layer immediately before flushing the
commit record to the WAL / journal. If commit is vetoed, the
transaction layer rolls back instead and the rollback_hook fires
(Pin 6).

```
if db.hooks_state.commit is absent:
    return CommitDecision::Commit
decision = (db.hooks_state.commit.callback)(db.hooks_state.commit.user_data)
return decision
```

### `fire_rollback(db)`

Called by the transaction layer after a rollback completes (the
WAL / journal has been reverted, in-memory page state has been
discarded).

```
if db.hooks_state.rollback is absent:
    return
(db.hooks_state.rollback.callback)(db.hooks_state.rollback.user_data)
```

## Correctness pins

1. **All four hooks are per-connection, independently
   installable.** Setting one does not affect the others. Setting
   `update` while `commit` is already installed leaves `commit`
   unchanged. Concurrent connections have independent slots.
2. **Set with absent callback clears.** `set_*_hook(db, absent,
   absent)` is the canonical clear; subsequent fires short-circuit.
3. **`update_hook` fires AFTER the row mutation, BEFORE commit.**
   The row is in the transaction's in-memory page state when the
   callback runs; a sibling read through the same connection sees
   the mutation; a read on another connection does NOT (the
   transaction has not committed). If the transaction subsequently
   rolls back, the update_hook fire is NOT retracted — the embedder
   is expected to handle that via the rollback_hook.
4. **`update_hook` fires once per row, in mutation order.** A
   statement that touches N rows produces exactly N callbacks; the
   order matches the VDBE's row-emission order (which for a
   straight INSERT / UPDATE / DELETE is the iteration order over
   the source). Multi-row INSERT VALUES fires once per VALUES
   tuple in source order.
5. **`update_hook` does NOT fire for rows in `sqlite_*` system
   tables.** DDL that mutates `sqlite_master` / `sqlite_schema`
   does not fire. Implicit-rowid table mutations fire normally.
6. **`commit_hook` vetoes via `CommitDecision::Veto`.** When a
   callback returns `Veto`, the transaction layer:
   (a) does NOT flush the commit record;
   (b) initiates a rollback (revert in-memory pages + WAL);
   (c) fires `rollback_hook` if installed;
   (d) the originating `step` returns
       `StepResult::Error(CommitVetoed)` (a new RuntimeCondition
       case, owned by `/parts/core`).
   The veto path MUST leave the database byte-identical to its
   pre-transaction state.
7. **`commit_hook` fires once per transaction, BEFORE durability.**
   Inside an explicit `BEGIN ... COMMIT` block, fire on COMMIT;
   inside an auto-commit statement (no explicit BEGIN), fire when
   the implicit commit triggers. The fire is BEFORE the WAL frame
   header / journal commit record is written — the hook is the
   last hold-point at which veto is observable.
8. **`rollback_hook` fires AFTER the rollback completes.** Both
   explicit ROLLBACK and implicit auto-rollback (commit veto from
   Pin 6, transaction-error path) fire it. The hook fires exactly
   once per ended transaction; it does not fire for SAVEPOINT
   release / rollback (savepoints deferred).
9. **`preupdate_hook` fires BEFORE the row mutation; old / new
   row payloads are present-or-absent by op.** For Insert: old_row
   is absent, new_row is present. For Delete: old_row is present,
   new_row is absent. For Update: both are present, AND if the
   UPDATE rewrites the rowid, `rowid_old != rowid_new`. Old/new
   row materialization is on-demand (the spec models it as an
   accessor object, not a pre-computed Vec, because materializing
   N columns × M rows is expensive and most preupdate users only
   read 1-2 columns).
10. **`update_hook` and `preupdate_hook` fire as a pair when both
    installed.** preupdate fires first (BEFORE mutation), then the
    mutation applies, then update fires (AFTER mutation). The two
    callbacks see the same (op, schema, table, rowid) — preupdate's
    `rowid_new` equals update's `rowid` for a non-rowid-rewriting
    UPDATE, and matches Insert's rowid / Delete's rowid otherwise.
11. **Trigger-internal mutations (deferred) fire hooks per row.**
    When v1.1 ships triggers, a row mutation inside a trigger body
    fires update_hook / preupdate_hook the same as a top-level
    mutation. This pin reserves the semantics; v1 has no triggers.
12. **Hooks MUST NOT call recursive prepare / step / DDL on the
    same `db`.** Same restriction as authorizer (Pin 13 there).
    Spec does not require detection; targets MAY add a re-entry
    flag. Reading non-mutated state via a sibling connection is
    permitted.
13. **`preupdate_hook` does not fire for `sqlite_*` system tables.**
    Same exclusion as update_hook (Pin 5).
14. **`commit_hook` veto on auto-commit promotes the statement
    error.** A bare `INSERT INTO t VALUES (1)` with a vetoing
    commit_hook installed: the statement reaches end-of-VDBE,
    fire_commit returns Veto, the transaction rolls back, and
    `step` returns `Error(CommitVetoed)`. The row is NOT visible
    to subsequent statements.
15. **Setting a hook returns the prior user_data handle (mainline-
    parity).** Targets that don't have a free-form return slot in
    their canonical set-callback signature MAY drop this; spec
    permits both shapes. The pin is that the OBSERVABLE hook state
    after `set` is exactly the new (callback, user_data) pair —
    no leftover prior-callback fires after the replacement
    completes.
16. **Hook fires are synchronous and on the same thread / coroutine
    as the operation that triggered them.** No background-thread
    delivery; no event-loop deferral. The transaction blocks until
    the callback returns. Targets MAY make this explicit in their
    callback signature (e.g. Rust's `FnMut`); spec pins the
    synchrony.
17. **Hook state survives `clear_authorizer` / authorizer changes.**
    Authorizer and hooks are independent slots on the connection.
    Re-preparing a statement under a new authorizer does not touch
    the hooks state.

## Ambiguities and v1 scope decisions

- **Hook ordering across multiple installed callbacks.** Each kind
  has at most ONE callback installed at a time. Replacing
  `update_hook` mid-transaction means rows mutated before the
  replacement fired the old callback; rows after the replacement
  fire the new one — there is no "callback list."
- **Commit veto inside explicit BEGIN.** A vetoed COMMIT inside an
  explicit transaction returns Error(CommitVetoed) on the COMMIT
  statement itself; subsequent statements on that connection see
  the rolled-back state.
- **rowid for WITHOUT ROWID tables.** v1 does not implement
  WITHOUT ROWID; the pin is reserved that the rowid field, if /
  when v1.1 admits them, will carry the synthetic primary-key
  hash mainline uses. v1 hook fires only fire for rowid tables.
- **Preupdate on a row INSERTed in the same transaction then
  UPDATEd later.** Two preupdate fires + two update fires; the
  second preupdate's `old_row` reflects the in-transaction state
  (the inserted values), not pre-transaction.
- **What happens if a hook callback raises (panics / throws)?**
  Spec-level: raising is undefined behavior. Targets MAY catch
  and convert to a runtime condition (Rust catch_unwind across
  FFI; Python try/except in the wrapper; Go recover); spec does
  not require it.

## Regeneration envelope

- Line budget: ~200-300 lines per target. Bulk: the four
  `set_*_hook` functions + the four `fire_*` entry points + the
  veto-promotion path inside fire_commit.
- No new VDBE opcodes. `Insert`, `Update`, `Delete` opcodes call
  `fire_preupdate` before / `fire_update` after via
  hooks-aware variants of the existing dispatch (the spec for
  `/parts/vdbe/parts/opcodes-dml` admits an optional hook-fire
  side-channel; see that part).
- New RuntimeCondition variant: `CommitVetoed` (added to
  `/parts/core`).
- Imports: `Database`, `RuntimeCondition`, `Value` (for row-
  accessor return types).

## Smoke probe (structural)

1. `set_update_hook(db, count_calls); INSERT INTO t VALUES (1),(2),
   (3)` fires the hook 3 times in order, each with `op=Insert,
   table="t"`, rowids 1/2/3 (or whatever the rowid allocator
   chose).
2. `set_update_hook(db, ...); UPDATE t SET a=a+1 WHERE id IN
   (1,2)` fires twice, op=Update, rowids 1 then 2.
3. `set_commit_hook(db, |_| Veto); INSERT INTO t VALUES (1)`:
   step returns `Error(CommitVetoed)`; subsequent
   `SELECT count(*) FROM t` returns 0.
4. With both update_hook and rollback_hook installed: a vetoed
   commit fires update_hook (the row mutation happened in-memory
   first), then rollback_hook (the rollback that the veto
   triggered). The embedder is expected to reconcile via the
   rollback_hook.
5. `set_preupdate_hook(db, capture); UPDATE t SET a=99 WHERE
   id=1`: callback sees `op=Update, old_row.a=<prior>,
   new_row.a=99, rowid_old=1, rowid_new=1`.
6. `DELETE FROM t WHERE id=1` with preupdate fires
   `op=Delete, old_row=<prior row>, new_row=absent, rowid_old=1,
   rowid_new=absent`.
7. `set_update_hook(db, A); INSERT ... ; set_update_hook(db, B);
   INSERT ...` — first INSERT fires A; second fires B; A is not
   re-fired.
8. DDL (`CREATE TABLE u(...)`) does NOT fire update_hook even
   though it mutates sqlite_schema (Pin 5).
