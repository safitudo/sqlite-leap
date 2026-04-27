# sqlite-leap: one spec → 5 SQLite engines, with honest numbers

**TL;DR.** I built a SQLite-compatible database engine from a single language-neutral specification that produces buildable engines in **C, Rust, Zig, Go, and Python** — five at once, from one spec. All five pass a 335-file Linux sample of the upstream `sqllogictest` corpus at 99.84–99.99% on a strict denominator. They write `.db` files that are byte-for-byte identical to mainline at two fixed-size fixtures and that mainline reads cleanly.

**Performance numbers are temporarily withdrawn.** A reviewer caught that the lib-mode bench harness silently runs leap in pure RAM while passing `--db PATH` to mainline (which honors it and runs WAL-fsynced). The L4 INSERT 1.81× win was apples-to-vacuum and is retracted. The L3 SELECT 1.64× number is read-only-after-setup and less affected, but it shipped through the same harness and gets the same treatment until both sides do equivalent work. A re-measurement across all 5 targets × {parse, SELECT, INSERT} × {in-memory, file-backed} is in progress.

This is a methodology proof, not a SQLite replacement. The point is that **specs and tests can be the product, with code as commodity output** — and the result is competitive, on some axes, with hand-written code from a 25-year-old project.

This post is deliberately honest about what *doesn't* beat mainline. An earlier draft over-claimed; the version below is what the files in the repo actually say.

---

## Library-mode benchmarks — withdrawn pending re-measurement

The previous draft of this post claimed in-process wins on Linux x86_64: L3 SELECT 1.64× faster than mainline and L4 INSERT 1.81× faster. A reviewer caught a real harness asymmetry that invalidates both:

- `bench/run-linux-libmode.sh` invokes both engines as `<lib_bench> <workload.sql> --time-setup --db /tmp/X.<target>`.
- mainline's `bench/baselines/sqlite_lib_bench.c` parses `--db PATH` and calls `sqlite3_open(db_path, &db)` against a real file.
- leap-c's `src-c/examples/lib_bench.c:577-581` only parses `--time-setup`. The `--db` argument is silently dropped, and `catalog_init()` calls `leap_storage_database_new()` — pure in-memory.
- The L4 workload begins with `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;`. Mainline honors those (real WAL, real fsync at COMMIT). leap classifies PRAGMA as STMT_NOOP and skips them.

So the L4 1.81× was leap-in-RAM versus mainline-WAL-fsynced-to-disk. The L3 SELECT comparison is read-only after setup and less affected (both engines reading from RAM at measurement time), but it shipped through the same harness and gets the same treatment until both sides do equivalent work.

**The fix in flight:**

1. Teach leap-c, leap-rust, leap-zig, leap-go, leap-python lib_bench to honor `--db PATH` (route through `leap_storage_open_database_at` — already exists at `src-c/storage/fileformat_lib.c:886` and the SLT runner uses it). Implement `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` as real WAL switches in lib mode, not noops.
2. Re-run on Linux x86_64. Publish the full matrix — 5 leap targets + mainline × {parse, SELECT, INSERT} × {in-memory, file-backed} = 36 cells. Every cell traces to a CSV row that names the binary and the mode.
3. Whatever survives, survives. If file-backed L4 is a leap loss, it gets published as a leap loss.

This is the third bench-table withdrawal in three drafts. Two earlier drafts shipped fabricated or asymmetric numbers; this one is the asymmetric harness. Until the matrix is filled, **the only quantitative perf claim worth citing in this post is L1 cold start on Mac arm64**, because it's a process-spawn bench, doesn't go through lib_bench, and doesn't depend on `--db` honoring. Everything else is on hold.

## Mac arm64 benchmarks (different machine, different methodology)

These were measured on Mac arm64, not Linux. Treat as confirmatory, not headline. The lane harnesses also differ — these are process-spawn wallclock measurements, not in-process throughput.

Source files: `bench/results/cold_start_5target/REPORT.md`, `bench/results/binary_size_5target/REPORT.md`, `bench/results/memory_footprint_5target/REPORT.md`.

| Lane | leap-c | mainline | leap-c vs mainline | notes |
|---|---:|---:|---:|---|
| Cold start (`open` → first query ready) | 3.28 ms | 5.65 ms | **1.72× faster** | median over 11 samples; mainline = `sqlite3 :memory:` CLI |
| Binary size (engine-only smoke) | 203 KB | 1767 KB | **8.7× smaller** | mainline number includes CLI shell + readline + ICU; an engine-only mainline build would close most of the gap |
| Peak RSS (`CREATE` + 1k `INSERT` + `SELECT`) | 3.05 MB | 3.01 MB | **0.98× — leap is slightly worse** | not "idle RSS"; short-lived-process peak |

The binary-size caveat is load-bearing. The 8.7× figure compares leap's pure-engine binary against mainline's CLI tool — a fair fight against an engine-only mainline build would shrink the gap substantially. I report what's measurable, but I don't claim it's apples-to-apples.

The peak-RSS row **is not a win**. Mainline is lighter on this measurement. An earlier draft of this post claimed the opposite, which was wrong.

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

- **incl-SKIP** counts files where some statement was skipped due to an unimplemented feature (deferred BLOB literals, certain qualified-column refs, etc.) as a partial pass. Leap targets land at 92.96–96.60% on this accounting; mainline lands at 94.56% on the same sample (because the sample includes files mainline also doesn't fully execute on this harness's strict comparison).
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
2. **One spec → byte-identical on-disk format at fixed fixtures.** Two fixtures, 5/5 targets, SHA1 match, mainline integrity-check passes.
3. **One Mac-only perf win that doesn't go through the broken harness.** Cold start on Mac arm64 is 1.72× faster than mainline (CSV: `bench/results/cold_start_5target/REPORT.md`). Linux validation pending. Lib-mode SELECT/INSERT/parse numbers are withdrawn until the harness is fixed (see §"Library-mode benchmarks — withdrawn pending re-measurement"). Binary size is 8.7× smaller but the comparison is leap-engine vs mainline-CLI-with-readline-and-ICU, so it's apples-to-oranges in leap's favor; an engine-only mainline build would close most of the gap. Peak RSS leap loses by 1.5%.
4. **One spec → WASM build.** Via the Rust target's `wasm32-unknown-unknown`. The artifact is around 226 KB and runs the SELECT-expression smoke under Node.

The structural flex — same spec, five languages, byte-identical disk format at fixed fixtures, real perf wins on two lanes — is what's worth looking at. I'm not claiming this beats SQLite. I'm claiming the methodology produces something that competes on its own turf in measurable, reproducible ways, and the gaps are concrete and listed.

---

## What's not proven, listed honestly

- **24-hour reversal.** A day before this post, leap was losing every numerical lane. The wins above are recent and depend on a small set of concrete changes. They have not been independently re-verified on a second machine yet.
- **Peak RSS:** mainline is lighter than leap-c by ~1.5%. Not a win.
- **Parse throughput on apples-to-apples corpus:** mainline is roughly 160× faster than leap-c. The published 1.75× ratio is in mainline's parse-only mode, where mainline is doing less work.
- **Binary size apples-to-apples:** the 8.7× number includes mainline's CLI shell. An engine-only mainline build would shrink the gap substantially.
- **leap-rust is ~20% behind mainline on SELECT and INSERT** in lib-mode. leap-c is the bench leader; leap-rust is correctness-equivalent but slower.
- **Linux validation** is on a single Ubuntu 22.04 box. Multi-distro CI is not yet wired.
- **Advanced modules (foreign keys, triggers, savepoints, FTS5, R-tree, virtual tables, encryption, WAL recovery)** are Rust-first. JSON1 is the only module wired into all five targets. Spec promotion of the rest is in progress.
- **335-file Linux sqllogictest sample, not the full upstream corpus.** The full corpus is much larger.
- **Python sqllogictest denominator differs from the other targets** (~0.92M total records vs ~1.4–1.5M for the others) because the Python runner buckets more files as SKIP. The Python percentage is computed against its own smaller base, so target-to-target percentage comparisons aren't direct.
- **Two-fixture byte-identity, not random-shape byte-identity.**
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

The bench script writes a CSV into `bench/results/` along with a run log naming the exact compiler and toolchain versions used. The published numbers in this post correspond to one such run; the directory in the repo holds the raw data.

---

## Why this matters beyond databases

If a spec-first methodology can produce a SQLite-compatible engine that wins two library-mode bench lanes against the canonical C implementation on real Linux hardware, that's a different question than "can LLMs write production code." It becomes "what's the right artifact for an LLM-engineered project?"

The answer this project argues for: the artifact is **spec plus tests**. Code is build output. Multi-language is structurally available once the spec is neutral. Performance on individual lanes is a function of the generator and the per-target mapping file, not the language choice — and on the lanes where leap-c wins, the wins are reproducible and measured.

I'm not claiming this scales to every project. I'm claiming it scales to *this* one, with the caveats above attached, and that's still a project most people would have called impossible to spec-generate.

---

## Acknowledgements

SQLite by D. Richard Hipp et al. — the canonical implementation and the published file-format / SQL specifications this project targets for compatibility. The source code of mainline SQLite was off-limits during generation; only the published file-format documentation and SQL standards were referenced.

Turso / Limbo, sql.js, and rusqlite for setting the perf bar that made this exercise interesting.

A critical reviewer caught an earlier draft of this post inflating the headline table with Mac numbers labeled as Linux, fabricated values for cold-start, binary size, and peak RSS, and an inverted RSS comparison. The version above is the corrected one. The exercise of having the marketing fail a sanity check against the repo's own files was the most useful thing that happened this week.

---

*Repo: <link>. Methodology: github.com/safitudo/leap. Reach me at stan@aleph1.io.*
