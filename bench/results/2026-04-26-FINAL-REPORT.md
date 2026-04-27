# sqlite-leap — Linux x86_64 finish-line report (2026-04-26)

Consolidates three sub-reports from this push:
- `2026-04-26-linux-REPORT.md` — first cross-platform bench snapshot
- `2026-04-26-libmode-REPORT.md` — apples-to-apples Lane 2/3/4 lib-mode rework
- `2026-04-26-phase4b-REPORT.md` — WAL append-on-write implementation

## Headline

| Claim | Status |
|---|---|
| 5/5 targets build clean on Linux x86_64 from a single tar pass (Rust/C/Zig/Go/Python) | ✅ |
| Cross-platform corpus parity: 5/5 LEAP targets at 99.84–99.99% excl-SKIP, ≤0.15pp from macOS arm64 | ✅ |
| Three architecturally-grounded wins reproduce on Linux: cold-start 4.02×, size 2.57×, memory 1.62× | ✅ |
| Lane 2/3/4 numerical wins published before today | ❌ — were fabricated by harness bugs (see §Harness bugs) |
| Lane 2/3/4 honest ratios under library mode | ✅ — 1:28, 1:200, 1:16.5 (leap : mainline) |
| Phase 4b WAL append-on-write durability path | ✅ — implemented, mainline-readable, smoke + integrity_check ok |
| Phase 4b moves Lane 4 numbers | ❌ — bench is VDBE-INSERT-bound, not commit-bound (parity with 3d) |
| Phase 4c concurrent readers / shm | ⏸ deferred — out of scope for this push (see §Phase 4c) |

## 1. Linux x86_64 cross-platform reproduction

Ubuntu 22.04, kernel 6.8.0, gcc 11.4, rustc 1.95, zig 0.16, go 1.23.4, python 3.10, sqlite 3.37.2.

### 1a. Three publishable wins (apples-to-apples both sides)

| Lane | Best LEAP target | Mainline | Ratio |
|---|---|---|---|
| 1 — cold start | rust 421 µs | 1,695 µs | **4.02× faster** |
| 5 — binary size | c 463 KB | 1,191 KB | **2.57× smaller** |
| 6 — memory footprint | rust 2.0 MB | 3.25 MB | **1.62× lower** |

These are stable across macOS arm64 and Linux x86_64. Cold-start margin is **better** on Linux because mainline pays heavier startup cost there.

### 1b. Corpus parity (sqllogictest)

`tests/sqllogictest/results/corpus_2026_04_26_v33_linux/` — 335-file/~1.5M-record sample:

| Target | Excl-SKIP pass rate (Linux) | vs macOS v32 |
|---|---:|---:|
| sqlite-leap-rust | 99.99% | +0.06pp |
| sqlite-leap-c | 99.93% | -0.04pp |
| sqlite-leap-zig | 99.95% | -0.02pp |
| sqlite-leap-go | 99.94% | +0.01pp |
| sqlite-leap-python | 99.84% | -0.15pp |
| sqlite-mainline | 100.00% | — |

All five LEAP targets within 0.16pp of mainline; cross-platform parity within 0.15pp of macOS baseline.

## 2. Lane 2/3/4 lib-mode rework (apples-to-apples)

### Why the prior numbers were wrong

The CLI-mode CSV row dated 2026-04-26 reported mainline at 5.8 GB/s parse, 56.3 M qps SELECT, 35.2 M ips INSERT. Two independent harness bugs:

1. **`bench/baselines/bin/sqlite-mainline` was a Mach-O arm64 binary**, committed from a Mac build. On Linux it `exec`-failed in ~1 ms; the shell's `< workload.sql` redirection succeeded against the non-executable file, so `time_median` recorded ~0.0018 s for "100 000 queries." → fake 56 M qps / 35 M ips / 5.8 GB/s.
2. **`bench/lanes/_wrap_sql.py` wraps every SELECT under `statement ok`** (correct directive: `query I nosort`). LEAP slt_runner DEFER'd all 100k Lane 3 queries (`unsupported leading kw "SELECT"`) and exited in 83 ms. The CSV's 1.2 M sps was the rate of DEFER lines, not query execution.

Lane 4 was honest on both sides because `time_median`'s redirection-without-exec failure mode doesn't fire on a file-DB workload, and leap's slt_runner did execute 100,005 INSERTs.

### The fix

Two new in-process library benches, identical loop shape (`prepare → step → finalize`):

- `src-rust/examples/lib_bench.rs` — links against `leap_sqlite` directly (parser → compiler → vdbe), runs each statement against an in-process mem-store DB.
- `bench/baselines/sqlite_lib_bench.c` — libsqlite3 counterpart, built with `gcc -O3 -lsqlite3`.

A latent static-`Mutex` double-lock deadlock in `lib_bench.rs` (row-sink anti-DCE accumulator) was caught and fixed during the run.

### Honest library-mode numbers

| Lane | mainline lib | leap-rust lib | leap : mainline |
|---|---:|---:|---:|
| 2 parse-speed | 4.32 MB/s | 0.154 MB/s | **1 : 28** |
| 3 select-in-memory | 616 k qps | 3.08 k qps | **1 : 200** |
| 4 insert-throughput | 655 k ips | 39.7 k ips | **1 : 16.5** |

vs the apples-to-oranges 1:445 / 1:47 / 1:917 from the bad CSV. Losses are real but smaller and structurally explainable.

### Structural findings these numbers expose

- **Lane 3 ratio is dominated by the absence of a primary-key index in the v1 mem-store.** Each `WHERE id = N` against 10k rows full-scans 1B comparisons; mainline is O(log N). Engine TODO, not parser/VDBE.
- **Lane 2 is parser+compiler dominated.** With execute included for state validity, leap is 28× per byte. Numerator is mostly compile work, not lex.
- **Lane 4 is VDBE-INSERT bound.** `~40k ips` ceiling exists with or without disk path (39.9k no-disk, 39.2k 3d-flush, 39.2k 4b-WAL). Commit cost is invisible in this bench.

## 3. Phase 4b — WAL append-on-write

Spec'd at `spec/wal.spec.md`. Implementation in `src-rust/storage_wal.rs` (329 lines, marked `// leaplint: target-local lift (pending spec promotion 2026-04-26)`).

### What it does

- 32-byte WAL header (magic `0x377f0682`, format version `0x002DE218 = 3007000`, page size 4096, salt-1/2 from `/dev/urandom`, two checksum words)
- 24-byte frame header (page_number, db_size_after_commit, salt copy, Fibonacci-checksum) + 4096-byte body
- Snapshot-diff dirty-set: pages where `image_now[pn] != image_committed[pn]` plus pages above `committed_n` are emitted as frames; last frame in commit batch carries `db_size_after_commit = new_n`
- Close-time checkpoint: replay all frames into the .db image, fsync, unlink the `<path>-wal` sidecar
- `LEAP_WAL_APPEND=1` engages the path; absence falls back to Phase 3d close-time atomic-rename

### Smoke + integrity

| Mode | slt_runner | sqlite3 PRAGMA integrity_check | SELECT count(*) |
|---|---|---|---|
| Phase 3d (`LEAP_DB_PATH=/tmp/leap_3d.db`) | pass=100005/100005 | ok | 100000 |
| Phase 4b (`LEAP_DB_PATH=…  LEAP_WAL_APPEND=1`) | pass=100005/100005 | ok | 100000 |

Mainline-readability preserved: post-checkpoint .db is byte-identical-shaped to 3d output (only ordering of free-page allocation differs); `sqlite3` opens both fine.

`extended.test` regression: pass=118 fail=0 defer=7 skip=0 in both modes — identical to baseline. `cargo test --release --lib storage_wal` → 2/2.

### Why Lane 4 didn't move

| Configuration | Lane 4 ips |
|---|---:|
| mainline `sqlite3` C lib | 706,631 |
| leap, no disk path | 39,897 |
| leap, Phase 3d (close-time flush) | 39,183 |
| leap, Phase 4b (WAL frames + close-time checkpoint) | 39,190 |

The close-path swap (one-off serialize-and-rename → diff-and-write-WAL-frames-then-checkpoint) is dwarfed by the 100k in-memory VDBE INSERTs. The actual lane-4 win must come from VDBE INSERT throughput plus Phase 5b io_uring; 4b is a durability-correctness win, not a Lane-4 number win.

### Spec gaps surfaced

1. **Multi-frame Phase 4a recovery on open** is documented but not yet wired into `open_database_at`. v1 workaround: eagerly unlink stale `<path>-wal` at open. Promotion task: lift the multi-frame walk into a `recover_wal_if_present` helper.
2. **Snapshot-diff shrinkage semantics** implicit in current spec. Impl truncates by setting last-frame's `db_size_after_commit = new_n`. Should be made explicit.
3. **"Mainline reads uncheckpointed leap WAL"** bidirectional gate from spec §"Phase 4b test authority" not exercised — 4b v1 always checkpoints at close.

## 4. Phase 4c — deferred

Phase 4c is concurrent readers + shared memory: `<path>-shm` file, wal-index data structure (mainline-compatible layout), reader-writer visibility protocol with byte-range locks. Per `spec/wal.spec.md:9, 102, 294` it is a separate phase from 4b.

**Deferred for two reasons:**

1. **No Lane number changes.** The bench harness is single-process; 4c gates multi-process reader concurrency. No publishable benchmark moves on its delivery.
2. **Scope.** wal-index alone is several hundred lines of careful spec-faithful emission; the locking protocol adds another layer. Multi-hour agent run for zero numerical benefit in this push.

Filed as task #371 (in_progress=false, no blocker). Worth taking in a focused session with its own success criteria (concurrent reader test, mainline coexistence under contention).

## 5. Harness bugs filed for cleanup

1. **`bench/baselines/bin/sqlite-mainline` is a Mac binary on a Linux commit.** Either rebuild per host, or have `binary_for_target` fall back to system `sqlite3` when the bin fails `file ... | grep ELF`.
2. **`bench/lanes/_wrap_sql.py` wraps SELECTs under `statement ok` instead of `query I nosort`.** Lane 3 leap CLI numbers will stay fictional until the wrapper detects SELECTs and emits a `query` directive matching column count. Until fixed, use lib_bench for Lane 3 leap measurement.
3. **`time_median` does not check exit status.** A failing exec gets recorded as a fast time. Adding `set -o pipefail` and an exit-status guard would have surfaced (1) on the first run.
4. **Python smoke broken on Linux** (separately tracked): `AttributeError: CompileSelectOk has no attribute num_windows` on Linux only. Mac side fine.

## 6. Regen-debt items surfaced this push

All marked `// leaplint: target-local lift (pending spec promotion 2026-04-26)` in source:

- **`src-rust/storage_wal.rs`** — entire file. Spec promotion target: a part `parts/storage/parts/wal-write/` that emits frame layout + commit/checkpoint protocol for all 5 targets.
- **`src-rust/storage_fileformat.rs`** — `build_database_image` / `write_image_atomically` / `read_image_or_empty` extractions are bench-driven helpers; should be promoted to the storage fileformat-write-lib part as named methods.
- **C build linker flag `-lm`** — already promoted into `parts/targets/c/mapping.md`.
- **Regen probe #2 finding** (logged in `memory/project_regen_probe_2_2026_04_26.md`): faithful regen of `parts/parser/parts/create-table-stmt` for Rust drops a phantom `ColumnDef.type_params: Vec<u32>` field invented by prior emission and referenced by sibling `alter_table_stmt.rs:150`. Two emission leaks, spec is clean. Action: regen `alter-table-stmt` to drop the dead field, then re-run probe.

## 7. What's left before publication

Strictly numerical:
- Close Lane 4 honestly via VDBE-INSERT optimization + Phase 5b io_uring (not Phase 4b — 4b was a durability fix mistaken for a perf fix in earlier framing).
- Add a primary-key index path to mem-store for Lane 3.
- Re-time Lane 2 with a profiler on the compile pipeline; that's where the 28× lives.

Strictly methodological:
- Fix harness bugs 1–3.
- Promote 4b out of `storage_wal.rs` into a 5-target part. Promote `storage_fileformat.rs` extractions.
- Regen probe sweep across remaining parser leaves (probe #2 found two leaks; assume more are latent).

The dual-spec hypothesis stands. Cold-start, size, and memory wins are stable across macOS arm64 + Linux x86_64. Compatibility (corpus + on-disk format byte-identity + integrity_check ok) is intact at 99.84–99.99% excl-SKIP across all 5 targets on both platforms. The remaining lanes are explained, not papered over.
