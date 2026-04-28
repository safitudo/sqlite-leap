# sqlite-leap

A SQLite-compatible database engine generated from a language-neutral specification, in **5 languages** — C, Rust, Zig, Go, Python — plus a WASM build via the Rust target.

Built using [LEAP](https://github.com/safitudo/leap) methodology: specs and tests are the product, code is generated output.

> **Headline (correctness, not perf).** All five language targets pass a 335-file Linux sample of the upstream sqllogictest corpus at 99.84–99.99% excl-SKIP (92.96–96.60% incl-SKIP; mainline 94.56% / 100% on the same denominators, source `tests/sqllogictest/results/corpus_2026_04_26_v33_linux/summary.md`); they emit byte-identical .db files at two fixed fixtures (270 and 5,000 row) that mainline reads cleanly.
>
> **Linux native lib-mode bench (2026-04-27): leap-c wins all three perf lanes vs mainline.** L2 parse 1.75×, L3 SELECT 1.51×, L4 INSERT 1.81×. **leap-rust loses all three** (0.67× / 0.80× / 0.82×) — it is correctness-equivalent, not perf-equivalent. CSVs at `bench/results/2026-04-27-linux-native/lane2-parseonly/raw.csv` and `bench/results/2026-04-27-linux-native/raw.csv`. Mac-only lanes (cold start 1.72× win, binary size 8.7× smaller — caveat: mainline number includes CLI shell, peak RSS leap loses 1.5%) are sourced from `bench/results/{cold_start,binary_size,memory_footprint}_5target/REPORT.md`.
>
> Earlier drafts of this README claimed 6/6 lane wins, then withdrew them, then mis-cited L2 as a 100× loss. The current numbers are the apples-to-apples lib-mode results — see `docs/PUBLICATION.md` for caveats and per-lane methodology.

---

## What this project demonstrates

1. **One spec → 5 native engines.** Roughly 33K lines of language-neutral spec under `parts/` produce ~234K lines of buildable engine code across C, Rust, Zig, Go, Python — all behaviorally identical on the upstream sqllogictest corpus.

2. **One spec → mainline-byte-identical on-disk format at fixed fixtures.** Every target writes .db files with identical SHA1 to mainline at the 270-row and 5,000-row split fixtures. Mainline `PRAGMA integrity_check` passes on every leap-emitted file. (Random-shape byte-identity at scale is not yet claimed.)

3. **Performance bench — leap-c wins three lib-mode lanes on Linux x86_64.** Linux native (Ubuntu 22.04, rustc 1.89, gcc 11.4) library-mode harness, both engines invoked symmetrically (`--parse-only` for L2; in-memory L3; `--db PATH` honored on both sides for L4):

   | Lane | mainline | leap-rust | leap-c | leap-c vs mainline |
   |---|---:|---:|---:|---:|
   | L2 parse-only filtered (stmt/s) | 1,060,065 | 710,430 | 1,857,806 | **1.75× win** |
   | L3 SELECT in-memory (sel/s) | 631,752 | 505,008 | 956,662 | **1.51× win** |
   | L4 INSERT file-backed (ins/s) | 678,258 | 555,862 | 1,228,876 | **1.81× win** |

   leap-rust loses all three at 67–82% of mainline. Mac-only lanes (L1 cold start, L5 binary size, L6 peak RSS) are process-spawn benches: L1 1.72× faster on Mac arm64, L5 8.7× smaller (apples-to-oranges in leap's favor: mainline includes CLI+readline+ICU), L6 leap is 1.5% heavier (loses). See `docs/PUBLICATION.md` for the full honest accounting and per-lane caveats.

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
- **leap-rust loses all three Linux lib-mode perf lanes** (L2 0.67×, L3 0.80×, L4 0.82× of mainline). leap-c is the headline; leap-rust is correctness-equivalent but not a perf leader.
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
