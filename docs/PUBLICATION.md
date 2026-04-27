# sqlite-leap: one spec → 5 SQLite engines, with honest numbers

**TL;DR.** I built a SQLite-compatible database engine from a language-neutral specification that produces buildable engines in **C, Rust, Zig, Go, and Python** — five at once, from one spec. The C target beats mainline SQLite on **two of the standard library-mode benchmark lanes** on real Linux x86_64 (SELECT 1.51×, INSERT 1.81×). All five targets pass a 186-file sample of the upstream sqllogictest corpus at 99.93–99.99% on a "no unsupported features" denominator. They emit `.db` files SHA1-identical to mainline at fixed-size fixtures (270 and 5,000 row) that pass `PRAGMA integrity_check`.

This is a methodology proof, not a SQLite replacement. The point is that **specs and tests can be the product, with code as commodity output**, and the result is competitive — on some lanes — with hand-written code from a 25-year-old project.

This post is deliberately honest about what doesn't beat mainline. An earlier draft over-claimed; what's below is what the files in the repo actually say.

---

## Library-mode benchmarks — Linux x86_64 native

Real Linux box (Ubuntu 22.04, 32 cores, glibc 2.35, rustc 1.89.0, gcc 11.4). Library-mode (in-process, no CLI startup bias). Same workload, same harness, both engines linked into the same `lib_bench` driver.

| Lane | leap-c | mainline | leap-c vs mainline |
|---|---:|---:|---:|
| L3 SELECT (in-memory) | 957 K q/s | 632 K q/s | **1.51× faster** |
| L4 INSERT (WAL) | 1.23 M ips | 678 K ips | **1.81× faster** |
| L2 parse (parse-only mode) | 1.86 M stmts/s | 1.06 M stmts/s | 1.75× faster — **see caveat below** |

L2 honest framing: in mainline's `parse-only` mode, mainline short-circuits ~60% of statements without doing schema-resolved parsing. On a **filtered corpus where both engines actually parse the statement**, mainline is **~160× faster** than leap-c on raw parse throughput (199,666 vs 1,236 qps). The "1.75×" line above is a real measurement of a real mode mainline ships, but it is not a fair comparison of parser engines — it is a comparison of two different work units. I'm including both numbers; the filtered comparison is the one a parser engineer would care about. Leap's tokenizer and Pratt parser are correct, not fast.

Raw CSV, run logs, hardware spec at `bench/results/2026-04-27-linux-native/`. Reproduce with `bash bench/run-linux-libmode.sh`.

## Mac arm64 benchmarks (different machine, different methodology)

These were measured on Mac arm64, not Linux. Treat as confirmatory, not the headline. Lane harnesses differ (process-spawn wallclock vs in-process throughput).

| Lane | leap-c | mainline | leap-c vs mainline | notes |
|---|---:|---:|---:|---|
| L1 cold start (`open` → first query) | 3.26 ms | 4.97 ms | **1.52× faster** | mainline = `sqlite3 :memory:` CLI shell |
| L5 binary size (engine-only smoke) | 203 KB | 1.77 MB | **8.7× smaller** | mainline number includes CLI shell + readline + ICU; apples-to-oranges in leap's favor |
| L6 peak RSS (CREATE + 1k INSERT + SELECT) | 3.05 MB | 3.01 MB | **0.98× — leap is slightly worse** | not "idle RSS"; short-lived-process peak only |

L5 caveat is load-bearing. The 8.7× number compares leap's pure-engine binary against mainline's CLI tool — mainline's engine-only library would be a fairer baseline and the gap would shrink substantially. I report what's measurable; I don't claim it's a fair fight.

L6 is **not a win**. Mainline has the lighter peak RSS in this measurement. The earlier draft of this post claimed otherwise — that was wrong.

---

## sqllogictest pass rates — 186-file sample

From `tests/sqllogictest/results/corpus_2026_04_27_post_T5/summary.md`:

| target | incl-SKIP | excl-SKIP |
|---|---:|---:|
| rust | 92.91% | 99.99% |
| c | 94.80% | 99.99% |
| zig | 94.35% | 99.93% |
| go | 94.78% | 99.98% |
| python | 92.44% | 99.99% |
| **sqlite (mainline)** | **92.47%** | **100.00%** |

Two honest framings, both in the table:

- **incl-SKIP** counts files where some statement was skipped due to unimplemented features (deferred BLOB literals, certain qualified-column refs, etc.) as a partial pass. Leap targets land 92–95%; mainline scores 92.47% on the same accounting (because the sample includes files mainline also doesn't fully execute on this harness).
- **excl-SKIP** drops SKIP rows from the denominator. On that denominator, leap targets land 99.93–99.99%, mainline 100%. This is the number worth quoting only if you also disclose it's an excl-SKIP number — which I am.

**Sample size:** 186 files per target, not the full upstream corpus (which is ~5M+ statements across thousands of files). The earlier draft said "passes the upstream corpus" — that overstated. It's a representative slice.

**Per-file timeout:** 60s. Files that hang are bucketed as DEFER; this favors leap relative to a no-timeout run.

---

## On-disk format byte-identity

Every leap target writes `.db` files with SHA1 identical to mainline at two fixed fixtures:

- 270-row split: SHA1 `b5f1f8978407...` × 5/5 targets.
- 5,000-row deep-split: SHA1 `fef632262aa2...` × 5/5 targets.

Mainline `PRAGMA integrity_check` returns `ok` on every leap-emitted file. Mainline can read leap-emitted files; leap can read mainline-emitted files.

This is real, but it's two fixtures. It's not a fuzz proof or a soak proof. Random-shape `.db` byte-identity at scale is not claimed.

---

## The methodology — LEAP

LEAP stands for *LLM Engineered Application Pattern*. The premise:

- **Tests** specify correctness. Human-authored. The most valuable artifact.
- **Schemas** are contracts. They *are* the architecture.
- **Specs** describe intent in language-neutral prose + records.
- **Code** is generated output. It lives in `src-*/`. It is gitignored.

When tests contradict specs, **tests win**. When specs contradict code, **specs win** — code gets regenerated.

For sqlite-leap specifically:

```
parts/                         # canonical spec, language-neutral
├── <component>/master.md      # prose + numbered correctness pins
├── <component>/shapes.json    # types/fns/records, language-neutral
└── targets/<lang>/mapping.md  # how language X realizes spec primitives

generators/                    # one per language target
src-<lang>/                    # GITIGNORED, regenerated
```

To add a feature: edit a `parts/` leaf. Re-emit per-target. Tests run. The five language trees move together.

The hardest discipline: specs must be **strictly language-neutral**. No `Result<T, E>`, no lifetimes, no `void*`, no `malloc`. If a Rust idiom or a C idiom leaks into the spec, the other targets break. This is the bar that makes the multi-target claim load-bearing.

---

## What's actually proven, soberly

1. **One spec → 5 native engines.** Roughly 10K lines of `parts/` produce ~140K lines of buildable engine code across 5 targets. All five execute the SQL surface of the 186-file SLT sample at 99.93–99.99% excl-SKIP / 92–95% incl-SKIP.
2. **One spec → byte-identical on-disk format at fixed fixtures.** Two fixtures, 5/5 targets, SHA1 match, integrity-check passes.
3. **One spec → competitive perf on 2 of the lanes I committed to.** L3 SELECT 1.51× and L4 INSERT 1.81× faster than mainline in lib-mode on Linux native x86_64. L1 cold-start is faster on Mac. L2 parse, L5 binary, L6 RSS comparisons each have caveats large enough that I won't claim them as straight wins.
4. **One spec → WASM build.** Via the Rust target's `wasm32-unknown-unknown`. 226 KB artifact, runs the SELECT-expression smoke under node.

The structural flex — same spec, five languages, byte-identical disk format at fixed fixtures, real perf wins on two lanes — is what's worth looking at. I'm not claiming this beats SQLite. I'm claiming the methodology produces something that competes on its own turf in measurable, reproducible ways, and the gaps are concrete and listed.

---

## What's not proven, listed honestly

- **L6 RSS:** mainline is lighter than leap-c by 1.5%. Not a win.
- **L2 parse on apples-to-apples corpus:** mainline is ~160× faster than leap-c. The published 1.75× number is in mainline's parse-only mode where mainline does less work.
- **L5 binary size apples-to-apples:** mainline's number includes the CLI shell. An engine-only mainline build would be much closer to leap-c.
- **leap-rust ~20% behind mainline on L3/L4** in lib-mode. leap-c is the bench leader; leap-rust is correctness-equivalent but slower.
- **Linux validation** is on a single Ubuntu 22.04 box. Multi-distro CI not yet wired.
- **Advanced modules (FK, triggers, savepoints, FTS5, R-tree, vtab, encryption, WAL recovery)** are Rust-first. JSON1 is the only module with full 5-target wire-in. Spec promotion of the rest to 5-target is in progress.
- **186-file SLT sample, not the full upstream corpus.** The full corpus is much larger.
- **Two-fixture byte-identity, not random-shape byte-identity.**
- **Not a production drop-in.** Soak testing, fuzzing across diverse workloads, and ABI compatibility audits are ongoing. Treat as a compatibility-tier implementation, not an `sqlite3.so` replacement.

---

## Reproduction

```bash
git clone <repo>
cd sqlite-leap

# Mac (arm64) — 5-target SLT parity + byte-identity + Mac-only lanes
bash demo_5target_stunt.sh

# Linux x86_64 — the publishable bench numbers (L2/L3/L4 lib-mode)
bash bench/run-linux-libmode.sh

# Or via Docker
docker build -f bench/Dockerfile.linux-x86 -t sqlite-leap-bench .
docker run --rm -v "$PWD:/repo" sqlite-leap-bench bash bench/run-linux-libmode.sh
```

Reference numbers from 2026-04-27 are at `bench/results/2026-04-27-linux-native/`.

---

## Why this matters beyond databases

If a spec-first methodology can produce a SQLite-compatible engine that wins **two** library-mode bench lanes against the canonical C implementation on real Linux hardware, that's a different question than "can LLMs write production code." It becomes "what's the right artifact for an LLM-engineered project?"

The answer this project argues for: the artifact is **spec + tests**. Code is build output. Multi-language is structurally available once the spec is neutral. Performance on individual lanes is a function of the generator and the mapping file, not the language choice — and on the lanes where leap-c wins, the wins are reproducible and measured.

I'm not claiming this scales to every project. I'm claiming it scales to *this* one, with the caveats above attached, and that's still a project most people would have called impossible to spec-generate.

---

## Acknowledgements

SQLite by D. Richard Hipp et al. — the canonical implementation and the published file-format / SQL specifications this project targets for compatibility. The source code of mainline SQLite was off-limits during generation; only the published file-format documentation (sqlite.org/fileformat2.html) and SQL standard were referenced.

Turso / Limbo, sql.js, and rusqlite for setting the perf bar that made this exercise interesting.

A critical reviewer caught the original draft of this post inflating the headline table with Mac numbers labeled as Linux, fabricated values for L1/L5/L6, and an inverted L6 result. The version above is the corrected one. The exercise of having the marketing fail a sanity check against the repo's own files was the most useful thing that happened this week.

---

*Repo: <link>. Methodology: github.com/safitudo/leap. Reach me at stan@aleph1.io.*
