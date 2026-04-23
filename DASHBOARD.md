# sqlite-leap — Status Dashboard

**Date:** 2026-04-21 (macOS arm64 / Linux x86_64 via Docker)
**Scope:** honest status of the LEAP claims. All numbers reproducible from artifacts in this repo.

## The claim in one line

> One language-neutral spec → two engines (C + Rust) → byte-identical output on hand-authored smoke tests, 108/108 bidirectional file-format compatibility with mainline SQLite, and **98.87%** / **92.60%** (Rust / C) end-to-end file-level pass on the full 622-file upstream sqllogictest corpus.

Turso has one Rust implementation. sqlite-leap has two implementations from one spec. That asymmetry is the stunt.

## Headline numbers

### Cross-build equivalence (the central LEAP claim)

| Proof | Result | Evidence |
|---|---|---|
| Smoke suite byte-identical C ↔ Rust | **203/203** | `tests/sqllogictest/smoke/` |
| Upstream corpus — Rust (622 files) | **615/622 (98.87%)** pass, **0 panics**, 2 timeouts, 5 FAIL | `tests/sqllogictest/results/2026-04-21-rust-full-v4.log` + diff `-v4-diff.md` |
| Upstream corpus — C (622 files, file-level) | **576/622 (92.60%)** pass, **0 panics**, 33 timeouts, 13 FAIL, 0 regressions from v3 | `tests/sqllogictest/results/2026-04-21-c-full-v4.log` + diff `-v4-diff.md` |

### Bidirectional file-format compat with mainline SQLite

| Matrix | Result | Evidence |
|---|---|---|
| 3 producers × 3 readers × 3 schemas × 4 rowcounts | **108/108 pass (100%)** | `tests/roundtrip/results/2026-04-20-matrix.md` |
| Load-bearing (mainline ↔ leap, both directions) | **48/48** | same |
| Peak validated index-tree depth | 2 (50 000-row indexed table, `PRAGMA integrity_check = ok` via mainline reader) | `serialise_populated_index_leaf` + `walk_index_tree` path in src-c and src-rust |
| Fuzz-grade deterministic roundtrip | **900/900 byte-equivalent**, 100 workloads × 3×3 producer/reader matrix, zero divergences, zero crashes | `tests/fuzz/results/2026-04-21-file-format.md` |

### Fuzz-resistance

| Target | Inputs | Crashes | Notes |
|---|---:|---:|---|
| `fuzz-parse` leap-c    | 449 217 |  0* | *one spurious SIGKILL, non-reproducible |
| `fuzz-parse` leap-rust | 441 214 |  0  | clean |
| `fuzz-exec`  leap-c    | 444 459 |  0  | clean |
| `fuzz-exec`  leap-rust | 248 473 | **100** | 2 bug classes (name-resolution panics on unresolved identifiers + GROUP BY on unresolved col). Open finding — spec-level, Rust path should surface `ENGINE_ERROR` instead of `unwrap()`. Concrete reproducers saved. |

Full campaign writeup: `tests/fuzz/results/2026-04-21-README.md`.

### Bench (macOS arm64, M2 Ultra — validated CSV after harness fix)

| Lane | leap-c | leap-rust | mainline | tursodb CLI | turso-core lib |
|---|---|---|---|---|---|
| 1 cold-start (s) | **0.00321** | 0.00347 | 0.00866 | 0.01099 | 0.00980 |
| 2 parse+exec (B/s) | 28 680 | 36 791 | **2 836 978** | 311 494 | pending |
| 3 SELECT (sel/s) | 6 265 | 4 522 | **500 822** | 102 886 | pending |
| 4 INSERT (ins/s) | 20 075 | 37 997 | **695 890** | 202 279 | pending |
| 5 binary-size (B) | **412 704** | 1 125 552 | 1 219 888 | 13 486 168 | 6 330 224 |
| 6 memory (B) | **1 671 168** | 2 113 536 | 2 719 744 | 16 728 064 | 9 340 000 |

- **Decisive wins** (footprint axes — cold start, binary size, memory): leap-c beats **mainline, tursodb CLI, and turso-core library** on every lane. Ratios: 2.7× / 2.96× / 1.63× vs mainline; 3.4× / 32.7× / 10× vs tursodb; 3.0× / 15.3× / 5.6× vs turso-core.
- **Honest losses** (throughput axes — SELECT, INSERT, parse+exec): mainline beats leap-c by **80× on SELECT, 35× on INSERT, 99× on parse+exec**. sqlite-leap has no async I/O in v1 (Phase 5 wired but harness DB-mode prevents lane 4 uplift — see tech debt) and the VDBE is un-tuned. Don't publish as a speed claim.
- **Lane 2 methodology note (updated 2026-04-21):** corpus now pre-seeds 64 tables (`t0..t63(id,c1..c5)`) so the prior "83% fast-reject on undefined tables" path is gone; every statement targets real tables/columns. That ELIMINATED the false 31 MB/s claim. The lane now legitimately measures parse+execute throughput on a 10 MiB, 131 233-statement mixed workload; single-run (not median-of-5) given leap's 6-minute per-target runtime. 2× priors rule is satisfied — mainline 77× faster than leap-rust, 99× faster than leap-c, no spec-violating inversions. CSV: `bench/results/2026-04-21-lane2-fixed.csv`. For publication we plan to re-measure after VDBE tuning so the gap narrows.

### Linux x86_64 cross-validation

Docker image: `bench/Dockerfile.linux-x86` (debian:bookworm-slim + gcc 12.2 + rustc 1.82 + hyperfine 1.18 + sqlite3 3.40.1). Both C and Rust rebuild clean in-container. Emulated x86_64-on-arm64 via Docker's linux/amd64 platform flag — valid for correctness cross-val, not absolute-speed claims.

| Lane | leap-c | leap-rust | mainline |
|---|---|---|---|
| 1 cold-start (s) | **0.0250** | 0.0325 | 0.1217 (4.9× / 3.7×) |
| 5 binary-size (B) | **424 536** | 1 346 016 | 1 233 632 (2.9× smaller) |
| 6 memory (B) | **5.03 MB** | 5.67 MB | 6.06 MB (1.2× leaner) |

Smoke suite: **C 203/203 pass** and **Rust 203/203 pass** (byte-identical to macOS, incl. stdout redirected to pipe or file). The pre-#130 Linux-only crash under redirected stdout was resolved by the runner-to-engine refactor; see tech-debt item 5.

**Generator gaps surfaced by Linux cross-val** (fixed in-session, documented in `bench/results/linux-x86_64.README.md`):
- `src-c/Makefile` omits `-lm` — Linux linker fails (macOS didn't need it).
- `src-rust/Cargo.toml` `lto = "fat"` rejected by debian 12 binutils.
- `bench/lanes/_lib.sh` had Python 3.11 f-string bug + hyperfine 1.18 CLI arg bug.

All three are real "spec stayed neutral but generator output had platform leaks" findings — worth noting as LEAP discipline case studies.

## What changed this session

This session started from an external reviewer's critique showing bench lanes 2/3/4 fed malformed sqllogictest input to the leap binary — reported "207 MB/s parse speed" was actually "10 MB of malformed input rejected in 50 ms." CSV was retracted, harness rewrapped per-statement, and all numbers re-measured. Fraud inflation removed: lane 3 Rust 1100×, lane 4 Rust 71×, lane 4 C 36×. The new numbers show the honest story — wins on footprint, losses on throughput. That's the starting point.

Starting pass-rate: Rust **64.63%** / C **25.88%**. Six targeted fixes this session:

| Fix | Target | Impact |
|---|---|---|
| NULLIF scalar builtin (spec + engines) | both | ~120 random/expr files on each target |
| DIV/MOD by zero → NULL (SQLite quirk, not error) | both | 42 Rust + 7 C random/aggregates files |
| VIEW runtime wiring (`view_subst.rs` on Rust — phase 6ac was test-driver only) | Rust | 15 index/view files; reveals tech debt (see caveats) |
| Derived-table runtime wiring (same pattern, 6br) | Rust | scattered; +355 records on slt_good_1.test alone |
| C memblowup fix (#79) | C | unbounded RSS → 9 MB on select4.test; removes crash |
| C SIGBUS fix (PHASE6AG_OUTER_BIT collision) | C | 9 crashes flip to regular FAIL |

Rust pass rate: 64.63% → 93.89% → 98.71% → **98.87%** at file level (+213 files, zero PASS→FAIL regressions). Residual 7 non-PASS: 4 `random/groupby/slt_good_{8,10,11,12}.test` (interleaved alias + row-count errors), 1 `evidence/slt_lang_update.test`, 2 TIMEOUT (select4/select5). The cluster-fix round found:
- sqllogictest runner wasn't applying typechar-driven TEXT→INT/REAL coercion on expected values (pinned the rule in `spec/sqllogictest-runner.spec.md`).
- `SELECT * FROM t GROUP BY k` produced zero rows because Star projection collapsed to empty slice in the grouped path.
- `A LEFT JOIN B ON FALSE, C` produced 3 rows instead of 9 — LEFT-tail emit skipped nested cross-product loops. Added `emit_nested_null_fill`.
- #140 AMBIGUOUS_ALIAS tiebreak — mainline accepts duplicate-alias when name matches base column (base wins); documented as Phase 6cc in spec/sql-grammar.spec.md.

C pass rate: 25.88% → **90.19%** (v3) → **92.60%** (v4, post-#139 derived-table parser port) at file level. +415 files, zero PASS→FAIL regressions, zero panics. Residual 46 non-PASS: 13 FAIL (1 `evidence/slt_lang_update`, 12 `random/groupby/slt_good_*` bare-col cluster), 33 TIMEOUT (22 in `index/random/10/` + `index/random/100/` small-row planner cluster, 11 other large-row or joint-with-Rust). Big unlocks this session's round 2:
- #129 C planner fix — IDX* opcodes missing from pc-remap in 3 splicing paths (emit_inline_exists, emit_inline_in_subquery, splice_opcode) caused infinite loop on IN-subquery + indexed inner WHERE. 147 TIMEOUT→PASS.
- #133 DISTINCT copy-loop fix — `compile_select_distinct` dropped agg_distinct + scalar*_kind on opcode copy; `SUM(DISTINCT -10)` summed constant N times. 130 random/aggregates + 120 random/expr flipped.
- #139 Phase 6br derived-table parser port — C parser had rejected `FROM (SELECT …) AS alias` as "Phase 6bq non-goal"; index/view/* corpus uses this shape. All 15 C-only index/view files flip PASS.
- #114 + #116 index B-tree write correctness — single-leaf + multi-page 0x02 interior pages. Roundtrip matrix 105 → 108/108.
- #79 select4 memblowup, #119 random/groupby SIGBUS, #121 DIV-zero, NULLIF spec adoption.

## Known tech debt

1. **~~VIEW and derived-table support on Rust is in the sqllogictest runner, not the engine.~~** **RESOLVED 2026-04-20.** View + CTE + derived-table handling now lives in `src-rust/src/engine.rs` (`execute_sql` / `execute_ast`) keyed off `Database::views` (per-Database catalog, no thread-local state). `wasm.rs` and `bin/sqllogictest.rs` both route through the engine entrypoint; `view_subst.rs` is deleted. Library consumers that call `engine::execute_sql` against a fresh `Database` get full view semantics with no setup. Integration tests in `src-rust/tests/engine_view.rs` lock in the contract. Corpus pass rate unchanged at 615/622 (98.87%), phase regression 83/83 green.
2. **Bare non-key columns in GROUP BY + JOIN on leap-c** emit NULL; mainline + leap-rust emit last-row-seen value (via Phase 6bo sorter-trick). Fixture cases documented; divergence not crash.
3. **~~Lane 2 bench corpus references undefined tables~~** — **RESOLVED 2026-04-21.** `bench/lanes/02-parse-speed/generate-corpus.{py,sh}` now pre-seeds 64 CREATE TABLE statements (`t0..t63` with columns `id/c1/c2/c3/c4/c5`) before emitting 10 MiB of random statements that only reference defined tables with real columns. Re-measured: `bench/results/2026-04-21-lane2-fixed.csv` — mainline 2.84 MB/s, turso 311 kB/s, leap-rust 36.8 kB/s, leap-c 28.7 kB/s. Single-run numbers (not median); lane now measures parse+execute throughput and satisfies the 2× priors sanity rule.
4. **~~Phase 5 async I/O deferred.~~** **IMPLEMENTED 2026-04-21.** Both kqueue (macOS/BSD, `src-{c,rust}/io_backend_kqueue.{c,rs}`) and io_uring (Linux, raw-syscall, `src-{c,rust}/io_backend_iouring.{c,rs}`) backends wired on both targets. Backend-agnostic pager_async state machine (`src-{c,rust}/pager_async.{c,rs}`) dispatches via env var. SQ capacity 64/128 per backend. Epoch-stamped silent-drop cancellation. Spec: `spec/io-backend-{iouring,kqueue}.spec.md`, `spec/pager-async.spec.md`, `schema/io-{submission,completion}.schema.json`. Fixture `phase5-async-{kqueue,iouring}.json` passes on both targets.
6. **~~Phase 4b deferred — lane 4 still doesn't move.~~** **LANDED 2026-04-23.** Phase 4b WAL append-on-write is implemented on both C and Rust with a `phase4b.json` fixture (6/6 green on both), full spec coverage in `spec/wal.spec.md` § "Phase 4b" (session activation via `LEAP_WAL_APPEND=1`, snapshot-diff dirty-set, multi-frame recovery on reopen, checkpoint-on-close), and the lane 4 harness wired to exercise it via `LEAP_DB_PATH` + `LEAP_WAL_APPEND`. **The lane 4 number did not move** (leap-c 20 296, leap-rust 37 786 — same as pre-4b) because the existing workload is a single 100k-insert transaction = one commit = one frame batch; Phase 4b's win surface is many small commits (OLTP shape). Lane 4 loss vs mainline is VDBE CPU, not WAL I/O. Honest write-up: `bench/results/2026-04-23-lane4-phase4b.README.md`. Follow-up sub-lane (many-commit workload) listed as open scope.
5. **~~Linux Rust smoke failure~~** (mid-run abort) — **RESOLVED 2026-04-20 by #130.** The pre-#130 runner held view/derived-table state in a thread-local that interacted with stdio buffer teardown under glibc full-buffering. Lifting view+CTE+derived-table handling into `src-rust/src/engine.rs` and dropping the thread-local eliminated the crash. Verified in-container (`sqlite-leap-bench:linux-amd64`): 5 consecutive runs of `sqllogictest tests/sqllogictest/smoke >out 2>err`, all exit 0, 203/203. macOS pipe-redirect also 203/203 (no regression).

## What's in v1 scope (Done criteria per CLAUDE.md)

| criterion | status |
|---|---|
| sqllogictest pass ≥ mainline's own rate, both builds | Rust **98.87%** / C **92.60%** file-level on macOS (v4 logs committed); Linux Rust smoke 203/203 (the pre-#130 runner-stdio bug is resolved by the runner→engine refactor) |
| Reads/writes mainline-compatible DBs, both builds | **Yes — 108/108 roundtrip matrix, 50k-row indexed tables pass `PRAGMA integrity_check` via mainline** |
| Cross-build equivalence C ↔ Rust | **Yes — 203/203 byte-identical smoke** |
| All 6 bench lanes beat mainline, Linux+macOS | No — wins footprint lanes, loses throughput lanes. Honest. |
| Clean build macOS arm64 + Linux x86_64, zero warnings | macOS: yes. Linux: C yes, Rust yes (smoke 203/203 post-#130). |
| WASM build passing I/O-constrained sqllogictest + beats sql.js | WASM 546 KB artifact builds from Rust target; beat-claims pending measurement |

## Deferred to follow-up stunts (explicit non-goals for v1)

FTS5, R-tree, JSON1 beyond minimal, session/changeset, encryption, shell ornaments. Previously this list included Phase 5 async I/O and Phase 4b per-commit WAL append — both now landed. Open follow-ups: sub-lane 4b (many-commit workload to actually *demonstrate* Phase 4b's architectural win on bench numbers); VDBE dispatch tuning for lane 3/4 CPU cost.

## Reproducibility

Everything in this dashboard comes from committed artifacts:

- `bench/results/2026-04-20-Stanislavs-Mac-Studio-validated.csv` — macOS benchmarks
- `bench/results/2026-04-20-linux-x86_64.csv` + Dockerfile — Linux cross-val
- `bench/results/2026-04-20-turso-core-library-variant.csv` — fair engine-vs-engine numbers
- `tests/sqllogictest/results/2026-04-21-rust-full-v4.log` — 615/622 Rust pass-rate (post-#140 AMBIGUOUS_ALIAS fix)
- `tests/sqllogictest/results/2026-04-21-c-full-v4.log` — 576/622 C pass-rate (post-#139 derived-table parser port)
- `bench/results/2026-04-21-lane2-fixed.csv` — lane 2 re-measured after corpus regen
- `tests/roundtrip/results/2026-04-20-matrix.md` — 108/108 bidirectional
- `tests/cross-build/phase*.json` — engine-level fixtures (86+ phases including Phase 5 async)
- `tests/sqllogictest/smoke/` — 203 hand-authored cases, byte-identical both targets
- `spec/io-backend.spec.md`, `spec/io-backend-{iouring,kqueue}.spec.md`, `spec/pager-async.spec.md` — Phase 5 async-I/O contracts
- `SCOPE.md` — Phase 4b WAL append follow-up scope-out

Re-run commands and methodology notes in `bench/results/README.md` and `tests/sqllogictest/results/README.md`.

## Recommended framing for publication

1. **Lead with the proof.** "One language-neutral spec, two engines, 203/203 byte-identical smoke + 108/108 bidirectional roundtrip with mainline + 93.89% on upstream corpus (Rust)." That's the LEAP thesis made concrete.
2. **Own the bench story honestly.** "leap-c wins footprint (3-33× on cold-start / size / memory vs both mainline and Turso) but loses throughput by wide margins; async I/O (Phase 5) is the identified path." Don't inflate.
3. **Disclose the tech debt.** VIEW/derived-table tied to the test runner, not the engine, on Rust; Linux Rust smoke failing; bench lane 2 methodology bug. Debt-honesty IS the LEAP reputation.
4. **Decline to ship Turso-parity on throughput until Phase 5.** Say that explicitly.
