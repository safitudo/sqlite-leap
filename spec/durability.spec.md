# Durability — atomic-rename commit (Phase 3d) — language-neutral spec

Phase 3d adds crash safety to the on-disk backend without departing from Phase 3a's slurp-on-open / flush-on-close simplicity strategy.

## Problem

Phase 3a/3b write the entire database file back on close via a single `write(2)` + `fsync(2)` sequence. If the process (or the machine) crashes partway through that write, the on-disk file is left in a torn state. A subsequent open reads the partially-updated bytes as if they were a complete database. Outcomes range from `STORAGE_CORRUPT_HEADER` (if the header was not fully rewritten) to silent data inconsistency (if the header made it but some middle page didn't).

## Design: atomic-rename commit

On POSIX filesystems, `rename(2)` between paths on the same filesystem is atomic with respect to concurrent readers: either the new file is visible under the destination name, or the old one is, never a mixture. We exploit this for durable commits.

### Commit protocol (on `close_database(handle)`, on-disk backend, dirty)

1. Let `<path>` be the database path (as passed to `open_database`).
2. Let `<staging>` = `<path> + ".leap-stage"` in the same directory. (Same filesystem is guaranteed because it's the same directory.)
3. If `<staging>` already exists at this point, unlink it first — it is leftover from an earlier process that crashed between step 7 and step 8.
4. Open `<staging>` for write (create + truncate). If open fails, raise `STORAGE_FILE_IO` with `operation="open"`, `path=<staging>`. Do NOT alter `<path>`.
5. Write the full serialised database bytes to `<staging>`. On short-write / I/O error: close `<staging>`, unlink it, raise `STORAGE_FILE_IO` with `operation="write"`, `path=<staging>`.
6. `fsync(<staging>)`. On failure: close, unlink, raise `STORAGE_FILE_IO` with `operation="sync"`, `path=<staging>`.
7. Close `<staging>` (file descriptor only — file remains on disk).
8. `rename(<staging>, <path>)`. On failure: unlink `<staging>` if still present, raise `STORAGE_FILE_IO` with `operation="write"`, `path=<path>`. This is the **commit point**. After this call completes successfully, `<path>` observers see the new bytes; the change is durable modulo the parent-dir fsync below.
9. `fsync(parent-directory-of-<path>)`. On failure: raise `STORAGE_FILE_IO` with `operation="sync"`, `path=<parent-dir>`. (Some filesystems — ext4 without `dirsync` — require this extra fsync for the rename itself to survive a crash.) This step is target-defined in detail: on macOS HFS+/APFS, this is often a no-op; on ext4 it is load-bearing.
10. Release the in-memory handle.

Steps 4–9 together are "the commit". A crash between any two steps leaves the system in a safely-recoverable state:

| Crash between … | State of `<path>` | State of `<staging>` | Next open recovers by … |
|---|---|---|---|
| steps 4–5 | unchanged (old bytes) | partial or empty | unlinking `<staging>` (step 3 of next open protocol). Committed state: old. |
| steps 5–6 | unchanged | fully written, not fsynced (may be dropped by fs) | unlinking `<staging>`. Committed state: old. |
| steps 6–8 | unchanged | fully written + synced | unlinking `<staging>` (new bytes discarded). Committed state: old. |
| steps 8–9 | new bytes (rename applied but possibly not durable) | does not exist | reading `<path>` — sees new bytes if rename survived, else old. Committed state: new OR old (filesystem-dependent). |
| after 9 | new bytes | does not exist | reading `<path>`. Committed state: new. |

In every row, the next open yields a valid database (either fully-old or fully-new), never a torn mixture.

### Open protocol (on `open_database(path)`)

1. If `<path>.leap-stage` exists, unlink it. It is staging leftover from a crashed prior process; its bytes are not committed. No error is raised for this cleanup.
2. Proceed with Phase 3a's normal open protocol (read `<path>` into RAM, validate header, etc.). If `<path>` does not exist, Phase 3a's create protocol runs (zero-fill a 4096-byte page, write header + empty sqlite_schema page).

### Non-dirty close

If the session performed no mutations (no CREATE / INSERT / UPDATE / DELETE), close MAY skip the entire atomic-rename protocol and simply release the handle. Implementations MAY still perform the atomic-rename — it's a performance optimisation, not a correctness requirement.

## What this spec does NOT provide

- **Transactional semantics** within a session. Phase 3d's unit of durability is a full database session (open → mutations → close). There is no BEGIN / COMMIT / ROLLBACK; a VDBE program that half-runs has no effect on disk because we only flush on close.
- **Concurrent writers**. Two processes opening the same `<path>` simultaneously and both mutating will race on step 8 (last-writer-wins) and may both unlink each other's staging files. Phase 3d is single-writer only. Mainline SQLite's file-lock protocol moves this to Phase 4 (WAL or rollback-journal).
- **Incremental durability**. A long session's mid-flight mutations are all lost on crash. Phase 4 (WAL) adds intra-session durability at checkpoint boundaries.
- **Mainline-SQLite journal compatibility**. Mainline uses `<path>-journal` for rollback-journal semantics or `<path>-wal` / `<path>-shm` for WAL mode. The `.leap-stage` suffix is intentionally DIFFERENT so that a mid-close crash does NOT leave a file that mainline would interpret as a rollback journal to replay. Phase 4 revisits this for cross-engine compatibility.

## Test authority

`tests/cross-build/phase3d.json` (Phase 3d test fixture) exercises:

- Normal commit: mutate, close, reopen, verify bytes match.
- Staging leftover cleanup: prewrite a `.leap-stage` file, open, verify it is unlinked and `<path>` is read normally.
- Repeat commit: multiple open/mutate/close cycles with the same path.

The fixture reuses the Phase 3a disk-backend harness conventions (backend="disk", preload_hex, reopen markers) with one extension: a `preload_staging_hex` field that writes bytes to `<path>.leap-stage` before the first open. See `phase3d-harness.md`.
