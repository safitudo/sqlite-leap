# sqlite-leap: one spec → 5 SQLite engines, with honest numbers

**TL;DR.** I built a SQLite-compatible database engine from a single language-neutral specification that produces buildable engines in **C, Rust, Zig, Go, and Python** — five at once, from one spec. All five pass a 335-file Linux sample of the upstream `sqllogictest` corpus at 99.84–99.99% on a strict denominator. They write `.db` files that are byte-for-byte identical to mainline at two fixed-size fixtures and that mainline reads cleanly.

**Bench leader is leap-c, not leap-rust.** On Linux x86_64 native lib-mode against mainline SQLite, leap-c wins **L2 parse 1.75×** (1.86M qps vs 1.06M), **L3 SELECT 1.51×** (956k qps vs 631k), and **L4 INSERT 1.81×** (1.23M ips vs 678k) — three for three. leap-rust on the same harness loses all three — 0.67× parse, 0.80× SELECT, 0.82× INSERT. Rust is correctness-equivalent (byte-identical disk format, ~99.99% sqllogictest excl-SKIP) but is the perf laggard. A Rust commit-path rewrite that landed today (in-place B-tree write, removes a per-commit re-encode that cost 82.7ms) hasn't been re-benched on Linux yet; on Mac it lifted L4 to 94.9k qps in a 100k-INSERT loop, which is a real improvement but does not close the Linux gap to mainline by itself.

This is a methodology proof, not a SQLite replacement. The point is that **specs and tests can be the product, with code as commodity output** — and the result is competitive, on some axes, with hand-written code from a 25-year-old project, when the perf-leading target (C) is the one being measured. Other targets are correctness-equivalent and slower.

This post is deliberately honest about what *doesn't* beat mainline. Earlier drafts over-claimed; the version below is what the files in the repo actually say.

---

## Linux x86_64 native lib-mode benchmarks — apples-to-apples

Source: `bench/results/2026-04-27-linux-native/raw.csv`. Ubuntu 22.04 (kernel 6.8), glibc 2.35, rustc 1.89.0, gcc 11.4.0. Both engines invoked as in-process libraries (`-llib`) with the same workload SQL. L3 reads from in-memory after setup (mainline `:memory:`, leap `Database::new()`); L4 writes file-backed via `--db PATH` honored on both sides (mainline opens the file, leap routes through `leap_storage_open_database_at`). Same machine, same hour, same run.

All three lanes are `--parse-only` / unmodified-workload symmetric: same harness, same flags on both engines. L2 runs `prepare_v2 + finalize` on mainline and `tokenize + parse` on leap (both drop the AST/stmt without stepping). L3 runs in-memory; L4 is file-backed via `--db PATH` honored on both sides.

| Lane | mainline | leap-rust | leap-c | leap-c vs mainline | leap-rust vs mainline |
|---|---:|---:|---:|---:|---:|
| L2 parse-only, filtered (stmt/s) | 1,060,065 | 710,430 | 1,857,806 | **1.75× (win)** | **0.67× (lose)** |
| L3 SELECT in-memory (sel/s) | 631,752 | 505,008 | 956,662 | **1.51× (win)** | **0.80× (lose)** |
| L4 INSERT file-backed (ins/s) | 678,258 | 555,862 | 1,228,876 | **1.81× (win)** | **0.82× (lose)** |

What this says, plainly:

- **leap-c wins all three lanes** on real Linux silicon. L2 1.75×, L3 1.51×, L4 1.81×. Reproducible via `bench/run-linux-libmode.sh`. CSVs at `bench/results/2026-04-27-linux-native/lane2-parseonly/raw.csv` (3 runs each lane), `.../raw.csv` for L3/L4.
- **leap-rust loses all three** at 67–82% of mainline. It's correctness-equivalent and produces the same .db files; it's just slower across the board on this workload. The reason isn't language overhead — it's that perf optimizations (PK index, predicate-pushdown, prepared-statement cache, in-place B-tree write) landed Rust-first as prototypes, and only some have been promoted to spec or ported to leap-c. The fact that leap-c is faster than leap-rust *despite* the optimizations being Rust-side first is itself a useful signal: idiomatic C with a tight VDBE dispatch outperforms idiomatic Rust on this workload.
- **L2 parse caveat — name resolution.** mainline's `prepare_v2` does parse + name-resolution + bytecode emit; on this corpus 39,448 of 65,653 statements (60%) fast-reject at name-resolution with "no such table" because CREATEs aren't being executed in `--parse-only` mode. Leap parsers do pure syntactic parse without name resolution, so they accept those statements (13,070 errors are real syntax rejections). Cost-per-successful-parse: mainline 2.4 µs, leap-c 0.67 µs (**3.6× faster per success**), leap-rust 1.75 µs (1.4× faster per success than mainline). Both numbers favor leap, but the headline 1.75× and 0.67× use total throughput including fast-rejects, which is the harness's natural metric. A future iteration that runs CREATEs untimed first, then times only schema-resolved SELECT/INSERT prepares, would likely widen leap-c's win further. We publish the conservative number.
- **leap-c L4 INSERT was 1.81× a known-good harness:** mainline opens `/tmp/X.main`, runs the WAL workload with `PRAGMA journal_mode=WAL` + `synchronous=NORMAL`, fsync at COMMIT. leap-c opens `/tmp/X.c` with the same path semantics (storage_pager + WAL bridge + fsync gated by PRAGMA synchronous). Both pay fsync; leap-c is faster anyway because the leaf-page write path is tighter.

A Rust-side commit-path rewrite (in-place B-tree write replacing a per-commit full-DB re-encode that previously cost 82.7ms per COMMIT) landed in `src-rust/storage.rs` and `src-rust/storage_pager.rs` today. On Mac, the new Rust path runs the L4 100k-INSERT loop at 94.9k qps, with mainline `PRAGMA integrity_check` returning `ok` and reopen recovery green. On Linux, the previous Rust number above (555,862 ips) precedes this rewrite. The expected delta on Linux is significant but **not measured yet**, and is not part of the headline table until it is. Today's measurable Rust win is correctness, not perf.

## Mac arm64 benchmarks (different machine, different methodology)

These were measured on Mac arm64, not Linux. Treat as confirmatory, not headline. The lane harnesses also differ — these are process-spawn wallclock measurements, not in-process throughput.

Source files: `bench/results/cold_start_5target/REPORT.md`, `bench/results/binary_size_5target/REPORT.md`, `bench/results/memory_footprint_5target/REPORT.md`.

| Lane | leap-c | mainline | leap-c vs mainline | notes |
|---|---:|---:|---:|---|
| Cold start (`open` → first query ready) | 3.28 ms | 5.65 ms | **1.72× faster** | median over 11 samples; mainline = `sqlite3 :memory:` CLI |
| Binary size (engine-only smoke) | 203 KB | 1767 KB | **8.7× smaller** | mainline number includes CLI shell + readline + ICU; engine-only mainline build would close most of the gap |
| Peak RSS (`CREATE` + 1k `INSERT` + `SELECT`) | 3.05 MB | 3.01 MB | **0.98× — leap is slightly worse** | not "idle RSS"; short-lived-process peak |

The binary-size caveat is load-bearing. The 8.7× figure compares leap's pure-engine binary against mainline's CLI tool — a fair fight against an engine-only mainline build would shrink the gap substantially. I report what's measurable, but I don't claim it's apples-to-apples.

The peak-RSS row **is not a win**. Mainline is lighter on this measurement.

The cold-start row is a clean win on Mac arm64; Linux validation of cold-start is on the to-do list.

---

## sqllogictest pass rates — 335-file Linux run

Source: `tests/sqllogictest/results/corpus_2026_04_26_v33_linux/summary.md`. 335 files per target, 60s per-file timeout.

| Target | incl-SKIP | excl-SKIP |
|---|---:|---:|
| rust | 95.08% | 99.99% |
| c | 96.60% | 99.84% |
| zig | 95.98% | 99.97% |
| go | 96.13% | 99.99% |
| python | 92.96% | 99.98% |
| **mainline sqlite** | **94.56%** | **100.00%** |

Two denominators, both honest:

- **incl-SKIP** counts files where some statement was skipped due to an unimplemented feature (deferred BLOB literals, certain qualified-column refs, etc.) as a partial pass. Leap targets land at 92.96–96.60%; mainline lands at 94.56% on the same sample (because the sample includes files mainline also doesn't fully execute on this harness's strict comparison).
- **excl-SKIP** drops SKIP rows from the denominator. On that denominator, leap targets land at 99.84–99.99% and mainline at 100%. This is the number worth quoting only if you also disclose it's an excl-SKIP number — which I am.

**Sample size:** 335 files per target, not the full upstream corpus (which is ~5M+ statements across thousands of files). An earlier draft said "passes the upstream corpus." That overstated. It's a representative slice, and a full-corpus run will probably produce lower rates and surface buckets the sample missed. That run is on the to-do list.

**Per-file timeout:** 60 seconds. Files that hang are bucketed as deferred, which favors leap relative to a no-timeout run.

---

## On-disk format byte-identity

Every leap target writes `.db` files with SHA1 identical to mainline at two fixed fixtures:

- 270-row split: same SHA1 across all 5 targets and mainline.
- 5,000-row deep-split: same SHA1 across all 5 targets and mainline.

Mainline's `PRAGMA integrity_check` returns `ok` on every leap-emitted file. Mainline reads leap-emitted files; leap reads mainline-emitted files.

This is real, but it's two fixtures. It's not a fuzz proof or a soak proof. Random-shape `.db` byte-identity at scale is **not** claimed.

A separate proof landed today: the in-place B-tree write path on Rust (`src-rust/storage.rs`, `parts/storage/parts/btree-write/`) replaces a per-commit re-encode. Fresh writes on this path are mainline-readable at 100 rows and 5,000 rows. The page-codec layer (`parts/storage/parts/page-codec/`, byte-encoding helpers) is byte-identical across all 5 targets — verified by SHA1 over 6 fixtures (varint, mixed cells, leaf+interior page builds at multiple page-size / reserved-space variants, usable-size sweep). Sibling-target emission of the rest of the new write path (Pager, page-cache, WAL bridge, cursor-sig migration, RowLocation, paged read paths) is in progress; Rust is canonical and validated on Mac, the four sibling targets currently run the v7-tx baseline (correct, byte-identical for fresh writes via the older fileformat-write path, but without the in-place commit win). Cross-target file-format byte-identity at the existing fixtures is unaffected.

---

## The methodology — LEAP

LEAP stands for *LLM Engineered Application Pattern*. The premise:

- **Tests** specify correctness. Human-authored. The most valuable artifact.
- **Schemas** are contracts. They *are* the architecture.
- **Specs** describe intent in language-neutral prose plus typed records.
- **Code** is generated output. It lives in `src-*/` and is not checked into the repo.

When tests contradict specs, **tests win**. When specs contradict generated code, **specs win** — code gets regenerated from the spec.

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
3. **Three perf wins on Linux native, all on leap-c.** L2 parse 1.75×, L3 SELECT 1.51×, L4 INSERT 1.81× vs mainline at the same hour, same harness, same workload. Reproducible via `bench/run-linux-libmode.sh`. CSVs at `bench/results/2026-04-27-linux-native/lane2-parseonly/raw.csv` (3 runs, 1.86M / 1.07M / 710k qps for leap-c / mainline / leap-rust) and `bench/results/2026-04-27-linux-native/raw.csv` (L3/L4). **leap-rust loses all three at 67–82% of mainline** — it is correctness-equivalent, not perf-equivalent. **Picking a different leap target moves you from "wins three lanes" to "loses three lanes" with no other change**, and that's worth knowing before citing this work.
4. **One Mac-only perf win that doesn't go through the lib-bench harness.** Cold start on Mac arm64 is 1.72× faster than mainline (CSV: `bench/results/cold_start_5target/REPORT.md`). Linux validation pending.
5. **One spec → WASM build.** Via the Rust target's `wasm32-unknown-unknown`. The artifact is around 226 KB and runs the SELECT-expression smoke under Node.

The structural flex — same spec, five languages, byte-identical disk format at fixed fixtures, real perf wins on three lib-mode lanes (on the C target only) — is what's worth looking at. I'm not claiming this beats SQLite. I'm claiming the methodology produces something that competes on its own turf in measurable, reproducible ways, on **specific targets**, and the gaps are concrete and listed.

---

## What's not proven, listed honestly

- **leap-rust is the bench laggard, not the bench leader.** Linux native L3/L4: 0.80× and 0.82× of mainline. Today's in-place B-tree commit-path rewrite (~45× speedup on Mac on the COMMIT phase alone) is fresh and not yet re-benched on Linux; even with the expected delta it is not obvious leap-rust will close the gap to mainline. Until measured, treat leap-rust as correctness-equivalent only.
- **leap-zig, leap-go, leap-python perf is not in the headline table.** Sibling-target perf benches exist but the structural-correctness numbers (sqllogictest, byte-identity) are the load-bearing claims for those targets, not perf parity with leap-c.
- **Peak RSS:** mainline is lighter than leap-c by ~1.5%. Not a win.
- **leap-rust loses all three perf lanes** (L2 0.67×, L3 0.80×, L4 0.82×). It is correctness-equivalent, not perf-equivalent. Today's in-place B-tree commit-path rewrite (~45× speedup on Mac on the COMMIT phase) is fresh and not yet re-benched on Linux; even with the expected delta it is not obvious leap-rust will close the gap to mainline.
- **Binary size apples-to-apples:** the 8.7× number includes mainline's CLI shell. An engine-only mainline build would shrink the gap substantially.
- **Linux validation** is on a single Ubuntu 22.04 box. Multi-distro CI is not yet wired.
- **Advanced modules (foreign keys, triggers, savepoints, FTS5, R-tree, virtual tables, encryption, WAL recovery)** are Rust-first behavioral-green; cross-target promotion is in progress. JSON1 is the only such module wired into all five targets today.
- **335-file Linux sqllogictest sample, not the full upstream corpus.** The full corpus is much larger.
- **Python sqllogictest denominator differs from the other targets** (~0.92M total records vs ~1.4–1.5M for the others) because the Python runner buckets more files as SKIP. The Python percentage is computed against its own smaller base, so target-to-target percentage comparisons aren't direct.
- **Two-fixture byte-identity, not random-shape byte-identity.**
- **Pin 19 in-place B-tree write is Rust-only today.** The four sibling targets (C/Zig/Go/Python) are at the v7-tx baseline for the storage commit path. Sibling regen for the new pager / page-cache / WAL-bridge / cursor-sig surface is dispatched in waves; Layer 1 (page-codec, the byte-encoder split) landed byte-identical across all 5 targets, but Layers 2–5 (page-cache, locking, WAL bytes, wal-bridge, cursor-sig migration, RowLocation, paged read paths) are still in flight as of this draft. Until that lands, "5-target storage parity" is **page-codec only**, not the full commit path.
- **Not a production drop-in.** Soak testing, fuzzing across diverse workloads, and ABI-compatibility audits are ongoing. Treat this as a compatibility-tier implementation, not a drop-in `sqlite3.so`.

---

## Reproduction

```bash
git clone <repo>
cd sqlite-leap

# Mac (arm64) — 5-target sqllogictest parity + on-disk byte-identity + Mac-only lanes
bash demo_5target_stunt.sh

# Linux x86_64 — the publishable bench numbers (in-process, library-mode)
bash bench/run-linux-libmode.sh

# Or via Docker
docker build -f bench/Dockerfile.linux-x86 -t sqlite-leap-bench .
docker run --rm -v "$PWD:/repo" sqlite-leap-bench bash bench/run-linux-libmode.sh
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
