# sqlite-leap

A SQLite-compatible database engine generated from a language-neutral specification, in **5 languages** — C, Rust, Zig, Go, Python — plus a WASM build via the Rust target.

Built using [LEAP](https://github.com/safitudo/leap) methodology: specs and tests are the product, code is generated output.

> **Headline (correctness, not perf).** All five language targets pass a 335-file Linux sample of the upstream sqllogictest corpus at 99.84–99.99% excl-SKIP (92.96–96.60% incl-SKIP; mainline 94.56% / 100% on the same denominators, source `tests/sqllogictest/results/corpus_2026_04_26_v33_linux/summary.md`); they emit byte-identical .db files at two fixed fixtures (270 and 5,000 row) that mainline reads cleanly.
>
> **Performance numbers temporarily withdrawn (2026-04-27).** A reviewer caught that the lib-mode bench harness silently runs leap in pure RAM while passing `--db PATH` to mainline (which honors it and runs WAL-fsynced). The L4 INSERT 1.81× claim was apples-to-vacuum and is retracted. The L3 SELECT 1.64× number shipped through the same harness and is held until a re-measurement covers all 5 leap targets × {parse, SELECT, INSERT} × {in-memory, file-backed} with both sides doing equivalent work.
>
> An earlier version of this README claimed 6/6 lane wins. That was wrong — see `docs/PUBLICATION.md` for the honest accounting and which lanes don't survive a strict comparison.

---

## What this project demonstrates

1. **One spec → 5 native engines.** Roughly 33K lines of language-neutral spec under `parts/` produce ~234K lines of buildable engine code across C, Rust, Zig, Go, Python — all behaviorally identical on the upstream sqllogictest corpus.

2. **One spec → mainline-byte-identical on-disk format at fixed fixtures.** Every target writes .db files with identical SHA1 to mainline at the 270-row and 5,000-row split fixtures. Mainline `PRAGMA integrity_check` passes on every leap-emitted file. (Random-shape byte-identity at scale is not yet claimed.)

3. **Performance bench — re-measurement in progress.** The previous lib-mode harness compared leap (running in pure RAM) against mainline (running WAL-fsynced against a real file), because leap-c/leap-rust silently drop the `--db PATH` flag the runner script passes. That asymmetry invalidates both the L3 and L4 numbers as published. The fix is in `parts/`: teach all five leap targets' lib_bench to honor `--db` (routing through `leap_storage_open_database_at` which already exists for the SLT runner), then re-run the full 5-target × 3-lane × 2-mode (in-memory + file-backed) matrix. Tracked as task #411.

   Mac-only lanes (L1 cold start, L5 binary size, L6 peak RSS) are unaffected by the lib-mode harness bug because they're process-spawn benches, not in-process. Their honest framings — L1 1.72× faster on Mac arm64, L5 8.7× smaller (apples-to-oranges in leap's favor: mainline includes CLI+readline+ICU), L6 leap is 1.5% heavier (loses) — are sourced from `bench/results/cold_start_5target/REPORT.md`, `bench/results/binary_size_5target/REPORT.md`, `bench/results/memory_footprint_5target/REPORT.md`. See `docs/PUBLICATION.md` for the full honest accounting.

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
