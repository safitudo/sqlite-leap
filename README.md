# sqlite-leap

A SQLite-compatible database engine generated from a language-neutral specification, in **5 languages** — C, Rust, Zig, Go, Python — plus a WASM build via the Rust target.

Built using [LEAP](https://github.com/safitudo/leap) methodology: specs and tests are the product, code is generated output.

> **Headline:** the C build beats mainline SQLite on **L3 in-memory SELECT (1.51× faster)** in lib-mode on real Linux x86_64. L4 INSERT measures 1.81× but is **not currently claimed** because leap's bench harness skips BEGIN/COMMIT/ROLLBACK while mainline runs the transaction bytecode (see `docs/POST-PUBLICATION-ROADMAP.md` P0.2). All five language targets pass a 186-file sample of the upstream sqllogictest corpus at 99.93–99.99% excl-SKIP (92–95% incl-SKIP; mainline 92.47% / 100% on the same denominators); they emit byte-identical .db files at two fixed fixtures (270 and 5,000 row) that mainline reads cleanly.
>
> An earlier version of this README claimed 6/6 lane wins. That was wrong — see `docs/PUBLICATION.md` for the honest accounting and which lanes don't survive a strict comparison.

---

## What this project demonstrates

1. **One spec → 5 native engines.** Roughly 10K lines of `parts/` produce ~140K lines of buildable engine code across C, Rust, Zig, Go, Python — all behaviorally identical on the upstream sqllogictest corpus.

2. **One spec → mainline-byte-identical on-disk format at fixed fixtures.** Every target writes .db files with identical SHA1 to mainline at the 270-row and 5,000-row split fixtures. Mainline `PRAGMA integrity_check` passes on every leap-emitted file. (Random-shape byte-identity at scale is not yet claimed.)

3. **One spec → 1 currently-claimable lib-mode bench win.** Real Linux x86_64 (Ubuntu 22.04, rustc 1.89, gcc 11.4), library-mode, in-process, both engines linked into the same `lib_bench` driver:

   | Lane | leap-c | mainline | leap-c vs mainline | claim status |
   |---|---:|---:|---:|---|
   | L3 SELECT (in-memory) | 957K q/s | 632K q/s | **1.51× faster** | claimed; PK-detection is spec-emitted (commit 770ceda) |
   | L4 INSERT | (pre-fix 1.23M ips) | (pre-fix 678K ips) | (pre-fix 1.81× ratio) | **WITHDRAWN** — asymmetry was closed in commit 677ff68 (mem-store v7-tx adds real BEGIN/COMMIT). Mac arm64 post-fix shows leap-c 0.84× (loses). Linux x86_64 re-measurement pending; the original 1.81× was the asymmetry, not the engine. |

   The remaining lanes have caveats large enough they can't be claimed as straight wins:

   - **L2 parse**: in mainline's `parse-only` mode (which short-circuits ~60% of statements without resolving schema), leap-c posts 1.86M stmts/s vs 1.06M (1.75× "faster"). On a **filtered corpus where both engines parse the same statements**, mainline is **~160× faster** than leap-c. Leap's parser is correct, not fast.
   - **L1 cold start (Mac arm64 only)**: leap-c 3.26 ms vs mainline `sqlite3 :memory:` CLI 4.97 ms = 1.52× faster. Linux validation pending.
   - **L5 binary size (Mac arm64 only)**: leap-c engine smoke 203 KB vs mainline `sqlite3` CLI 1.77 MB = 8.7× smaller, but mainline's binary includes the CLI shell + readline + ICU; an engine-only mainline build would close most of this gap.
   - **L6 RSS (Mac arm64 only)**: leap-c 3.05 MB vs mainline 3.01 MB — **mainline is slightly lighter, not leap.** Not a win.

   See `docs/PUBLICATION.md` for the full honest accounting.

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
