# sqlite-leap: one spec → 5 SQLite engines, with honest numbers

**TL;DR.** I built a SQLite-compatible database engine from a single language-neutral specification that produces buildable engines in **C, Rust, Zig, Go, and Python** — five at once, from one spec. On real Linux x86_64, library-mode (in-process), the C target beats mainline SQLite on **in-memory SELECT throughput (1.64× faster)** and **INSERT throughput (1.81× faster)**, with both engines doing equivalent work in the bench harness. All five targets pass a 186-file sample of the upstream `sqllogictest` corpus at 99.93–99.99% on a strict denominator. They write `.db` files that are byte-for-byte identical to mainline at two fixed-size fixtures and that mainline reads cleanly.

This is a methodology proof, not a SQLite replacement. The point is that **specs and tests can be the product, with code as commodity output** — and the result is competitive, on some axes, with hand-written code from a 25-year-old project.

This post is deliberately honest about what *doesn't* beat mainline. An earlier draft over-claimed; the version below is what the files in the repo actually say.

---

## Library-mode benchmarks — Linux x86_64 native

Hardware: Ubuntu 22.04, 32 cores, glibc 2.35, rustc 1.89.0, gcc 11.4. Library-mode means both engines are linked into the same in-process driver and run the same workload — no CLI startup overhead, no shell parsing, no subprocess noise.

| Lane | leap-c | mainline | leap-c vs mainline | claim |
|---|---:|---:|---:|---|
| In-memory SELECT | 949 K queries/s | 580 K queries/s | **1.64× faster** | claimed |
| INSERT throughput | 1.21 M inserts/s | 669 K inserts/s | **1.81× faster** | claimed |
| Parse throughput (parse-only mode) | 1.86 M stmts/s | 1.06 M stmts/s | 1.75× ratio | **not claimed** — see below |

Both engines run the same statements in both lanes. The SELECT lane uses a primary-key lookup pattern; the INSERT lane runs in batches wrapped by `BEGIN`/`COMMIT`. Both engines execute the transaction machinery on every batch — there is no "leap skips the transaction work" asymmetry.

**On the parse lane, the 1.75× number is misleading.** Mainline has a `parse-only` mode that short-circuits roughly 60% of statements without resolving schema. On a filtered corpus where both engines actually parse the statement, mainline is roughly **160× faster** than leap-c on raw parse throughput. The 1.75× line is a real measurement of a real mode mainline ships, but it's not a fair parser-vs-parser comparison. Leap's tokenizer and Pratt parser are correct, not fast. I'm publishing the conservative interpretation: parse is not a leap win.

Raw CSV, run logs, and hardware specs are committed under `bench/results/`. To reproduce on a Linux x86_64 box, clone the repo and run `bash bench/run-linux-libmode.sh`.

## How fragile are these numbers?

Twenty-four hours before this post was drafted, leap was *losing every bench lane* — by 28× on parse, 200× on SELECT, 16× on INSERT. The end-of-day report from the day before names the structural reasons: no primary-key index in the in-memory store, a naive VDBE INSERT path that capped at ~40K inserts/s, and parser cold-cache effects.

The swing came from three concrete changes:

1. **SELECT got 200× faster** because the in-memory store now installs a primary-key index automatically when a `CREATE TABLE` declares an `INTEGER PRIMARY KEY` column. This detection is described in the spec — not hand-tuned in the harness — and every language target inherits it.
2. **INSERT got 16× faster** from a combination of a prepared-statement cache and a leaner row-write path. The earlier version of this post flagged that the leap bench harness was treating `BEGIN`/`COMMIT`/`ROLLBACK` as no-ops while mainline ran the full transaction machinery — that asymmetry is now closed. Leap implements those statements as real snapshot-frame transactions on both the C and Rust targets, the bench harness exercises them, and mainline's bytecode runs as before. Both engines do equivalent transaction work per batch.
3. **Parse changed what it measured.** The earlier "leap loses parse 28×" was a different bench mode (full parse + compile + plan). The new "1.75×" is a parse-only comparison. Both are valid; the headline does *not* claim a parse win.

I'm leaving the wins above the fold because they're reproducible — anyone with a Linux x86_64 box can clone the repo, run one shell script, and regenerate the table. Independent re-verification on a second Linux machine is on the to-do list and will land before any number gets cited beyond this post.

## Mac arm64 benchmarks (different machine, different methodology)

These were measured on Mac arm64, not Linux. Treat as confirmatory, not headline. The lane harnesses also differ — these are process-spawn wallclock measurements, not in-process throughput.

| Lane | leap-c | mainline | leap-c vs mainline | notes |
|---|---:|---:|---:|---|
| Cold start (`open` → first query ready) | 3.26 ms | 4.97 ms | **1.52× faster** | mainline = `sqlite3 :memory:` CLI |
| Binary size (engine-only smoke) | 203 KB | 1.77 MB | **8.7× smaller** | mainline number includes CLI shell + readline + ICU; an engine-only mainline build would close most of the gap |
| Peak RSS (`CREATE` + 1k `INSERT` + `SELECT`) | 3.05 MB | 3.01 MB | **0.98× — leap is slightly worse** | not "idle RSS"; short-lived-process peak |

The binary-size caveat is load-bearing. The 8.7× figure compares leap's pure-engine binary against mainline's CLI tool — a fair fight against an engine-only mainline build would shrink the gap substantially. I report what's measurable, but I don't claim it's apples-to-apples.

The peak-RSS row **is not a win**. Mainline is lighter on this measurement. An earlier draft of this post claimed the opposite, which was wrong.

The cold-start row is a clean win on Mac arm64; Linux validation of cold-start is on the to-do list.

---

## sqllogictest pass rates — 186-file sample

| Target | incl-SKIP | excl-SKIP |
|---|---:|---:|
| rust | 92.91% | 99.99% |
| c | 94.80% | 99.99% |
| zig | 94.35% | 99.93% |
| go | 94.78% | 99.98% |
| python | 92.44% | 99.99% |
| **mainline sqlite** | **92.47%** | **100.00%** |

Two denominators, both honest:

- **incl-SKIP** counts files where some statement was skipped due to an unimplemented feature (deferred BLOB literals, certain qualified-column refs, etc.) as a partial pass. Leap targets land at 92–95% on this accounting; mainline lands at 92.47% on the same sample (because the sample includes files mainline also doesn't fully execute on this harness's strict comparison).
- **excl-SKIP** drops SKIP rows from the denominator. On that denominator, leap targets land at 99.93–99.99% and mainline at 100%. This is the number worth quoting only if you also disclose it's an excl-SKIP number — which I am.

**Sample size:** 186 files per target, not the full upstream corpus (which is ~5M+ statements across thousands of files). An earlier draft said "passes the upstream corpus." That overstated. It's a representative slice, and a full-corpus run will probably produce lower rates and surface buckets the sample missed. That run is also on the to-do list.

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

1. **One spec → 5 native engines.** Roughly 29K lines of language-neutral spec produce ~233K lines of buildable engine code across C, Rust, Zig, Go, and Python. All five execute the SQL surface of the 186-file sqllogictest sample at 99.93–99.99% on the strict denominator.
2. **One spec → byte-identical on-disk format at fixed fixtures.** Two fixtures, 5/5 targets, SHA1 match, mainline integrity-check passes.
3. **One spec → competitive perf on two of the lanes I committed to.** On Linux x86_64 in-process, leap-c is 1.64× faster than mainline on in-memory SELECT and 1.81× faster on INSERT. Cold start is faster on Mac. The remaining lanes (parse throughput, binary size, peak RSS) each have caveats large enough that I don't claim them as straight wins.
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
- **186-file sqllogictest sample, not the full upstream corpus.** The full corpus is much larger.
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
