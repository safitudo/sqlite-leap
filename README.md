# sqlite-leap

A research artifact: how far can a language-neutral specification carry SQLite compatibility across multiple target languages? Five engines (**C, Rust, Zig, Go, Python**) plus a WASM build are maintained against the same prose specs in `parts/`. They are evaluated against mainline SQLite for behavior, on-disk format, and process-level metrics.

Built using [LEAP](https://github.com/safitudo/leap) methodology: tests and specs are the load-bearing artifacts; engine source is regenerable from `parts/` (caveats below).

> **The question this project answers**
>
> Not "does it beat SQLite" — it doesn't, on most measures, and where it does the comparison usually has a caveat. The interesting question is *how far* a single neutral spec carries you across five languages. This repo says: far enough that five hand-emitted engines agree byte-for-byte with mainline at fixed `.db` fixtures, ship as 361 KB (C, Mac) / 500 KB (C, Linux) to 4.6 MB (Go) binaries, and pass **98.88–99.98% of the records they attempt** on the full 622-file upstream sqllogictest corpus on Linux native (post-2026-04-30, post-zigrebase). The 4 compiled targets (rust/c/zig/go) all attempt **99.93–99.96%** of mainline's record surface — denominator parity holds. leap-python attempts 98.94%. Mainline runs the full corpus at 99.9997%. See `bench/PUBLISHED.md §A.1` for per-target detail.

**Single source of truth for every published number:** [`bench/PUBLISHED.md`](bench/PUBLISHED.md). Each claim cites the CSV path and date. The TL;DR below is a digest of that file; if the two ever disagree, `PUBLISHED.md` wins.

---

## What's load-bearing today

1. **Cross-target byte-identity at fixed fixtures.** All 5 leap targets and mainline SQLite produce SHA1-identical `.db` files at a 270-row split fixture and a 5,000-row deep-split fixture. Mainline `PRAGMA integrity_check` returns `ok` on every leap-emitted file. (Two fixtures, not random-shape fuzz.)

2. **sqllogictest parity on the full 622-file upstream corpus, Linux x86_64 native (2026-04-30, post-zigrebase).** All 5 leap targets pass **98.88–99.98% excl-SKIP** on the records they attempt; mainline runs the full corpus at **100.00%**. The 4 compiled targets (rust/c/zig/go) all attempt **99.93–99.96%** of mainline's record surface (denominator parity holds — closed by Pin α29-pc-rebase + α23-c-bufslot-mat); leap-python attempts 98.94% (240s budget on the pure-Python interpreter still leaves 11 timeouts on heavy random/* files). leap-zig's 98.88% reflects 65,998 record-level FAILs the prior post-pcrebase build was masking via timeouts on the random/expr cluster — substantively this is the parity gap surfacing, not a regression. Source: `tests/sqllogictest/results/corpus_2026_04_30_post_zigrebase/summary.json`. Per-target detail in [`bench/PUBLISHED.md` §A.1](bench/PUBLISHED.md). **Crashes: 0 across all 4 compiled leap targets**; leap-python has 3 (regressions from the longer 240s budget exposing previously-masked paths; under triage); mainline 0. The 2 timeouts on every leap target are the same 2 files — `select4.test`/`select5.test`, deeply nested 5-way unindexed equijoin planner stress.

3. **Three builds from the Rust target.** Native, cross-compiled, and `wasm32-unknown-unknown` (231 KB). The WASM smoke runs SELECT-expression cases under Node.

4. **L3 SELECT in-RAM lib-mode wins on three of five targets** (post-Pin-18.1e, all 5 targets producing real `-wal` sidecars with mainline `integrity_check; → ok`): leap-zig 1.99×, leap-c 1.54×, leap-rust 1.14× over mainline. leap-go 0.93× (lose 7%). L2 parse-only on a filtered 65,653-statement corpus: leap-c 1.75× win (parse-only, no DB open). L4 INSERT --db: leap loses to mainline on every fully apples-to-apples row; leap-zig 1.54× provisional. Source: `bench/results/2026-04-28-linux-native-libmode-postPin18.1e/raw.csv` and `bench/results/2026-04-27-linux-native/lane2-parseonly/raw.csv`.

5. **Process-level metrics, not engine-vs-engine.** L1 cold start: leap-c/rust/zig 4–17× faster than mainline `sqlite3` on Mac and Linux. L5 binary size: leap-c at 207 KB (Mac) / 512 KB (Linux) vs mainline `sqlite3` CLI at 1.22 MB — apples-to-oranges; the mainline number includes the CLI shell + readline + ICU. L6 RSS is run-to-run noisy and the latest demo run shows leap-c at 0.98× mainline (i.e., loses by 2%); we no longer publish a fixed L6 win claim. Sources: `bench/results/{cold_start,binary_size,memory_footprint}_5target/REPORT.md`.

## What we don't claim

- **Not a SQLite drop-in.** Reputation asymmetry is real. Treat sqlite-leap as a compatibility-tier implementation, not a substitute for `sqlite3.so`.
- **Not generated end-to-end yet.** `generators/c/generate.sh` and `generators/rust/generate.sh` invoke `generators/leapgen.py` to assemble a build brief; the actual emission step is an LLM agent run, not a deterministic compiler. The five engines were emitted leaf-by-leaf and are maintained as source. The cross-target convergence (byte-identity, SLT parity, file-format agreement) is real; the one-button regeneration loop covers leaf parts and is partial on monolithic ones (e.g., `compiler.rs` at ~19K LOC is past the size where an agent reliably regenerates). See `docs/DASHBOARD.md` for the regen-debt accounting.
- **Mixed engine-vs-engine perf in lib-mode.** Post-Pin-18.1e Linux 5-target × 3-lane matrix (`bench/results/2026-04-28-linux-native-libmode-postPin18.1e/raw.csv`): **L3 SELECT in-RAM** — leap-zig 1.99× win, leap-c 1.54× win, leap-rust 1.14× win, leap-go 0.93× lose, leap-python 0.021×. **L4 INSERT --db** — leap-zig 1.54× win (provisional, close-time WAL flush vs per-COMMIT — see `bench/PUBLISHED.md §B.3`); leap-c 0.83× lose, leap-rust 0.56× lose, leap-go 0.67× lose, leap-python 0.018×. The "leap-c L4 1.87× win" published in earlier drafts was free durability (the C harness wasn't fsyncing); under Pin 18.1e it now does, and the win evaporates. leap loses L4 against mainline on every fully apples-to-apples row.

See `docs/PUBLICATION.md` for full per-lane methodology and caveats.

---

## Module surface

The Rust target has behavioral test coverage for: JSON1 (5/5 targets), foreign keys with cascade/restrict/set-null, triggers (BEFORE/AFTER, recursion-guarded), savepoints / RELEASE / ROLLBACK, WITHOUT ROWID, ATTACH multi-DB, R-tree, FTS5 MATCH, virtual tables (xBestIndex/xFilter), PRAGMA-key encryption (AEAD per-row), WAL crash recovery. Cross-target propagation is in progress; only JSON1 is wired into all five targets today.

---

## Reproduction

Engine source for the five targets is distributed via [GitHub Releases](https://github.com/safitudo/sqlite-leap/releases) (the repo itself ships only the spec, tests, and bench harness — source lives outside `git` because it is regenerable from `parts/` for leaf parts and the resulting trees are large; see `docs/PUBLICATION.md` for the regen story).

### Mac (arm64)

```bash
git clone https://github.com/safitudo/sqlite-leap.git
cd sqlite-leap

# Pull engine sources for the targets you want to reproduce
TAG=v0.1.0-publication-2026-04-28
for tgt in c rust zig go python; do
  curl -L -o /tmp/src-$tgt.tar.gz \
    https://github.com/safitudo/sqlite-leap/releases/download/$TAG/src-$tgt.tar.gz
  tar xzf /tmp/src-$tgt.tar.gz
done

# Verify checksums
curl -L -o SHA256SUMS \
  https://github.com/safitudo/sqlite-leap/releases/download/$TAG/SHA256SUMS
shasum -a 256 -c SHA256SUMS

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
