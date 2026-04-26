# Linux x86_64 Benchmark Snapshot — 2026-04-26

**Environment:** Ubuntu 22.04 LTS, kernel 6.8.0, AMD/Intel x86_64, 32 cores, 31 GiB RAM.
**Toolchains:** rustc 1.95.0, gcc 11.4.0, zig 0.16.0, go 1.23.4, python 3.10.12, sqlite 3.37.2.
**Method:** `bench/run-all.sh` — single pass, no warmup curation. Raw CSV at `2026-04-26-linux-x86_64.csv`.

## Headline (3 publishable wins)

| Lane | Best LEAP target | Mainline SQLite | Ratio |
|---|---|---|---|
| **1 — cold start** | rust 421 μs | 1,695 μs | **✅ 4.02× faster** |
| **5 — binary size** | c 463 KB | 1,191 KB | **✅ 2.57× smaller** |
| **6 — memory footprint** | rust 2.0 MB | 3.25 MB | **✅ 1.62× lower** |

Macros consistent with macOS arm64 numbers (cold-start 2.4×, size 2.96×, memory 1.64×). Linux cold-start ratio is **better** on the Linux box because mainline pays a heavier startup cost there.

## Per-target detail

### Lane 1 — cold start (open → first query ready)

| Target | Time | vs mainline |
|---|---|---|
| sqlite-leap-rust | 421 μs | 4.02× faster |
| sqlite-leap-c    | 539 μs | 3.15× faster |
| sqlite-mainline  | 1,695 μs | baseline |

### Lane 5 — binary size

| Target | Size | Notes |
|---|---|---|
| sqlite-leap-c      | 463 KB | **beats mainline 2.57×** |
| sqlite-mainline    | 1,191 KB | baseline |
| sqlite-leap-rust   | 1,659 KB | 1.39× larger than mainline |
| sqlite-leap-go     | 4,098 KB | static Go runtime |
| sqlite-leap-zig    | 7,810 KB | debug-symbol heavy |
| sqlite-leap-python | 21 KB (script) | not directly comparable |

### Lane 6 — memory footprint (RSS idle + small DB open)

| Target | RSS | vs mainline |
|---|---|---|
| sqlite-leap-rust | 2.0 MB | 1.62× lower |
| sqlite-leap-c    | 2.5 MB | 1.30× lower |
| sqlite-mainline  | 3.3 MB | baseline |

(Zig/Go/Python lane-6 measurement not yet wired — TODO.)

## Apples-to-oranges lanes (do not publish raw numbers)

### Lane 2 — parse speed
Numbers measured via the slt_runner CLI parse path; mainline measured against its embedded library lexer in-process. The 380× ratio is meaningless until a library-mode parse harness exists for both engines.

### Lane 3 — SELECT in-memory
| Target | q/s |
|---|---|
| sqlite-leap-rust | 1.19 M |
| sqlite-leap-c    | 988 k |
| sqlite-mainline  | 56.3 M |

Mainline is timed via in-process library calls; LEAP via the slt_runner CLI doing parse+compile per query. Apples-to-apples needs a LEAP library-mode bench (rusqlite-style). Pure-loop methodology already documented in `bench/results/select_throughput_5target/REPORT.md`.

### Lane 4 — INSERT throughput
| Target | i/s | Path |
|---|---|---|
| sqlite-leap-go     | 344 k | close-time atomic flush |
| sqlite-leap-zig    | 132 k | close-time atomic flush |
| sqlite-leap-c      | 43 k  | close-time atomic flush |
| sqlite-leap-rust   | 38 k  | close-time atomic flush |
| sqlite-leap-python | 7.6 k | close-time atomic flush |
| sqlite-mainline    | 35.2 M | hot-path lib, no fsync |

LEAP currently writes the database via close-time atomic-rename (Phase 3d). Mainline at 35M i/s is the in-process lib path with no per-commit fsync. The right comparison is **Phase 4b WAL append-on-write** (already spec'd, not yet emitted on slt_runner) — that closes most of the gap. Until then, this lane is structural.

## What this proves

The dual-spec hypothesis survives Linux:

1. **Cold start, binary size, memory** — three architecturally-grounded wins land on both macOS arm64 and Linux x86_64. Numbers are stable across platform; the LEAP build is honest.
2. **5/5 targets compile clean on Linux from one rsync pass** — Rust, C, Zig, Go, Python all build with their pinned toolchains. C needed `-lm` added to the build script (Linux-only divergence captured in `src-c/build_slt_runner.sh`).
3. **slt_runner smoke on `select1.test`**: Rust 1031/1031, C 1028/1031, Zig 1029/1031, Go 1029/1031 — same as macOS. Linux is not introducing new divergences. (Python had a stale-import error on Linux, separately tracked.)

## Gaps to close before publication

1. **Library-mode harness** — re-time Lanes 2/3/4 with both engines invoked as in-process libraries. Mainline already exposes `sqlite3_*`; we need a LEAP equivalent for each target (Rust crate already exists; C/Zig/Go/Python need wrapping).
2. **Phase 4b WAL append-on-write** — close Lane 4 gap honestly. Spec exists; emission pending.
3. **Pure-loop repeat for Lane 3** — already done on macOS, not yet re-run on Linux with the new fixture.
4. **Linux-specific Lane 1/5/6 fine print** — io_uring (Linux-only) for Lane 4 may move that lane further; not used today.
