---
name: storage/savepoints
kind: leaf
shapes: ./shapes.json
inherits:
  - /parts/storage/parts/wal/master.md
  - /parts/storage/parts/pager/master.md
---

# Part: storage/savepoints

The savepoint stack: a LIFO of named **savepoint frames** that
captures enough state to revert page changes (and schema deltas)
made since the frame was pushed. Lives between the VDBE
`OpcodeSavepoint` handler and the pager / WAL.

This is the foundational design pass. **No target code is emitted
from this part yet.** The deliverable is the language-neutral spec
(this file) plus the shape declarations (`shapes.json`). Targets
will be added in a subsequent wave once the spec is stable.

## What a savepoint frame captures

Each frame on the stack remembers, at the moment of push:

- **`name`** — the user-supplied identifier (owned string).
- **`wal_mark`** — the frame number `mx_frame` at push time, OR
  the equivalent rollback-mode journal offset. This is the cut
  point. Anything beyond this mark is "post-savepoint" and is
  what `ROLLBACK TO` undoes.
- **`schema_mark`** — the schema-version cookie at push time,
  plus a snapshot of the in-memory schema descriptor (table /
  index / view list). DDL inside the savepoint mutates the
  in-memory schema; rollback restores from this snapshot.
- **`page_dirty_set_mark`** — the cardinality of the pager's
  dirty-page set at push time. Used by checkpoint-deferral logic
  (storage pin S8): no checkpoint may run while any savepoint
  frame is open, because checkpoint folds WAL frames into the
  main file and that would break frame-mark-based revert.

The frame does NOT copy page images. Revert reads the pre-savepoint
page images out of the WAL (or the rollback-mode journal) and
re-applies them. This is mainline-compatible: savepoints are
cheap to push, costly to roll back, never duplicate page data.

## Stack discipline

The stack is a LIFO. Push order matches `SAVEPOINT` order. Pop
order is governed by `ReleaseSavepoint` and `RollbackToSavepoint`,
each of which scans the stack from the top to find a name match.

```
SavepointStore = {
    frames: list<SavepointFrame>,            # LIFO; deepest at index 0
    implicit_outer_open: bool,               # did Savepoint silently BEGIN?
}

push_savepoint(store, name, ctx) -> result<unit, RuntimeCondition>:
    if len(store.frames) >= SAVEPOINT_STACK_MAX_DEPTH:
        return Err(SavepointStackOverflow)
    if ctx.in_transaction == false:
        ctx.begin_transaction()
        store.implicit_outer_open = (len(store.frames) == 0)
    frame = SavepointFrame {
        name:                copy(name),
        wal_mark:             ctx.current_wal_mark(),
        schema_mark:          ctx.snapshot_schema(),
        page_dirty_set_mark:  ctx.dirty_page_count(),
    }
    store.frames.push(frame)
    return Ok

release_savepoint(store, name, ctx) -> result<unit, RuntimeCondition>:
    idx = find_innermost(store.frames, name)
    if idx is None: return Err(SavepointNotFound)
    # Discard idx and every frame above. Their changes merge into
    # whatever frame (or outer transaction) sits at idx-1.
    store.frames.truncate(idx)
    if len(store.frames) == 0 and store.implicit_outer_open:
        ctx.commit_transaction()
        store.implicit_outer_open = false
    return Ok

rollback_to_savepoint(store, name, ctx) -> result<unit, RuntimeCondition>:
    idx = find_innermost(store.frames, name)
    if idx is None: return Err(SavepointNotFound)
    target_frame = store.frames[idx]
    # Revert all changes made since target_frame's marks.
    ctx.revert_pages_to(target_frame.wal_mark)
    ctx.restore_schema(target_frame.schema_mark)
    # Discard frames above idx; KEEP target_frame on the stack.
    store.frames.truncate(idx + 1)
    return Ok

find_innermost(frames, name):
    for k in (len(frames) - 1) downto 0:
        if frames[k].name == name: return k
    return None
```

## Interaction with WAL

`wal_mark` for the WAL backend is the integer `mx_frame` at push
time. To revert, the pager / WAL replays the wal-index up to
`wal_mark` only — frames `> wal_mark` are treated as not present
for the purposes of post-revert reads.

Concretely:

- New writes after a savepoint push append new WAL frames as
  usual (via `wal_append_frame`).
- `RollbackTo` calls `wal_truncate_to(wal_mark)` (or equivalent
  in-memory wal-index truncation if frames haven't been
  fsynced yet); see WAL pin W6 — frames past `mx_frame` are
  inert, so truncating the index is enough.
- `Release` performs no WAL action; the appended frames remain
  and will be folded into the outer transaction's commit (or
  the implicit transaction's commit).

Crash before the outer transaction commits: WAL recovery
(WAL §"Recovery on open") naturally drops every frame past the
last commit-frame. Savepoint-only frames (no commit marker) are
already inert and are discarded automatically. **The savepoint
stack itself is in-memory only; it does not survive a crash.**
This is mainline-compatible: a crashed process loses all
savepoints with the rest of the in-flight transaction.

## Interaction with rollback-mode journal

When the database is in rollback mode (no WAL), `wal_mark`
becomes a journal offset: the byte offset of the next-to-write
slot in the rollback journal at push time. `revert_pages_to`
re-reads the journal pages from that offset onward and writes
them back into the database file. The rollback journal stays
intact across savepoint operations within a single outer
transaction; it is truncated only at outer COMMIT.

## Interaction with checkpoint

Checkpoint folds committed WAL frames into the main database
file and resets the WAL (WAL pin W8 — salts roll). Once
salts roll, every `wal_mark` captured by an open savepoint
frame is dead — those frames no longer exist in the live
region.

Therefore: **no checkpoint may run while any savepoint frame
is open** (storage pin S8). The pager's checkpoint scheduler
must consult `SavepointStore.frames.is_empty()` and defer
otherwise.

## DDL inside a savepoint

`schema_mark` captures the in-memory schema before DDL runs.
DDL mutates the in-memory schema descriptor and writes a
schema-cookie bump to the database header (page 1 byte 40).
On `RollbackTo`:

1. The schema descriptor is restored from `schema_mark`.
2. The page-revert step (`revert_pages_to(wal_mark)`) restores
   page 1 (with its schema cookie) to the pre-DDL state, so
   on-disk schema and in-memory schema agree again.

DDL inside a savepoint that is later RELEASEd merges normally:
the in-memory schema continues to reflect the DDL, and the
schema-cookie page is part of the WAL frames that the outer
commit will write.

Open question: prepared-statement invalidation when DDL inside
a savepoint is rolled back. Mainline invalidates all prepared
statements when the schema cookie changes. Leap's prepared-
statement cache (TBD) must observe this; for v1 we recompile
on schema change, so any rollback of DDL re-invalidates the
cache implicitly.

## Stack-depth bound

`SAVEPOINT_STACK_MAX_DEPTH = 32` (compile-time constant). Beyond
this we'd be encouraging pathological nesting; mainline does not
enforce a hard cap, but the leap-WAL salt-roll-on-checkpoint
discipline (pin W8) means deep savepoint stacks block checkpoint
indefinitely. A 32-deep stack already covers every reasonable
nested-transaction pattern.

## Names

Names are owned `string` values, byte-for-byte compared. No case
folding. Duplicate names on the stack are allowed (LIFO scan
resolves to the innermost match — pin S5).

## Correctness pins

**S1. Stack is LIFO; deepest frame is at index 0.** Push appends
to the top; pop / truncate operates from the top. The "innermost"
frame of a duplicate-name pair is the most recently pushed one
(highest index), and `find_innermost` scans from the top.

**S2. Implicit BEGIN on first push.** If `push_savepoint` runs
when no transaction is open, the storage layer begins one and
records `implicit_outer_open = true`. When the outermost
savepoint is later released and the stack becomes empty, that
implicit transaction COMMITs (pin S4). If a `RollbackTo`
unwinds the implicit-begin frame's changes but leaves the frame
itself on the stack (pin S5b), `implicit_outer_open` stays true
until either a matching RELEASE or an explicit ROLLBACK clears it.

**S3. Explicit BEGIN coexists.** If `BEGIN` was already executed
by the caller, savepoint push does NOT begin another transaction
and `implicit_outer_open` stays false. RELEASE of the outermost
savepoint in this case does NOT commit; only the matching
explicit COMMIT closes the outer transaction.

**S4. Outermost RELEASE commits the implicit outer.** When
`release_savepoint` empties the stack AND `implicit_outer_open`
is true, the storage layer calls `commit_transaction()` and
clears the flag. The order matters: the merge-upward step
finishes first (truncate the stack), then the commit runs.

**S5. Duplicate-name resolution: innermost wins.** When a name
appears twice on the stack, both `RELEASE` and `ROLLBACK TO`
match the topmost (innermost) occurrence. Frames below it with
the same name are unaffected.

**S5b. RollbackTo KEEPS the target frame.** `rollback_to_savepoint`
truncates the stack to `idx + 1`, NOT `idx`. The user can
`ROLLBACK TO x` repeatedly without `x` disappearing.

**S6. Schema is part of the savepoint state.** Each frame
captures the schema descriptor at push time. RollbackTo restores
it. Release merges (the most-recent in-memory schema wins, as
the merged frame's deltas are kept).

**S7. Stack-depth cap is enforced.** Push beyond
`SAVEPOINT_STACK_MAX_DEPTH = 32` returns
`SavepointStackOverflow`. The frame is NOT pushed; the
transaction state is unchanged.

**S8. No checkpoint while any savepoint is open.** The pager's
checkpoint scheduler consults `SavepointStore.frames.is_empty()`.
While frames are open, checkpoint defers. This protects every
captured `wal_mark` from being invalidated by a salt roll
(WAL pin W8). When the last frame releases (or the outer
transaction commits / rolls back), checkpoint becomes eligible
again.

**S9. Stack does not survive a crash.** `SavepointStore` is
in-memory. WAL recovery treats every uncommitted frame as
dropped (WAL pin W10). After recovery, the savepoint stack is
empty and `implicit_outer_open = false`.

**S10. Page revert delegates to pager / WAL.** This part owns
the savepoint *protocol*; the pager owns the page-image
restoration. `revert_pages_to(wal_mark)` is a method on the
pager / WAL context, not on the savepoint stack.

**S11. Schema cookie consistency post-revert.** After
`RollbackTo`, the in-memory schema descriptor and the on-disk
schema cookie (page 1 byte 40) MUST agree. The pager's page
revert restores page 1; the savepoint store's schema restore
restores in-memory state; these two operations together are
atomic from the caller's perspective.

**S12. Names are owned, byte-comparable, case-sensitive.** No
case folding, no Unicode normalization, no whitespace trimming.

**S13. SavepointNotFound is the exclusive name-error.** Both
`release_savepoint` and `rollback_to_savepoint` raise
`SavepointNotFound` when the name is not on the stack. They do
not silently no-op.

**S14. No invented helpers.** Per
`/spec/part-conventions.spec.md` §Generation scope. Targets
emit only what `shapes.json` declares plus what this spec
explicitly requires.

## Phase pins

- **Phase SP0** — spec only (this part). `shapes.json` declares
  the type+function surface. NO target code emitted yet.
- **Phase SP1** — single-target prototype (Rust). Implements
  `push_savepoint`, `release_savepoint`, `rollback_to_savepoint`
  against the existing `mem-store` backend (in-memory pages, no
  WAL). Smoke covers single-frame revert + nested 3-deep.
- **Phase SP2** — second target (C) for parity. Same shape
  surface, identical observable semantics on the SP1 fixtures.
- **Phase SP3** — WAL integration. `wal_mark` becomes
  `mx_frame`; `revert_pages_to` truncates the wal-index; smoke
  covers savepoint across multiple WAL frames.
- **Phase SP4** — DDL-inside-savepoint smoke (CREATE TABLE in a
  savepoint, ROLLBACK TO, verify table not in schema and not on
  disk).
- **Phase SP5** — checkpoint-deferral integration with the
  pager scheduler.

## Regeneration envelope

- Spec line budget: ~280 lines (this file).
- shapes.json: ~80 lines.
- Target line budget (Phase SP1+): ~250-400 lines per target. The
  store is structurally a Vec / array of small records plus a
  handful of stack operations; most of the surface is the
  pager-callback boundary.
- No external deps beyond stdlib + the pager / WAL parts.

## Open questions (for follow-up phases)

1. **Two-phase savepoint commit on the outermost RELEASE.** When
   the implicit outer transaction commits as part of the
   outermost RELEASE (pin S4), should we expose a callback so
   higher layers (e.g. the embedding's prepared-statement cache)
   can hook the commit? Defer until a real consumer asks.

2. **Savepoint replay across reconnect.** Mainline does not
   persist savepoints. Some higher-level engines do (logical
   replication scenarios). Out of scope for v1; flagged here so
   the shape doesn't accidentally preclude it.

3. **Concurrent readers and a writer with open savepoints.** WAL
   readers snapshot at session open (WAL §Concurrency). A writer
   with open savepoints has a mid-transaction `mx_frame` that
   readers don't see anyway. Confirm during SP3 that no extra
   gate is needed.

4. **`SavepointStackOverflow` value.** Is 32 the right cap, or
   should it be configurable? v1 picks 32 hard-coded; revisit if
   any benchmark or test pattern needs more.
