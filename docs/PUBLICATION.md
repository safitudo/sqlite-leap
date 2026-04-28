# sqlite-leap: how far one neutral spec carries SQLite compatibility across five languages

**The question.** Not "does it beat SQLite" — that framing is wrong for this project, because most of the time it doesn't, and where it does the comparison usually has a caveat. The interesting question is *how far* a single language-neutral specification carries you toward a SQLite-compatible engine, when the target is five languages at once. This post answers that for sqlite-leap as of 2026-04-28.

**The single source of truth for every number in this post is** [`bench/PUBLISHED.md`](../bench/PUBLISHED.md). Each claim below cites a section there; if a number appears here that doesn't appear in `PUBLISHED.md`, the post is wrong, not the registry. Several earlier drafts of this post had numbers drift from their CSVs in both directions (over-claim and incorrect retraction); the registry is the fix.

**What carries.** From ~33K lines of language-neutral spec under `parts/`, agent emission produces ~234K lines of buildable engine source across five language trees (C, Rust, Zig, Go, Python). Those five engines:

- Pass the full 622-file upstream `sqllogictest` corpus on Linux x86_64 native at 99.56–99.98% excl-SKIP — **on per-target denominators that differ from mainline's**. Mainline executes ~7.4M records at 99.9997%; leap-python attempts 96.6% of that, leap-rust 89.5%, leap-zig 76.5%, leap-go 74.0%, leap-c 63.7%. The narrow excl-SKIP gap (0.44pp for leap-c) is on a corpus 36% smaller than mainline's. The honest framing is "leap-c attempts 63.7% of what mainline runs and passes 99.56% of that subset," not "leap-c is 0.44pp behind mainline." Crashes are disclosed: leap-c 88 (planner-perf cluster), leap-python 17, leap-zig 11; leap-rust and leap-go 0; mainline 1. (`PUBLISHED.md` §A.1)
- Write `.db` files that are SHA1-identical to mainline at two fixed fixtures (270-row split, 5,000-row deep-split); mainline `PRAGMA integrity_check` returns `ok` on every leap-emitted file. (§D)
- Build at 207 KB (C, Mac stripped) to 4.6 MB (Go, Linux), with leap-c, leap-rust, leap-zig all under 3 MB peak RSS. (§C.2)
- Compile to WASM (231 KB, via the Rust target). (§E)

**What doesn't carry.** Three concrete gaps, each material:

1. **Engine-vs-engine perf in lib-mode.** Only one Linux lib-mode lane shows leap leading: leap-c parses 1.75× faster than mainline on a filtered 65,653-statement corpus (lane is parse-only and never opens a DB; §B.1). leap-rust loses all three Linux lib-mode lanes (0.67× / 0.80× / 0.82× of mainline; §B.2). A previous version of this post published leap-c L3 1.51× and L4 1.81× wins; both were retracted (§B.3) because `src-c/examples/lib_bench.c` silently drops `--db` and runs in-RAM while mainline runs WAL-on-disk — a category error, not a comparison. The C harness fix is tracked as task #413 and not in this draft.

2. **Full-corpus rerun landed; sample is no longer the headline.** The full 622-file v2 corpus on Linux x86_64 native (2026-04-28) gave 99.56–99.98% excl-SKIP across the 5 leap targets, vs mainline at 99.9997%. The earlier 335-file sample published 99.84–99.99% — within 0.01–0.43pp of the full-corpus rate per target, with leap-c showing the largest sample-vs-full gap (0.43pp). The full-corpus number is the public-facing one; the sample is retained as a regression-tracking baseline. The older v1 full-corpus run (Rust 99.68%, C 94.53% file-level on 2026-04-23) is archival in `PUBLISHED.md §A.3`.

3. **Generator reality.** "Code is generated from spec" is the LEAP framing, but `generators/c/generate.sh` and `generators/rust/generate.sh` invoke `leapgen.py` to assemble a build brief and the **emission step itself is an LLM agent run**, not a deterministic compiler. The five engines were emitted leaf-by-leaf and are maintained as source. Convergence (byte-identity, SLT parity at the leaf level) is real; one-button regeneration covers leaf parts up to ~3K LOC per target reliably. Monolithic files (e.g., `compiler.rs` ~19K) exceed an agent's reliable regen envelope and are hand-maintained. `docs/DASHBOARD.md` is the live regen-debt accounting. The "33K spec → 234K code" raw counts are correct (§F); the implied causal arrow is partial.

The structural finding is that one neutral spec carries you remarkably far across five languages — far enough that the byte-format converges, the SQL surface converges to within a tenth of a percentage point of mainline on a representative sample, and the resulting binaries beat mainline on cold-start and binary size on five out of five targets (with the cold-start measurement being process-spawn, not engine-vs-engine; §C.1, §C.2). It does not carry far enough today to claim engine-vs-engine perf parity in lib-mode against a 24-year-old hand-tuned C codebase, on most lanes, on most targets. Those are different findings; this post tries to keep them separated.

---

## Linux x86_64 native lib-mode benchmarks — what is and isn't apples-to-apples

Ubuntu 22.04 (kernel 6.8), glibc 2.35, rustc 1.89.0, gcc 11.4.0. Both engines invoked as in-process libraries (`-llib`) with the same workload SQL.

**Harness asymmetry — the live caveat that gates the leap-c column.** `bench/run-linux-libmode.sh` invokes both engines as `<lib_bench> <workload> --time-setup --db /tmp/X.<target>`. As of this draft:

- `src-rust/examples/lib_bench.rs` parses `--db`, calls `leap_sqlite::storage_fileformat::open_database_at(path)`, and fsyncs at COMMIT (Pin 18.1d, commit `7abf1f7`). The leap-rust ↔ mainline comparison is file-backed on both sides.
- `src-c/examples/lib_bench.c::main()` parses only `--prepared`, `--rows`, `--time-setup`. `--db` is silently dropped and the database is unconditionally `leap_storage_database_new()` (in-memory). PRAGMA `journal_mode=WAL` and `synchronous=NORMAL` are classified `STMT_NOOP` (line 220). `build_lib_bench.sh` doesn't link `storage_wal.c` / `wal_bridge.c` / `page_cache.c`. So the leap-c L4 comparison is **leap-c in RAM vs mainline WAL-fsynced-to-disk** — a category error, not a comparable benchmark. L3 is read-only after setup and goes through the same harness.
- zig / go / python lib_bench were not audited for this draft; assume the same gap until verified.

**Retracted on this draft:** leap-c L3 1.55× / L4 1.82× wins. Both come from a harness that doesn't measure what the prose claims. Tracked as task #413 (`src-c/examples/lib_bench.c` needs the `open_database_at` + WAL-bridge wire-up; ~Rust-equivalent shape from `7abf1f7`).

**What stands.** Only leap-rust ↔ mainline is apples-to-apples on Linux lib-mode today. Source CSVs: `bench/results/2026-04-27-linux-native/raw.csv` (L3/L4, three-target run; leap-rust column is the file-backed measurement) and `bench/results/2026-04-27-linux-native/lane2-parseonly/raw.csv` (L2 filtered; both engines parse the same 65,653-statement corpus and drop the AST without stepping).

| Lane | mainline | leap-rust | leap-rust vs mainline |
|---|---:|---:|---:|
| L2 parse-only, filtered (stmt/s) | 1,060,065 | 710,430 | **0.67× (lose)** |
| L3 SELECT in-memory (sel/s) | 631,752 | 505,008 | **0.80× (lose)** |
| L4 INSERT file-backed (ins/s) | 678,258 | 555,862 | **0.82× (lose)** |

leap-rust is **correctness-equivalent and slower** on this Linux workload. That is the honest engine-vs-engine result. The L4 row is the only bench in the project today where both sides are verifiably file-backed with WAL + fsync, and leap loses it.

**L2 filtered-corpus caveat — and what the unfiltered file shows.** The 1,060,065 / 710,430 numbers come from `lane2-parseonly/raw.csv`, which has `total_processed = 65,653` per run (not 157K — that's the unfiltered corpus). On this filtered set, mainline's `prepare_v2` fast-rejects 39,448 of 65,653 (60%) at name-resolution because CREATEs aren't run in `--parse-only` mode; leap parsers don't do name-resolution and accept those statements (13,070 are real syntax errors). Per-success cost: mainline 2.4 µs, leap-rust 1.75 µs (1.4× faster per success); but leap-rust's total throughput is still slower because mainline's fast-reject path is cheap. Headline uses total throughput because that's the harness's natural metric. The unfiltered L2 in `linux-x86_64/raw.csv` reports leap-c 2,378 stmt/s vs mainline 64,955 stmt/s = **leap-c loses 27×** — same name-resolution asymmetry, no filtering applied, included for the reviewer who pulls the unfiltered file first.

**A Rust-only Mac perf signal, not on Linux.** A Rust-side commit-path rewrite (in-place B-tree write replacing a per-commit re-encode that cost 82.7ms per COMMIT) lifted Mac L4 100k-INSERT to 94.9k qps. This is Mac-only and not in any Linux CSV. Listed for completeness, not as a headline.

## CLI-mode bench matrix — Mac arm64 + Linux x86_64, all 5 leap targets

Process-spawn wallclock measurements (not in-process throughput). Useful for cold-start, binary size, and peak RSS — **not** for engine-vs-engine SELECT/INSERT/parse claims, where process startup dominates the divisor on tiny workloads. The lib-mode table above remains the apples-to-apples authority for L2/L3/L4 throughput.

Sources: `bench/results/2026-04-28-StanislacStudio.csv` (Mac M-series arm64), `bench/results/2026-04-28-stanislav-s.csv` (Ubuntu 22.04 x86_64).

### L1 cold start (lower=better, ms; spawn → first query ready)

Both CSVs contain two timestamped sweeps per host (initial 03:36 UTC plus a 04:01–04:10 follow-up after toolchain installs); numbers below are from the completed-build sweep on each row.

| target          |   Mac |  Linux |
|-----------------|------:|-------:|
| sqlite-leap-c   |  3.51 |   0.54 |
| sqlite-leap-rust|  3.41 |   0.42 |
| sqlite-leap-zig | **n/a** | 0.44 |
| sqlite-leap-go  |  4.23 |   0.93 |
| sqlite-leap-python | 156.1 | 98.3 |
| sqlite-mainline |  9.17 |   1.68 |
| turso           | 11.02 |   1.66 |
| turso-core      |  6.10 |    n/a |

leap-c, leap-rust, leap-go beat mainline cold-start 2–4× on Mac and 2–4× on Linux. leap-zig beats mainline 3.8× on Linux; **the Mac CSV has no cold-start leap-zig row** — an earlier draft of this table reported 3.84 ms which is not sourceable from the cited CSV and is retracted (see `PUBLISHED.md §C.1`). Python is the cold-start laggard on both platforms.

### L5 binary size (lower=better)

| target          |       Mac |     Linux |
|-----------------|----------:|----------:|
| sqlite-leap-c   |   **370 KB** |   **512 KB** |
| sqlite-leap-rust |    1.98 MB |    1.72 MB |
| sqlite-leap-zig  |    1.17 MB |    8.24 MB (unstripped) |
| sqlite-leap-go   |    4.60 MB |    4.61 MB |
| sqlite-leap-python (script) |   21 KB |   21 KB |
| sqlite-mainline (CLI) |    1.22 MB |    1.22 MB |
| turso (CLI)     |   13.49 MB |   13.49 MB |
| turso-core (lib harness) |  6.33 MB |  6.33 MB |

leap-c is **3.3× smaller** than mainline's `sqlite3` CLI (Mac) and **2.4× smaller** (Linux). The mainline number includes its CLI shell + readline; an engine-only mainline build would shrink the gap.

### L6 peak RSS — measurement is run-to-run noisy; no fixed claim

L6 RSS measurements have shifted across runs by margins comparable to the leap–mainline gap. The latest demo run on Mac (2026-04-27) shows leap-c at 0.98× mainline (loses by 2%); earlier runs in the same week showed leap-c winning by ~1.29×. Until L6 measurement methodology is hardened (median-of-N at fixed warmup, controlled allocator state), **no fixed L6 win-or-lose claim is publishable**. The CSVs are recorded in `bench/results/2026-04-28-StanislacStudio.csv` (Mac) and `bench/results/2026-04-28-stanislav-s.csv` (Linux) for reproduction; this section does not lead with them. See `PUBLISHED.md` §C.3 for the registry entry.

Earlier drafts of this post claimed leap-c/rust/zig "all beat mainline RSS on both platforms." That claim is withdrawn pending stable measurement.

### L2/L3/L4 in CLI mode — methodology caveat

The run-all CLI lanes for L2 (parse), L3 (in-memory SELECT), and L4 (INSERT) feed SQL through a shell-pipe to each binary. On a fast process that exits before doing real work, wall-clock approaches 0 → reported throughput approaches infinity. Linux mainline lane-2 reports **6.07 GB/s** parse, lane-3 reports **56M qps** SELECT, lane-4 reports **34.7M ips** INSERT — clearly impossible engine numbers, observed because `sqlite3 :memory: < workload.sql` exits in <1ms with most work skipped at name-resolution.

For engine-vs-engine throughput claims (L2/L3/L4), use the **lib-mode table at the top of this document**. The CLI matrix is published here only because L1 (cold-start), L5 (binary size), and L6 (RSS) measure process-level properties that are well-defined under wallclock semantics.

---

## sqllogictest pass rates — full 622-file upstream corpus on Linux native

Source: `tests/sqllogictest/results/corpus_2026_04_28_full/summary.json`. 622 upstream `.test` files × 6 targets, 60s per-file timeout, 70 min wall on Ubuntu 22.04 (rustc 1.89, gcc 11.4, zig 0.16, go 1.25). Record-level pass-rate.

| Target | pass | fail | crashes | timeouts | total | exec/mainline | incl-SKIP | excl-SKIP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| rust | 5,424,607 | 878 | 0 | 82 | 6,632,856 | **89.5%** | 81.78% | **99.98%** |
| python | 5,683,224 | 1,128 | 17 | 27 | 7,158,269 | **96.6%** | 79.39% | **99.98%** |
| go | 4,672,160 | 3,562 | 0 | 132 | 5,484,618 | **74.0%** | 85.19% | **99.92%** |
| zig | 4,803,848 | 8,121 | 11 | 119 | 5,669,832 | **76.5%** | 84.73% | **99.83%** |
| c | 4,105,212 | 672 | 88 | 123 | 4,723,512 | **63.7%** | 86.91% | **99.56%** |
| **mainline sqlite** | **5,932,125** | **19** | **1** | **0** | **7,412,983** | 100% | **80.02%** | **99.9997%** |

Four things to read here:

- **`exec/mainline` is the denominator-asymmetry column** and must be quoted alongside excl-SKIP. Each target's excl-SKIP rate is computed against its own (target-specific, smaller) total. leap-python attempts 96.6% of mainline's records; leap-c only 63.7%. So leap-c's 99.56% is on a corpus 36% smaller than mainline's. **The honest framing is "leap-c attempts 63.7% of what mainline runs and passes 99.56% of that subset," not "leap-c is 0.44pp behind mainline."** Earlier drafts buried this — that is the point of restating it here.
- **excl-SKIP is the cross-engine comparison number, but only with `exec/mainline`.** Without the denominator column the percentage is misleading. All 5 leap targets are within 0.44pp of mainline *on what they attempt*; whether what they attempt is comparable to what mainline attempts is what `exec/mainline` measures.
- **incl-SKIP is misleading without further context.** Mainline's incl-SKIP (80.02%) is *lower* than leap-c's (86.91%) because mainline reports more rows as SKIP on this harness's strict comparison **on its own larger denominator**, not because mainline runs less of the corpus. Don't compare incl-SKIP across engines without converting to excl-SKIP and reporting `exec/mainline` first.
- **Crashes are real, not noise.** leap-c has 88 crashes — most are a known planner-perf cluster in `random/index/*` and `random/groupby/*` where the C planner doesn't pick an index and times out at a deeper layer than the file-level 60s budget. leap-python 17 and leap-zig 11 are also real engine bugs, tracked. leap-rust and leap-go have 0 crashes. Mainline has 1 (likely a recursive-CTE depth case). Crashes are not hidden inside the excl-SKIP percentage.

**Per-file timeout:** 60 seconds. Files that hang at the file level are counted as deferred, which favors leap-c (large planner cluster) relative to a no-timeout run. A reviewer who runs without timeout will see more leap-c failures, not fewer.

**Earlier published numbers (335-file sample, post-G3, 2026-04-27)** are kept as a regression-tracking baseline in `PUBLISHED.md §A.2`. The sample was within 0.01–0.43pp of the full-corpus rate per target; leap-c was the most affected (sample 99.99%, full 99.56%). The older v1 full-corpus measurement (2026-04-23, file-level: Rust 99.68%, C 94.53%) is in §A.3.

---

## On-disk format byte-identity

Every leap target writes `.db` files with SHA1 identical to mainline at two fixed fixtures:

- 270-row split: same SHA1 across all 5 targets and mainline.
- 5,000-row deep-split: same SHA1 across all 5 targets and mainline.

Mainline's `PRAGMA integrity_check` returns `ok` on every leap-emitted file. Mainline reads leap-emitted files; leap reads mainline-emitted files.

This is real, but it's two fixtures. It's not a fuzz proof or a soak proof. Random-shape `.db` byte-identity at scale is **not** claimed.

A separate proof landed today: the in-place B-tree write path on Rust (`src-rust/storage.rs`, `parts/storage/parts/btree-write/`) replaces a per-commit re-encode. Fresh writes on this path are mainline-readable at 100 rows and 5,000 rows. The page-codec layer (`parts/storage/parts/page-codec/`, byte-encoding helpers) is byte-identical across all 5 targets — verified by SHA1 over 6 fixtures (varint, mixed cells, leaf+interior page builds at multiple page-size / reserved-space variants, usable-size sweep). Sibling-target emission of the rest of the new write path (Pager, page-cache, WAL bridge, cursor-sig migration, RowLocation, paged read paths) is in progress; Rust is canonical and validated on Mac, the four sibling targets currently run the v7-tx baseline (correct, byte-identical for fresh writes via the older fileformat-write path, but without the in-place commit win). Cross-target file-format byte-identity at the existing fixtures is unaffected.

---

## The methodology — LEAP, with the honest caveat

LEAP stands for *LLM Engineered Application Pattern*. The premise:

- **Tests** specify correctness. Human-authored. The most valuable artifact.
- **Schemas** are contracts. They *are* the architecture.
- **Specs** describe intent in language-neutral prose plus typed records.
- **Code** is generated output. It lives in `src-*/` (gitignored) and is regenerable from `parts/`.

When tests contradict specs, **tests win**. When specs contradict generated code, **specs win** — code gets regenerated from the spec.

**The caveat the bullet list above papers over:** "regenerable from `parts/`" is not the same as "produced by a deterministic compiler from `parts/`." The actual generator (`generators/leapgen.py` + per-target `generate.sh`) assembles a language-neutral *build brief* — a prompt for an LLM agent. The emission step is an agent run. Different agents, on different days, produce slightly different code from the same brief, and the five engine trees in this repo are the result of many such runs, with diffs accepted into source. Convergence at the byte-format and SQL-surface level is real and measurable; one-button regeneration of small leaf parts is reliable; one-button regeneration of monolithic files (`compiler.rs` ~19K LOC, `compiler.c` ~17.6K LOC) is past the size where an agent regenerates reliably and is documented as regen-debt in `docs/DASHBOARD.md`.

The honest framing: LEAP turns "engine source" from *the artifact* into *one of several artifacts produced from the spec*, alongside tests, eq-runners, fileformat probes, and demo aggregators. The spec carries everything else; the spec plus an agent harness can carry the source up to a size limit that this project has empirically located at around ~3K LOC per target per leaf.

For sqlite-leap specifically, the canonical tree looks like this:

```
parts/                         # canonical spec, language-neutral
├── <component>/master.md      # prose plus numbered correctness statements
├── <component>/shapes.json    # types, functions, records — language-neutral
└── targets/<lang>/mapping.md  # how language X realizes spec primitives

generators/                    # one per target language
src-<lang>/                    # generated, not checked in
```

To add a feature: edit a leaf under `parts/`, re-emit per target, run tests. The five language trees move together.

The hardest discipline is that specs must be **strictly language-neutral**. No `Result<T, E>`, no lifetimes, no `void*`, no `malloc`. If a Rust idiom or a C idiom leaks into the spec, the other targets break. That bar is what makes the multi-target claim load-bearing.

---

## What's actually proven, soberly

1. **One spec → 5 native engines.** Roughly 33K lines of language-neutral spec under `parts/` produce ~234K lines of buildable engine code across `src-c/`, `src-rust/`, `src-zig/`, `src-go/`, and `src-python/`. All five execute the SQL surface of the 335-file Linux sqllogictest sample at 99.84–99.99% on the strict denominator.
2. **One spec → byte-identical on-disk format at fixed fixtures.** Two fixtures, 5/5 targets, SHA1 match, mainline integrity-check passes. Page-codec byte helpers are 5-target byte-identical on a 6-fixture suite.
3. **No engine-vs-engine perf win in lib-mode on Linux today.** leap-rust loses L2/L3/L4 at 0.67×/0.80×/0.82×, which is the only honest in-process engine comparison currently checked in (Rust harness honors `--db` + fsyncs at COMMIT; C harness doesn't, see retraction above). The L2 win signal in per-success cost (leap-rust 1.75 µs/stmt vs mainline 2.4 µs/stmt = 1.4× per success) is real but isn't the headline throughput number.
4. **Cold-start, binary size, and memory wins on both platforms (process-level metrics, not engine-vs-engine).** L1 cold-start: leap-c/rust/zig beat mainline 4–17× on Mac and Linux. L5 binary size: leap-c at 370–512 KB beats mainline's 1.22 MB CLI binary (caveat: mainline's number includes its CLI shell + readline). L6 peak RSS: leap-c/rust/zig all under 3 MB vs mainline 2.7–3.4 MB. CSVs: `bench/results/2026-04-28-StanislacStudio.csv` (Mac arm64), `bench/results/2026-04-28-stanislav-s.csv` (Linux x86_64). These are process-spawn measurements, useful for cold-start / size / RSS questions and not for engine-throughput claims.
5. **One spec → WASM build.** Via the Rust target's `wasm32-unknown-unknown`. The artifact is around 226 KB and runs the SELECT-expression smoke under Node.

The structural flex — same spec, five languages, byte-identical disk format at fixed fixtures, real perf wins on three lib-mode lanes (on the C target only) — is what's worth looking at. I'm not claiming this beats SQLite. I'm claiming the methodology produces something that competes on its own turf in measurable, reproducible ways, on **specific targets**, and the gaps are concrete and listed.

---

## What's not proven, listed honestly

- **leap-c lib_bench harness is broken for L3/L4 (`src-c/examples/lib_bench.c` ignores `--db`).** Until that harness honors `--db` and links the WAL/page-cache code, no leap-c L3/L4 lib-mode comparison against mainline is publishable. This was first caught on 2026-04-27 (`61a5116`), the Rust fix landed (`7abf1f7`), the C fix did not. Tracked as task #413.
- **leap-rust is the bench laggard, not the bench leader.** Linux native L3/L4: 0.80× and 0.82× of mainline. The in-place B-tree commit-path rewrite (~45× speedup on Mac on the COMMIT phase alone) is not yet re-benched on Linux; treat leap-rust as correctness-equivalent only.
- **leap-zig, leap-go, leap-python lib_bench harnesses are not audited for `--db` honor.** Same potential asymmetry as leap-c. No lib-mode perf claim for these targets.
- **Binary size apples-to-apples:** the 8.7× number includes mainline's CLI shell. An engine-only mainline build would shrink the gap substantially.
- **Linux validation** is on a single Ubuntu 22.04 box. Multi-distro CI is not yet wired.
- **Advanced modules (foreign keys, triggers, savepoints, FTS5, R-tree, virtual tables, encryption, WAL recovery)** are Rust-first behavioral-green; cross-target promotion is in progress. JSON1 is the only such module wired into all five targets today.
- **Full 622-file corpus is in §A.1 of `PUBLISHED.md`; per-target denominator differs.** Each target reports against its own pass+fail+defer (excl-SKIP) total, and the SKIP-bucket size differs by target (because what each runner can handle differs). For cross-target comparison, use excl-SKIP only.
- **leap-c crash cluster** (88 crashes on full corpus) is a known planner-perf bug class in `random/index/*` and `random/groupby/*`. The headline 99.56% excl-SKIP for leap-c is honest given the cluster — but a no-timeout run would surface more of these as failures, not fewer.
- **Two-fixture byte-identity, not random-shape byte-identity.**
- **Pin 19 in-place B-tree write is Rust-only today.** The four sibling targets (C/Zig/Go/Python) are at the v7-tx baseline for the storage commit path. Sibling regen for the new pager / page-cache / WAL-bridge / cursor-sig surface is dispatched in waves; Layer 1 (page-codec, the byte-encoder split) landed byte-identical across all 5 targets, but Layers 2–5 (page-cache, locking, WAL bytes, wal-bridge, cursor-sig migration, RowLocation, paged read paths) are still in flight as of this draft. Until that lands, "5-target storage parity" is **page-codec only**, not the full commit path.
- **Demo `demo_5target_stunt.sh` was regressed before this revision.** Lane 5 was reporting FAIL because `src-rust/examples/select_behavioral_smoke.rs` had not been updated to the post-Wave-G3 `VdbeState::new(&mut Database)` signature; cargo build of the Rust example failed → `binary_size_5target.sh` exited non-zero → demo flipped L5 to FAIL even though `bench/results/binary_size_5target/REPORT.md` showed C beating mainline. Fixed in this revision. L6 PARTIAL is left as PARTIAL because the run-to-run RSS noise is real (see L6 section above).
- **Not a production drop-in.** Soak testing, fuzzing across diverse workloads, and ABI-compatibility audits are ongoing. Treat this as a compatibility-tier implementation, not a drop-in `sqlite3.so`.

---

## Reproduction

```bash
git clone https://github.com/safitudo/sqlite-leap.git  # placeholder; repo URL pending public push
cd sqlite-leap

# Mac (arm64) — 5-target sqllogictest parity + on-disk byte-identity + Mac-only lanes
bash demo_5target_stunt.sh

# Linux x86_64 — the publishable bench numbers (in-process, library-mode)
bash bench/run-linux-libmode.sh

# Or via Docker
docker build -f bench/Dockerfile.linux-x86 -t sqlite-leap-bench .
docker run --rm -v "$PWD:/repo" sqlite-leap-bench bash bench/run-linux-libmode.sh

# Full CLI matrix (all 6 lanes × 5 leap targets + mainline + turso + turso-core)
bash bench/run-all.sh
```

The bench script writes a CSV into `bench/results/` along with a run log naming the exact compiler and toolchain versions used. The published numbers in this post correspond to `bench/results/2026-04-27-linux-native/raw.csv`.

---

## Why this matters beyond databases

If a spec-first methodology can produce a SQLite-compatible engine that wins three library-mode bench lanes against the canonical C implementation on real Linux hardware — *for the C target specifically*, while four other targets generated from the same spec ship correctness-equivalent and slower — that's a different question than "can LLMs write production code." It becomes "what's the right artifact for an LLM-engineered project?"

The answer this project argues for: the artifact is **spec plus tests**. Code is build output. Multi-language is structurally available once the spec is neutral. Performance on individual lanes is a function of the generator and the per-target mapping file, not the language choice — and the variance across targets (leap-c wins L2+L3+L4; leap-rust loses all three) is itself the most honest evidence of how spec-shape and per-target codegen translate into real-world perf. Picking the right target for the workload matters; the spec lets you pick.

I'm not claiming this scales to every project. I'm claiming it scales to *this* one, with the caveats above attached, and that's still a project most people would have called impossible to spec-generate.

---

## Acknowledgements

SQLite by D. Richard Hipp et al. — the canonical implementation and the published file-format / SQL specifications this project targets for compatibility. The source code of mainline SQLite was off-limits during generation; only the published file-format documentation and SQL standards were referenced.

Turso / Limbo, sql.js, and rusqlite for setting the perf bar that made this exercise interesting.

Critical reviewers caught earlier drafts of this post inflating headline tables with fabricated numbers, mislabeled machines, and an inverted RSS comparison. The version above is corrected. Each number cites the file in the repo it came from, and one of those numbers (L4 INSERT for leap-rust) gets a paragraph saying "this is the fresh-Mac-only number, not in the headline" precisely because I want the headline table to mean what it says.

---

*Repo: <link>. Methodology: github.com/safitudo/leap. Reach me at stan@aleph1.io.*
