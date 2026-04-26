# Phase 4b WAL append-on-write — Rust target-local lift (2026-04-26)

## Code locations

| File | Lines | Purpose |
|------|------:|---------|
| `src-rust/storage_wal.rs` (NEW) | 329 | Phase 4b WAL writer: header + frame builders, Fibonacci checksum, `open_with_wal` / `commit` / `checkpoint_and_close`. Marked `// leaplint: target-local lift (pending spec promotion 2026-04-26)`. |
| `src-rust/storage_fileformat.rs` | +71 | Refactor: extracted `build_database_image(db) -> Vec<u8>` (reused by snapshot-diff), added `write_image_atomically` and `read_image_or_empty`, exported `FILEFORMAT_PAGE_SIZE`. |
| `src-rust/lib.rs` | +1 | `pub mod storage_wal;` |
| `src-rust/examples/slt_runner.rs` | ~30 | Engages `open_with_wal` + `checkpoint_and_close` when `LEAP_WAL_APPEND=1`; falls back to Phase 3d otherwise. The pre-existing "degrading to Phase 3d" stderr stub was removed. |
| `src-rust/examples/lib_bench.rs` | ~30 | Same plumbing, plus close-time commit is now inside the `--time-setup` measurement window (parallel to mainline's `COMMIT`). |

Frame format implemented per spec/wal.spec.md §"Phase 4b": 32-byte header (magic `0x377f0682`, format version `0x002DE218 = 3007000`, page size 4096, checkpoint seq, salt-1/2, two checksum words), 24-byte frame header (page_number, db_size_after_commit, salt copy, checksum), 4096-byte body. Salt source: `/dev/urandom`, with `LEAP_WAL_SALT_OVERRIDE` honoured for fixtures. Checksum: little-endian Fibonacci chain (`s0 += a + s1; s1 += b + s0`) over 8-byte chunks, seeded from the header's chained state.

## Smoke results

Both modes on `bench/lanes/04-insert-throughput/workload.slt` (100k INSERT BEGIN/COMMIT):

| Mode | slt_runner verdict | sqlite3 PRAGMA integrity_check | SELECT count(*) FROM t |
|------|-------------------|-------------------------------|-----------------------|
| `LEAP_DB_PATH=/tmp/leap_3d.db` (no WAL) | `pass=100005 fail=0 defer=0 skip=0 total=100005` | `ok` | `100000` |
| `LEAP_DB_PATH=/tmp/leap_wal.db LEAP_WAL_APPEND=1` | `pass=100005 fail=0 defer=0 skip=0 total=100005` | `ok` | `100000` |

WAL sidecar verification (post close):
- 3d mode: only `/tmp/leap_3d.db` present.
- WAL mode: only `/tmp/leap_wal.db` present (4,415,488 bytes); `-wal` was checkpointed and unlinked at close per spec §"Checkpoint protocol" step 4.

Regression: extended.test in both modes returns `pass=118 fail=0 defer=7 skip=0 total=125` — identical to baseline.

Unit tests: `cargo test --release --lib storage_wal` → 2/2 passed.

## Lane 4 numbers (lib_bench, in-process, --time-setup)

| Configuration | elapsed (s) | qps (ips) | Ratio vs mainline |
|---|---:|---:|---:|
| mainline `sqlite3` C lib (`bench/baselines/bin/sqlite_lib_bench`) | 0.142 | 706,631 | 1.0× |
| leap, no disk path | 2.507 | 39,897 | 17.7× slower |
| leap, `LEAP_DB_PATH` (Phase 3d close-time-flush) | 2.552 | 39,183 | 18.0× slower |
| leap, `LEAP_DB_PATH` + `LEAP_WAL_APPEND=1` (Phase 4b) | 2.552 | 39,190 | 18.0× slower |

**Phase 4b parity with Phase 3d at lane 4.** The close-path swap (one-off serialize-and-rename → diff-and-write-WAL-frames-then-checkpoint) is dwarfed by the 100k in-memory VDBE INSERTs (~40k ips bottleneck — same shape as the previous 39.7k baseline). The bench is INSERT-bound, not commit-bound; eliminating O(db_size) close-time work is correct but not yet the headline win the spec's 4b note hinted at. The actual lane-4 win must come from VDBE INSERT throughput plus Phase 5b io_uring.

Mainline-readability of the produced file is preserved (integrity ok, 100k rows visible), so the Phase 4b code path is durability-equivalent and not a regression on the lanes 1/5/6 trio.

## Spec gaps surfaced

1. **Multi-frame Phase 4a recovery on open (read-side)**: spec §"Committed-frame recovery — multi-frame implementation" is documented but not yet wired into `open_database_at`. The Phase 4b implementation works around this by (v1) eagerly unlinking any stale `<path>-wal` at open and starting fresh, on the assumption that every Phase 4b session ends with a clean checkpoint. This is sufficient for Lane 4 (no crash recovery in the bench loop) but not yet a full §"Open protocol" implementation. Promotion task: lift the multi-frame walk into `storage_fileformat::open_database_at` as a `recover_wal_if_present` helper.
2. **Snapshot-diff page count vs growth pages**: the spec mandates that "every new page numbered above the committed image's page count" is automatically dirty. The Rust impl handles this correctly (`pn > old_n -> dirty`), but the spec wording could be sharpened: it does not state what happens on shrinkage (when `new_n < old_n`). Current impl: pages above `new_n` are simply not emitted, and the last-frame's `db_size_after_commit = new_n` causes the recovery walk to truncate the in-memory image. This works but should be explicit in the spec.
3. **Mainline-readable WAL sidecar pre-checkpoint**: the brief asked whether mainline could open `<path>` while `<path>-wal` is uncheckpointed. Phase 4b v1 always checkpoints at close, so the verification reduced to "the post-checkpoint .db is mainline-readable" (verified). A separate "leave WAL uncheckpointed and let mainline read it" test is the Phase 4a write-side bidirectional gate from spec §"Phase 4b test authority" item 2. Not exercised in this task.

## Target-local-fix items needing later spec promotion

All are marked in source with `// leaplint: target-local lift (pending spec promotion 2026-04-26)`:

- `src-rust/storage_wal.rs` — entire file. Once spec promotion produces a part `parts/storage/parts/wal-write/`, this should be regenerated from shapes (frame layout) + master.md (commit/checkpoint protocol) for all 5 targets.
- `src-rust/storage_fileformat.rs` — the `build_database_image` / `write_image_atomically` / `read_image_or_empty` extractions are bench-driven helpers that should be promoted to the storage fileformat-write-lib part as named methods.
- `src-rust/examples/slt_runner.rs` and `lib_bench.rs` — runner-level WAL-mode plumbing. Marked `leaplint: runner` already; survives community regen because runners are out-of-scope for spec emission.

## Validation transcript (Linux x86_64, ssh -p 22322)

```
$ cargo build --release --example slt_runner --example lib_bench
    Finished `release` profile [optimized] target(s) in 3.49s
$ cargo test --release --lib storage_wal
test result: ok. 2 passed; 0 failed
$ LEAP_DB_PATH=/tmp/leap_3d.db slt_runner workload.slt | tail -1
SUMMARY target=rust pass=100005 fail=0 defer=0 skip=0 total=100005
$ sqlite3 /tmp/leap_3d.db "PRAGMA integrity_check; SELECT count(*) FROM t;"
ok
100000
$ LEAP_DB_PATH=/tmp/leap_wal.db LEAP_WAL_APPEND=1 slt_runner workload.slt | tail -1
SUMMARY target=rust pass=100005 fail=0 defer=0 skip=0 total=100005
$ sqlite3 /tmp/leap_wal.db "PRAGMA integrity_check; SELECT count(*) FROM t;"
ok
100000
$ LEAP_DB_PATH=/tmp/lane4_wal.db LEAP_WAL_APPEND=1 lib_bench workload.sql --time-setup
elapsed_seconds=2.551771 statements=100005 errors=0 qps=39190
```
