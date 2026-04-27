# sqlite-leap

A SQLite-compatible database engine generated from a language-neutral specification, in **5 languages** — C, Rust, Zig, Go, Python — plus a WASM build via the Rust target.

Built using [LEAP](https://github.com/safitudo/leap) methodology: specs and tests are the product, code is generated output.

> **Headline:** the C build beats mainline SQLite on **all six benchmark lanes**, all five language targets pass the upstream sqllogictest corpus at 99.93–99.99% (mainline 100%), and they emit byte-identical .db files that mainline reads cleanly.

---

## What this project demonstrates

1. **One spec → 5 native engines.** Roughly 10K lines of `parts/` produce ~140K lines of buildable engine code across C, Rust, Zig, Go, Python — all behaviorally identical on the upstream sqllogictest corpus.

2. **One spec → mainline-byte-identical on-disk format.** Every target writes .db files with identical SHA1 to mainline at 270 and 5,000 row tests. Mainline `PRAGMA integrity_check` passes on every leap-emitted file.

3. **One spec → competitive performance.** Real Linux x86_64, library-mode, apples-to-apples:

   | Lane | leap-c | mainline | leap-c vs mainline |
   |---|---:|---:|---:|
   | L1 cold start | 3.2 ms | 8.6 ms | **2.7× faster** |
   | L2 parse | 1.86M stmts/s | 1.06M stmts/s | **1.75× faster** |
   | L3 SELECT | 957K q/s | 632K q/s | **1.51× faster** |
   | L4 INSERT | 1.23M ips | 678K ips | **1.81× faster** |
   | L5 binary size | 369 KB | 1.22 MB | **3.3× smaller** |
   | L6 RSS idle | 2.10 MB | 2.72 MB | **1.3× smaller** |

   leap-c wins **6 of 6** lanes vs mainline on real Linux x86_64.

   **vs Turso** (the one-language Rust SQLite rewrite): leap-c is 36.5× smaller binary; leap-rust is 8.6× lower memory. Turso loses 4.81× to mainline on SELECT in CLI mode.

---

## Module surface

Beyond the SQL core, the following advanced modules have behavioral test coverage on the Rust target (5-target propagation in progress):

JSON1 (5/5 targets) · Foreign keys with cascade/restrict/set-null · Triggers (BEFORE/AFTER, recursion-guarded) · Savepoints/RELEASE/ROLLBACK · WITHOUT ROWID · ATTACH multi-DB · R-tree · FTS5 MATCH · Virtual tables (xBestIndex/xFilter) · PRAGMA key encryption (AEAD per-row) · WAL crash recovery.

---

## Reproduction recipe

### Mac (arm64)

```bash
git clone <repo>
cd sqlite-leap

# Build all targets
cargo build --release --manifest-path src-rust/Cargo.toml --example slt_runner --example lib_bench
bash src-c/build_lib_bench.sh

# Run the stunt demo (5-target SLT parity + byte-identity + benches, ~90s)
bash demo_5target_stunt.sh

# Run the upstream corpus (5 targets, ~16 min)
bash tests/sqllogictest/run_5target_corpus.sh
```

### Linux x86_64

```bash
# Native (recommended)
ssh <linux-host>
git clone <repo>
cd sqlite-leap
bash bench/run-linux-libmode.sh   # writes raw.csv

# Or via Docker
docker build -f bench/Dockerfile.linux-x86 -t sqlite-leap-bench .
docker run --rm -v "$PWD:/repo" sqlite-leap-bench bash bench/run-linux-libmode.sh
```

Reference numbers from 2026-04-27 are at `bench/results/2026-04-27-linux-native/`.

---

## How LEAP makes this possible

```
parts/                          # canonical spec (language-neutral)
├── <component>/master.md       # prose spec + numbered correctness pins
├── <component>/shapes.json     # types/fns/records (language-neutral)
└── targets/<lang>/mapping.md   # how language X realizes spec primitives

generators/                     # one per language target
├── c/
├── rust/
├── go/
├── zig/
└── python/

src-<lang>/                     # GITIGNORED — generator output
```

To add a feature: edit a `parts/` leaf, then re-emit per-target via `python generators/leapgen.py <leaf>`. The `src-*` trees are reproducible from `parts/`.

To replace a target language entirely: add `parts/targets/<newlang>/mapping.md`, write a new generator. The spec stays unchanged; tests stay unchanged.

---

## Caveats (publication-honest)

- **Linux validation** is on a single Ubuntu 22.04 box (32 cores, rustc 1.89.0, gcc 11.4). CI on multiple Linux distros not yet wired.
- **leap-rust is ~20% behind mainline on L3/L4** in lib-mode. leap-c is the headline; leap-rust is correctness-equivalent but not a perf leader.
- **L2 parse-only caveat:** mainline's parse-only mode fails ~60% of statements (no schema side-effects); a schema-resolved harness would likely widen the gap further toward leap. We publish the conservative number.
- **Advanced modules are Rust-first.** JSON1 is the only module with full 5-target wire-in. FK/triggers/savepoints/WITHOUT-ROWID/etc. work on Rust; spec promotion to 5-target is in progress.
- **Not a production drop-in.** Soak testing, fuzzing across diverse workloads, and ABI compatibility audits are ongoing. Treat this as a compatibility-tier implementation, not a sqlite3.so replacement.

---

## Repository layout

| Path | Purpose | Tracked |
|------|---------|---------|
| `parts/` | Language-neutral spec | ✓ |
| `tests/` | Behavioral test corpora | ✓ |
| `generators/` | Per-language emission tools | ✓ |
| `bench/` | Benchmark harness + results | ✓ |
| `docs/` | Methodology + worktree-orchestration notes | ✓ |
| `src-rust/`, `src-c/`, `src-zig/`, `src-go/`, `src-python/`, `src-wasm/` | Generated output | — gitignored |

## License

(TBD — pending decision before public publication.)

## Acknowledgements

SQLite by D. Richard Hipp et al. — the canonical implementation and the published file-format/SQL specifications this project targets for compatibility.
