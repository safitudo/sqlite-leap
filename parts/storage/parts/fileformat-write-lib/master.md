---
name: fileformat-write-lib
kind: inner
emits:
  rust:   { path: src-rust/storage_fileformat.rs }
  go:     { path: src-go/storage/fileformat.go }
  c:      { path: src-c/storage/fileformat_lib.c }
  zig:    { path: src-zig/storage_fileformat.zig }
  python: { path: src-python/leap_sqlite/storage_fileformat.py }
---

# File-format write — library API (close-time atomic flush)

Lifts the proven multi-page b-tree write path from the
`fileformat_deep_split_runner` probe (memory:
`project_4target_multipage_split_2026_04_25.md` — 5/5 targets
byte-identical at 5000 rows on the deep-split path; mainline
`PRAGMA integrity_check ok`) into the `leap_sqlite::storage_fileformat`
library so the sqllogictest runner — and any future callers — can open
and flush an on-disk SQLite-format-3 database.

This is **not** Phase 4b WAL (per-commit fsync). It is the close-time
atomic-flush durability model spec'd in `spec/durability.spec.md`:
serialize the entire `Database` to `<path>.leap-stage`, fsync, atomic
rename onto `<path>`. A long session's mid-flight mutations are still
all-or-nothing across an open/close cycle. Phase 4b is a follow-up.

## Public API (Rust signatures, language-neutral semantics)

```
open_database_at(path: string)
    -> Database | RuntimeCondition
close_database_at(db: Database, path: string)
    -> ok | RuntimeCondition
serialize_database_to(db: Database, path: string)
    -> ok | RuntimeCondition
deserialize_database_from(path: string)
    -> Database | RuntimeCondition
```

`open_database_at`:
1. Unlink any leftover `<path>.leap-stage` (open protocol step 1 of
   durability.spec.md).
2. If `<path>` does not exist or is empty, return an empty `Database`
   (with an in-memory `Pager`, since no on-disk file exists yet).
3. Otherwise validate the SQLite-format-3 magic + 100-byte header,
   read `sqlite_master` from page 1, descend each table's b-tree, and
   construct an in-memory `Database` with one `MemTable` per row.
4. Pin 18.1d — Pager attachment. After the in-memory `Database` is
   constructed (steps 2 or 3), if `<path>` exists on disk, attach a
   file-backed `Pager` to the `Database` by calling
   `pager_new_file_backed(path)` and stamping the result onto
   `Database.pager`. This wires the WAL bridge: subsequent
   `pager_commit_transaction` calls on this `Database` will fsync
   committed frames to `<path>-wal` per `parts/storage/parts/wal-bridge`.
   Before stamping, the implementation MAY perform Phase A.3 crash
   recovery (replay any committed WAL frames into the in-memory page
   image) so that `deserialize_database_from_bytes` sees the
   post-recovery view; this is independent of the Pager attachment.

`close_database_at` / `serialize_database_to`:
1. Lay out one b-tree per user table starting at page 2. Pack rows
   ascending by rowid into table-leaf pages (page_type 0x0D); when a
   single leaf cannot hold the next cell, finalise it and start a new
   one. When more than one leaf exists at a level, build interior
   pages (page_type 0x05) bottom-up: greedy pack of `InteriorCell {
   child, key }` pairs with the rightmost subtree placed in the
   page-header `right_child` field. Iterate until exactly one root
   page remains for the table.
2. Build `sqlite_master` on page 1 with one row per user table:
   `(type='table', name, tbl_name=name, rootpage, sql)`. Synthesize
   `sql` as `CREATE TABLE name(c1,c2,...)` from `MemTable.column_names`
   when the original DDL is not retained by the catalog.
3. Write the 100-byte database header at offset 0:
   `page_size`, `change_counter=1`, `database_size`, `text_encoding=1`
   (UTF-8), `version_valid_for=change_counter`,
   `sqlite_version=3_007_000`. Reserved bytes 32–95 (minus the
   load-bearing fields above) are zero.
4. Atomic-rename commit per durability.spec.md §"Commit protocol":
   write to `<staging> = <path>.leap-stage`, `fsync(staging)`,
   `rename(staging, <path>)`, best-effort `fsync(parent_dir)`.

## Constants used by the v1 layout

- `PAGE_SIZE = 4096`
- `RESERVED  = 0`
- `USABLE    = PAGE_SIZE - RESERVED`
- `PAGE_TYPE_TABLE_LEAF     = 0x0D`
- `PAGE_TYPE_TABLE_INTERIOR = 0x05`

## Spec compatibility — carried over from `fileformat-write`

The cell encoder, page-header layout, varint codec, serial-type
encoding, and InteriorCell shape are all the same byte protocol as
the existing `fileformat-write` leaf. This leaf does NOT redeclare
them; it lifts the same encoder routines into a callable library
form. Any future regen pass that touches encoder bytes MUST keep both
leaves in sync — preferred: hoist the byte-level encoder shapes into
`parts/storage/parts/file-format/` and have both leaves import them.

## Out of scope (v1)

- Overflow pages for cells larger than ~4040 bytes. If a single row's
  encoded cell exceeds usable-space, the current implementation still
  emits one cell per page but does not honour mainline's overflow-page
  protocol. Surfaced as **SPEC GAP overflow** for follow-up.
- WAL `<path>-wal` sidecar. `LEAP_WAL_APPEND=1` is acknowledged on
  stderr but the close still goes via the atomic-rename path.
- Indexes (`page_type 0x02 / 0x0A`). User-defined indexes are deferred
  to a follow-up; sqlite_master does not currently emit `type='index'`
  rows even when a CREATE INDEX has been issued.
- Original `CREATE TABLE` DDL preservation. The catalog does not retain
  source SQL; we synthesise a minimal `CREATE TABLE name(c1,c2,...)`
  that mainline parses cleanly enough for `PRAGMA integrity_check`.

## Test authority

End-to-end validation lives at the runner level for v1:

- Tiny: 3-row INSERT → `sqlite3 <path> "SELECT count(*) FROM t"` → 3,
  `PRAGMA integrity_check` → `ok`.
- Lane 4: 100 000-row INSERT (workload at
  `bench/lanes/04-insert-throughput/workload.slt`) → count=100000,
  `PRAGMA integrity_check` → `ok`, sample SELECTs round-trip
  payload bytes.

Both validated 2026-04-26 on Rust target. Go landed 2026-04-26 from
the same algorithm: 100k-row workload writes a mainline-readable file
in ~0.3s (333k inserts/s), `PRAGMA integrity_check ok`, payload bytes
round-trip on `SELECT id, payload FROM t LIMIT 3`. C landed 2026-04-26
as `src-c/storage/fileformat_lib.c`: 100k-row Lane-4 workload writes
in ~1.36s (73,736 inserts/s), `xxd` shows `SQLite format 3\0` magic,
`SELECT count(*) FROM t` returns 100000, `PRAGMA integrity_check`
returns `ok`. Zig / Python ports are deferred to a multi-target
promotion pass; the API surface above is target-agnostic, so each
generator can lift the same algorithm.

## Regen-debt note

The current emission lives in `src-rust/storage_fileformat.rs`. It is
marked `// leaplint: target-local lift (pending spec promotion
2026-04-26)`. When the multi-target promotion pass runs, this leaf
should grow `emits:` slots for python / c / zig / go and the agents
should regenerate from this master. The existing
`fileformat_deep_split_runner` probe stays in place as the runner-level
proof-of-correctness fixture.
