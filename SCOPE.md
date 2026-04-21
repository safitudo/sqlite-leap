# Scope-out: Phase 4b WAL-append (2026-04-20)

Phase 4b (WAL append-on-write — task spec in `spec/wal.spec.md` § "Phase 4b")
was attempted this session and **deferred**. The env var `LEAP_WAL_APPEND=1`
is wired end-to-end but the underlying append path is not yet implemented;
the hook is a no-op pass-through that falls back to the existing atomic-
rename slurp commit. Contract: flag unset ⇒ byte-identical to pre-session;
flag set ⇒ one-shot stderr notice + identical behaviour.

## Why deferred

### 1. Lane 4 harness is structurally in-memory

The lane 4 bench (`bench/lanes/04-insert-throughput/run.sh`) invokes the
`sqllogictest` binary with the workload file as its only argument. That
binary opens its session via `db_create()` / `Database::new()`, which is the
**in-memory** backend. The commit path (`atomic_rename_commit` / `db_close`)
is never reached during lane 4. No change to `atomic_rename_commit` — sync,
WAL-append, or otherwise — can move the lane 4 number until the harness is
taught to open a file-backed DB.

Concretely: current 20k/38k ins/s (C/Rust) are pure VDBE + B-tree in-RAM
throughput. They are NOT disk-bound; they are CPU-bound on the insert loop.
Phase 5 async backends landed correctly but cannot affect lane 4 for the
same reason: there is no I/O on the hot path.

**Minimum harness change required** (out of scope for this session; `run.sh`
is fenced off by the task's rules): teach the sqllogictest binary to honour
a `LEAP_DB_PATH` env var (or a `--db` flag) that, when set, opens via
`db_open(path)` instead of the in-memory `db_create()`. Lane 4 can then set
the var to `$tmpdir/db.sqlite` parallel to what mainline and turso do. This
is a ~30-line change across the two harness binaries but it touches the
semantics of every sqllogictest run, so regression clean-up matters.

### 2. Phase 4a multi-frame WAL recovery is a stub

`src-c/storage.c` `wal_read_side_open` and its Rust sibling refuse WAL files
with more than zero frames:

```
    /* Multi-frame WAL: MVP refuses. phase4a.json does not exercise this. */
```

A real Phase 4b WAL-append produces multi-frame WALs at commit time. Any
producer must be matched by a consumer on the open path — otherwise a crash
between commit and checkpoint, or a cooperative reopen within the same
process, surfaces as `STORAGE_WAL_CORRUPT_HEADER`. This is the **prerequisite
Phase 4a did not ship** (its acceptance gate used the zero-frame path + out-
of-band `tests/roundtrip_wal_readside.py` which remains deferred). Phase 4b
cannot land cleanly until the consumer is in place.

**Minimum work to unblock**: implement multi-frame walk per
`spec/wal.spec.md` § "Committed-frame recovery rule" (frame-header walk,
salt check, Fibonacci-checksum chain, page-index overlay, full checkpoint
into main file via existing atomic-rename, unlink WAL). Spec text is
complete and byte-unambiguous; roughly 200–300 LOC per target. Must ship
with a fixture that includes **actual committed frame bytes** (not just the
32-byte empty-WAL header).

### 3. Pager has no page-level dirty tracking

The current storage model keeps the whole DB materialised in RAM (`Vec<u8>`
for the main image, `Vec<Table>` for the catalog) and re-serialises the
entire image on commit. Phase 4b needs to know WHICH pages changed since
the last commit in order to append only those frames. The pager has no
dirty-map today; instead `Database::dirty` is a single bool.

**Minimum work to unblock**: introduce a page-granular dirty-map in the
storage layer (one bit per page, or a `HashSet<page_no>`). Every mutation
path — `insert_row`, `update_row`, `delete_row`, B-tree splits, freelist
grows, schema changes — must mark the pages it touches. This is not deep
but it is broad: every write path on both targets must cooperate, and
cross-build equivalence must be preserved (both targets must mark the same
set of pages given the same mutation sequence).

An acceptable v1 simplification: diff the pre-commit in-memory image
against the post-commit serialised bytes at page granularity. O(DB size)
per commit instead of O(dirty set), but no pager rework. Would still need
a way to hold the pre-commit bytes (i.e., call `serialize_database` once
at the start of the txn and stash it). Feasible for small DBs, degrades
for multi-GB DBs, but it's strictly better than full re-slurp for the
benchmark case.

## Estimated total effort (follow-up session)

| Item                                           | LOC (both targets) | Hours |
|------------------------------------------------|--------------------|-------|
| Phase 4a multi-frame reader + fixture          |              ~500 |   4–6 |
| Page-diff dirty detector (simplification)      |              ~200 |   2–3 |
| WAL frame builder + async-pipelined append     |              ~400 |   4–6 |
| Checkpoint-on-close path                       |              ~150 |     2 |
| `phase4b-wal-append.json` fixture (5 cases)    |             fixture |   2 |
| Harness `LEAP_DB_PATH` env-var support         |              ~60 |     1 |
| Regression + corpus re-run                     |                  - |   2 |
| **Total**                                      |                  - | **17–22** |

This is a dedicated-session-scale effort, not a 1-hour scope-in. The
working norm "An honest 'not this session' is better than half-landed WAL
corruption risk" applies.

## What this session DID land

- `LEAP_WAL_APPEND=1` env-var observation in `atomic_rename_commit` on both
  targets. Notifies once via stderr. Falls through to the existing sync
  path — no behavioural change vs. prior session.
- This scope document.
- Lane 4 numbers with / without the env var (identical, as expected, since
  the harness never reaches the hook).

## Acceptance gate for the follow-up

A future session that claims Phase 4b done MUST show:

1. `phase4b-wal-append.json` passing on both C and Rust (byte-identical WAL
   frame bytes for the same salt seed).
2. `tests/roundtrip_wal_writeside.py` passing (leap writes WAL, mainline
   reads it, and round-trips back).
3. Full smoke corpus (203/203) clean both with and without
   `LEAP_WAL_APPEND=1`.
4. Lane 4 sqllogictest harness taught to open file-backed DBs (via
   `LEAP_DB_PATH` or equivalent) without regressing the existing in-memory
   test path. Corpus pass rate unchanged.
5. Lane 4 insert-throughput result ≥ 100k ins/s with the env var set
   (directly measurable on Darwin kqueue backend; Linux io_uring number
   blocks publication).
