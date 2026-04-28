# sqlite-leap

A research artifact: how far can a language-neutral specification carry SQLite compatibility across multiple target languages? Five engines (**C, Rust, Zig, Go, Python**) plus a WASM build are maintained against the same prose specs in `parts/`. They are evaluated against mainline SQLite for behavior, on-disk format, and process-level metrics.

Built using [LEAP](https://github.com/safitudo/leap) methodology: tests and specs are the load-bearing artifacts; engine source is regenerable from `parts/` (caveats below).

> **The question this project answers**
>
> Not "does it beat SQLite" — it doesn't, on most measures, and where it does the comparison usually has a caveat. The interesting question is *how far* a single neutral spec carries you. This repo says: far enough that five hand-emitted engines agree byte-for-byte with mainline at fixed `.db` fixtures, run the same SQL surface to within ≤0.16 percentage points of mainline on a 335-file sqllogictest sample, and ship as 207 KB (C) to 4.6 MB (Go) binaries.

**Single source of truth for every published number:** [`bench/PUBLISHED.md`](bench/PUBLISHED.md). Each claim cites the CSV path and date. The TL;DR below is a digest of that file; if the two ever disagree, `PUBLISHED.md` wins.

---

## What's load-bearing today

1. **Cross-target byte-identity at fixed fixtures.** All 5 leap targets and mainline SQLite produce SHA1-identical `.db` files at a 270-row split fixture and a 5,000-row deep-split fixture. Mainline `PRAGMA integrity_check` returns `ok` on every leap-emitted file. (Two fixtures, not random-shape fuzz.)

2. **sqllogictest parity on the full 622-file upstream corpus, Linux x86_64 native — with denominator asymmetry disclosed.** All 5 leap targets pass **99.56–99.98% excl-SKIP** on the records they attempt; mainline runs the full corpus at **99.9997%**. **The denominators differ by target**, because each target's runner buckets a different fraction of the corpus as SKIP: leap-python attempts 96.6% of mainline's records, leap-rust 89.5%, leap-zig 76.5%, leap-go 74.0%, **leap-c only 63.7%**. So leap-c's 99.56% is on a 36% smaller corpus than mainline's, not on the same corpus. The "0.44pp behind mainline" framing must be read with the `exec/mainline` column. Source: `tests/sqllogictest/results/corpus_2026_04_28_full/summary.json`. Per-target detail in [`bench/PUBLISHED.md` §A.1](bench/PUBLISHED.md). Crashes are disclosed: leap-c 88 (planner-perf cluster in `random/index/*` and `random/groupby/*`), leap-python 17, leap-zig 11; leap-rust and leap-go 0; mainline 1.

3. **Three builds from the Rust target.** Native, cross-compiled, and `wasm32-unknown-unknown` (231 KB). The WASM smoke runs SELECT-expression cases under Node.

4. **One survivable Linux lib-mode perf signal.** leap-c parses a filtered 65,653-statement corpus 1.75× faster than mainline (lane-2-parseonly). Lane is parse-only and does not open a database, so the harness asymmetry that broke L3/L4 (below) does not apply here. Source: `bench/results/2026-04-27-linux-native/lane2-parseonly/raw.csv`.

5. **Process-level metrics, not engine-vs-engine.** L1 cold start: leap-c/rust/zig 4–17× faster than mainline `sqlite3` on Mac and Linux. L5 binary size: leap-c at 207 KB (Mac) / 512 KB (Linux) vs mainline `sqlite3` CLI at 1.22 MB — apples-to-oranges; the mainline number includes the CLI shell + readline + ICU. L6 RSS is run-to-run noisy and the latest demo run shows leap-c at 0.98× mainline (i.e., loses by 2%); we no longer publish a fixed L6 win claim. Sources: `bench/results/{cold_start,binary_size,memory_footprint}_5target/REPORT.md`.

## What we don't claim

- **Not a SQLite drop-in.** Reputation asymmetry is real. Treat sqlite-leap as a compatibility-tier implementation, not a substitute for `sqlite3.so`.
- **Not generated end-to-end yet.** `generators/c/generate.sh` and `generators/rust/generate.sh` invoke `generators/leapgen.py` to assemble a build brief; the actual emission step is an LLM agent run, not a deterministic compiler. The five engines were emitted leaf-by-leaf and are maintained as source. The cross-target convergence (byte-identity, SLT parity, file-format agreement) is real; the one-button regeneration loop covers leaf parts and is partial on monolithic ones (e.g., `compiler.rs` at ~19K LOC is past the size where an agent reliably regenerates). See `docs/DASHBOARD.md` for the regen-debt accounting.
- **Not a perf leader engine-vs-engine.** leap-rust loses all three Linux lib-mode lanes (L2 0.67×, L3 0.80×, L4 0.82× of mainline). leap-c L3/L4 wins published earlier are retracted because `src-c/examples/lib_bench.c` silently drops `--db` and runs in-RAM while mainline runs WAL-on-disk — a category error, not a comparison. Tracked as task #413.
- **Not the full corpus.** The 99.84–99.99% rates are on a 335-file sample. The full upstream corpus is 622 files. The full-corpus v2 number is what should be quoted publicly; it isn't measured yet on the v2 spec.

See `docs/PUBLICATION.md` for full per-lane methodology and caveats.

---

## Module surface

The Rust target has behavioral test coverage for: JSON1 (5/5 targets), foreign keys with cascade/restrict/set-null, triggers (BEFORE/AFTER, recursion-guarded), savepoints / RELEASE / ROLLBACK, WITHOUT ROWID, ATTACH multi-DB, R-tree, FTS5 MATCH, virtual tables (xBestIndex/xFilter), PRAGMA-key encryption (AEAD per-row), WAL crash recovery. Cross-target propagation is in progress; only JSON1 is wired into all five targets today.

---

## Reproduction

### Mac (arm64)

```bash
git clone https://github.com/safitudo/sqlite-leap.git  # placeholder; repo URL pending public push
cd sqlite-leap

cargo build --release --manifest-path src-rust/Cargo.toml --example slt_runner --example lib_bench
bash src-c/build_lib_bench.sh

# 5-target SLT parity + on-disk byte-identity + Mac process-level lanes (~90s)
bash demo_5target_stunt.sh

# 335-file SLT sample × 5 targets (~16 min)
bash tests/sqllogictest/run_5target_corpus.sh
```

### Linux x86_64

```bash
ssh <linux-host>
cd sqlite-leap
bash bench/run-linux-libmode.sh   # writes raw.csv

# Or via Docker
docker build -f bench/Dockerfile.linux-x86 -t sqlite-leap-bench .
docker run --rm -v "$PWD:/repo" sqlite-leap-bench bash bench/run-linux-libmode.sh
```

Reference numbers from 2026-04-27 are at `bench/results/2026-04-27-linux-native/`.

---

## Repository layout

| Path | Purpose | Tracked |
|------|---------|---------|
| `parts/` | Language-neutral spec (~33K LOC across leaves) | ✓ |
| `tests/` | Behavioral test corpora (sqllogictest, smokes, eq-runner) | ✓ |
| `generators/` | `leapgen.py` brief assembler + per-target `generate.sh` invokers | ✓ |
| `bench/` | Harness + results + `PUBLISHED.md` registry | ✓ |
| `docs/` | `PUBLICATION.md`, `DASHBOARD.md`, methodology notes | ✓ |
| `src-rust/`, `src-c/`, `src-zig/`, `src-go/`, `src-python/`, `src-wasm/` | Engine source (agent-emitted, hand-maintained, gitignored) | — gitignored |

To regenerate one leaf for one target:

```bash
python generators/leapgen.py --part <leaf> --target <c|rust|zig|go|python>
# emits build brief to stdout; pipe into your agent harness
```

The five `src-*` trees are reproducible from `parts/` for leaves under ~3K LOC per target. Larger files (`compiler.rs` ~19K) need sub-decomposition into smaller leaves before they regenerate cleanly; see `docs/DASHBOARD.md` for which files have known regen-debt.

## License

(TBD — pending decision before public publication.)

## Acknowledgements

SQLite by D. Richard Hipp et al. — the canonical implementation and the published file-format/SQL specifications this project targets for compatibility. The mainline SQLite source code was off-limits during generation; only the published file-format documentation and SQL standards were referenced.

Critical reviewers caught earlier drafts of this README and the publication post inflating headline tables, mis-citing CSVs, and re-publishing already-retracted numbers. The version above is the corrected one. Every number cites the file in the repo it came from; numbers with citation drift are tracked in `bench/PUBLISHED.md` and reconciled before each public revision.
