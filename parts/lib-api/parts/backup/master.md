---
name: lib-api/backup
kind: leaf
shapes: ./shapes.json
inherits:
  - /parts/storage/master.md
  - /parts/storage/parts/backup-engine/master.md
emits:
  rust:   { path: src-rust/lib_api/backup.rs }
  c:      { path: src-c/lib_api/backup.c, headers: [src-c/lib_api/backup.h] }
  zig:    { path: src-zig/lib_api/backup.zig }
  go:     { path: src-go/lib_api/backup.go }
  python: { path: src-python/lib_api/backup.py }
---

# Online backup API: init / step / finish / remaining / pagecount

Surface that mirrors the published `sqlite3_backup_*` family
(sqlite.org/c3ref/backup_finish.html, sqlite.org/backup.html). A
backup is a long-running, incremental copy of pages from a source
database into a destination database, executed under cooperative
locking so the source can continue serving readers (and short
writers, with restart-on-write semantics).

The lib-api surface is a thin wrapper around the storage-side
`/parts/storage/parts/backup-engine` state machine. This part owns
the public lifecycle (`init` → repeated `step` → `finish`) and the
two introspection accessors (`remaining`, `pagecount`).

## Scope (v1)

Admitted:

- `backup_init(dst_db, dst_name, src_db, src_name)` — open a
  backup handle that copies the database named `src_name` (e.g.
  `"main"`, `"temp"`, an attached schema name) within `src_db`
  into the database named `dst_name` within `dst_db`. v1 admits
  `"main"` for both names; other schema names are admitted by the
  shape but resolved by the storage layer (out-of-scope schemas
  yield `BackupInitError::UnknownSchema`).
- `backup_step(handle, n_pages)` — copy up to `n_pages` source
  pages into the destination. `n_pages == -1` (passed as the
  sentinel `STEP_ALL`) means "copy every remaining page in this
  call". Returns `BackupStepResult::Ok` (more pages remain),
  `Done` (every page copied; transaction committed on dst), or
  `Error(condition)`.
- `backup_finish(handle)` — release the handle. If the backup
  completed (last `step` returned `Done`), the destination commit
  has already been written; `finish` only releases locks and
  storage handles. If `finish` runs while the backup is
  incomplete, the destination is left in a well-defined
  rolled-back state (see Pin 6) and any pages already written are
  discarded.
- `backup_remaining(handle)` — pages in the source that have not
  yet been copied in the current pass. Decreases monotonically as
  `step` makes progress within a pass; reset to a fresh
  `pagecount` on a restart (see Pin 4).
- `backup_pagecount(handle)` — total pages in the source as of
  the most recently observed source snapshot. Refreshed at every
  `step` entry that observes a source-write since the prior
  observation (see Pin 4).

Deferred:

- Backup of attached schemas other than `"main"` — admitted
  syntactically but the resolver is a follow-up.
- Encrypted-source backup — out of v1 scope (encryption is
  deferred project-wide).
- Backup with concurrent destination readers (mainline allows
  read-while-backup on dst; v1 holds an exclusive write lock on
  dst for the entire backup).

## Public lifecycle

```
backup_init(dst_db, dst_name, src_db, src_name) -> Result<BackupHandle, BackupInitError>
loop:
    r = backup_step(handle, n_pages)
    if r is Ok      -> continue (more pages remain)
    if r is Done    -> break    (success; dst committed)
    if r is Error   -> break    (failure; dst rolled back)
backup_finish(handle) -> Result<unit, BackupFinishError>
```

The same handle MAY be re-stepped after a transient
`BackupStepResult::Error(condition)` if the condition is a
restart-class error (see Pin 4). Error conditions that originate
in the destination (write I/O failures, full-disk) are terminal:
the next call must be `finish`.

## Algorithm

### `backup_init(dst_db, dst_name, src_db, src_name)`

```
if src_db is dst_db and src_name == dst_name:
    return Err(BackupInitError::SameDatabase)
src_handle = storage_resolve_schema(src_db, src_name)
            # Err(UnknownSchema) if name doesn't resolve
dst_handle = storage_resolve_schema(dst_db, dst_name)
            # Err(UnknownSchema) if name doesn't resolve
engine = backup_engine_open(src_handle, dst_handle)
            # Err(EngineOpen) on lock acquisition failure
return Ok(BackupHandle { engine, dst_db_borrow, src_db_borrow })
```

Holding two database borrows is an abstract obligation; targets
render the two borrows in their idiomatic form (Rust `&Database`,
C handle pair). The handle MUST NOT outlive either borrow.

### `backup_step(handle, n_pages)`

```
to_copy = if n_pages == STEP_ALL:
              backup_engine_remaining(handle.engine)
          else:
              min(n_pages, backup_engine_remaining(handle.engine))

result = backup_engine_step(handle.engine, to_copy)
        # state-machine call; see /parts/storage/parts/backup-engine
return map_engine_result(result)
```

`map_engine_result` translates the storage-side enum into the
public StepResult: engine `Progressed` → `Ok`, engine `Completed`
→ `Done`, engine `RestartRequired` → `Ok` (caller observes
restart via the next `pagecount`/`remaining` read), engine
`Failed(cond)` → `Error(cond)`.

### `backup_finish(handle)`

```
if backup_engine_state(handle.engine) is Completed:
    backup_engine_release(handle.engine)
    return Ok(())
backup_engine_rollback_dst(handle.engine)
backup_engine_release(handle.engine)
return Ok(())
```

`finish` is infallible at the lib-api layer in v1 — every
recoverable failure is reported during `step`. Targets MAY return
the rollback's I/O condition if a target-side I/O error fires
during dst rollback; v1's spec-side return is `Ok(())`.

### `backup_remaining(handle)` and `backup_pagecount(handle)`

```
backup_remaining(handle)  -> backup_engine_remaining(handle.engine)
backup_pagecount(handle)  -> backup_engine_pagecount(handle.engine)
```

Both accessors are O(1) reads of state cached on the engine.

## Correctness pins

**B1. `init` rejects same-database backup.** If the source and
destination handles refer to the same `(database, schema name)`
pair, `init` returns `BackupInitError::SameDatabase`. Mainline
parity (cf. published `sqlite3_backup_init` doc).

**B2. `step(handle, STEP_ALL)` copies every remaining page in
one call.** The sentinel is the language-neutral spelling of
mainline's `nPage = -1`. Targets render the sentinel in their
idiomatic form (Rust constant, C `#define`); the public surface
treats `STEP_ALL` and a sufficiently-large positive `n_pages` as
equivalent (modulo restart, see Pin 4).

**B3. `step` makes monotonic progress in the absence of source
writes.** With no source-side writers, every successful `step`
strictly decreases `remaining`. After enough cumulative `step`
calls, `remaining` reaches 0 and the next `step` returns `Done`.

**B4. Source-write during backup forces restart.** If the source
database is modified between two `step` calls (or during a step,
observed at the next acquisition of the source's shared
read-lock), the engine resets its internal cursor to page 1 and
re-observes `pagecount`. The public surface signals this by:
(a) `pagecount` may increase or decrease at the next read,
(b) `remaining` jumps back up to the new `pagecount`. The next
`step` returns `Ok` (not `Error`); restart is NOT a caller-
visible error condition. Consumers that care about progress
should compare `pagecount - remaining` over time.

**B5. Source takes a SHARED lock per step; concurrent readers
admitted.** Each `step` acquires a shared read-lock on the
source for the duration of the page-copy phase, then releases
it. This admits concurrent readers (and short, non-overlapping
writers from other connections — those writers trigger Pin 4
restart on the next step). The lock is NEVER held across
`step` boundaries; long-running backups do not starve the
source.

**B6. Destination is held under EXCLUSIVE write-lock for the
backup's lifetime.** From `init` to `finish`, the destination
database is exclusively locked. Concurrent destination readers
from other connections are NOT admitted in v1. The lock is
released by `finish`. If `finish` runs while the engine state
is anything other than `Completed`, the destination is rolled
back: any pages already written are discarded by the rollback
(file truncated to the size observed at `init`, or the
destination's pre-init journal / WAL frames are reset). The
caller observes a destination identical to its pre-`init`
state on rollback.

**B7. Destination's page size adapts to the source's.** If the
destination is freshly created (zero-byte file) at `init`, its
page size is set to the source's page size during the first
`step`. If the destination already contains a database with a
DIFFERENT page size, v1 returns
`BackupInitError::PageSizeMismatch` from `init` (mainline
admits an in-flight page-size change via vacuum-style copy; v1
defers that path).

**B8. WAL-mode source reads a consistent snapshot.** When the
source is in WAL mode, every `step` reads pages through the
WAL frame map at the snapshot established at the step's
shared-lock acquisition. A page that exists in a WAL frame is
read from the WAL; a page absent from the WAL is read from the
main file. The snapshot is fixed for the duration of the step;
between steps, a new snapshot is acquired (which can trigger
Pin 4 restart if the snapshot has advanced).

**B9. `finish` is idempotent.** Calling `finish` on an
already-finished handle is a no-op. Calling `finish` after
`step` returned `Done` releases storage handles and locks; a
second `finish` returns `Ok(())` without error. Targets MAY
make double-finish a programmer error (e.g. by consuming the
handle in Rust); the spec admits both renderings.

**B10. `remaining` and `pagecount` are valid before the first
`step`.** Immediately after `init`, `pagecount` is the source's
current page count and `remaining` equals `pagecount`. The
caller may issue these reads as a progress baseline before
issuing any `step`.

**B11. Page 1 is always copied last among the live pages.**
Mainline's online-backup contract requires page 1 (the
database header) to be the last page written, so a destination
observed mid-backup never has a header that asserts a page
count larger than what's on disk. The engine MUST defer page 1
until every other live page has been copied; if a restart
occurs, the deferral resets along with the cursor.

**B12. `n_pages == 0` is admitted as a no-op.** `step(handle,
0)` returns `Ok` without copying any page, without acquiring
any source lock, and without advancing the engine cursor. This
is useful for callers that want to drive `pagecount` /
`remaining` reads on a polling cadence without forcing
progress.

**B13. No invented helpers.** Per §Generation scope. Targets
emit only what `shapes.json` declares plus what this spec
explicitly requires. The five public functions, the
`BackupHandle` record, the three error variants, and the
`STEP_ALL` constant are the entire emitted surface.

## Ambiguities and v1 scope decisions

- **Backup of `:memory:` databases.** Admitted; the engine
  treats an in-memory database as a sequence of pages just like
  a file-backed one. The destination MAY be in-memory; the
  destination MAY be file-backed and the source in-memory.
- **Backup with the source in a transaction.** Admitted; the
  source's write-lock for an in-progress transaction blocks the
  step's shared-lock acquisition. The step waits (or, target's
  choice, returns `BackupStepResult::Error(BUSY)` for non-
  blocking targets); v1's spec admits the blocking form.
- **Cancellation.** v1 has no `backup_cancel`; the caller
  cancels by issuing `finish` while the engine state is not
  `Completed` (Pin 6).
- **Progress callback.** Mainline's `sqlite3_backup_step`
  returns SQLITE_BUSY / SQLITE_LOCKED for transient conditions;
  the lib-api surface routes these through
  `BackupStepResult::Error(condition)` with a recoverable
  classification on the `condition`. The caller decides whether
  to retry.

## Regeneration envelope

- Line budget: ~150-250 lines per target. The lib-api wrapper is
  a thin layer over the engine; most logic lives in
  `/parts/storage/parts/backup-engine`.
- Imports: `Database`, `RuntimeCondition` from `/parts/core` /
  `/parts/storage`; `BackupEngine` and engine fns from
  `/parts/storage/parts/backup-engine`.
- No new VDBE opcodes. No new storage primitives.

## Smoke probe (structural)

1. `init(db, "main", db, "main")` returns
   `Err(SameDatabase)`.
2. `init(dst, "main", src, "main")` on a 100-page src returns
   `Ok(handle)`; `pagecount(handle) == 100`,
   `remaining(handle) == 100`.
3. `step(handle, 10)` returns `Ok`; `remaining(handle) == 90`.
4. Loop `step(handle, STEP_ALL)` once → `Done`;
   `remaining(handle) == 0`.
5. `finish(handle)` returns `Ok(())`; the destination contains
   100 pages structurally equivalent to the source.
6. Modify the source between two `step` calls (open a writer
   on src, INSERT a row, commit) → next `step` returns `Ok`,
   `pagecount` reflects the new page count, `remaining` resets
   to the new `pagecount` (Pin 4 restart).
7. `init` then `finish` with no `step`: destination is
   unchanged from its pre-`init` state (Pin 6 rollback).
