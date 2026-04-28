# Published numbers — single source of truth

Every numeric claim that appears in `README.md`, `docs/PUBLICATION.md`, or any external write-up about sqlite-leap **must** appear here with a CSV path and a measurement-date. If a doc carries a number not in this file, the doc is wrong.

When a number is **retracted**, it is removed from this file and the rationale recorded in the changelog at the bottom. Re-publishing a retracted number requires a new measurement entry, not a re-add of the old one.

Format: each section is a measurement family. Within a family, every row names the lane, the platform, the source CSV, the measurement date, and the scope caveat that gates how it can be cited.

---

## A. sqllogictest pass rates

### A.1 — **PRIMARY**: 622-file v2 full corpus, Linux x86_64 native (2026-04-28)

Source: `tests/sqllogictest/results/corpus_2026_04_28_full/summary.json`. 622 upstream `.test` files × 6 targets, 60s per-file timeout, 70 min wall clock, Ubuntu 22.04 native (rustc 1.89, gcc 11.4, zig 0.16, go 1.25). **Record-level** pass-rate (each statement counted, not each file).

| Target | pass | fail | defer | skip | timeouts | crashes | total | exec/mainline | incl-SKIP | **excl-SKIP** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sqlite-leap-rust | 5,424,607 | 878 | 76 | 1,207,295 | 82 | **0** | 6,632,856 | **89.5%** | 81.78% | **99.98%** |
| sqlite-leap-python | 5,683,224 | 1,128 | 58 | 1,473,859 | 27 | 17 | 7,158,269 | **96.6%** | 79.39% | **99.98%** |
| sqlite-leap-go | 4,672,160 | 3,562 | 45 | 808,851 | 132 | **0** | 5,484,618 | **74.0%** | 85.19% | **99.92%** |
| sqlite-leap-zig | 4,803,848 | 8,121 | 298 | 857,565 | 119 | 11 | 5,669,832 | **76.5%** | 84.73% | **99.83%** |
| sqlite-leap-c | 4,105,212 | 672 | 17,549 | 600,079 | 123 | 88 | 4,723,512 | **63.7%** | 86.91% | **99.56%** |
| sqlite-mainline | 5,932,125 | 19 | 0 | 1,480,839 | 0 | 1 | 7,412,983 | 100% | 80.02% | **99.9997%** |

`exec/mainline` = (target's total records) / (mainline's total records). It quantifies **how much of mainline's executed test surface this target also attempts**. The remainder is bucketed as SKIP — runs that the target's harness or runner refused to execute (unimplemented features, parser gaps, runner directives the target doesn't honor, etc.).

**Headline that must accompany any cross-target pass-rate claim:** "On the full upstream sqllogictest corpus, the five leap targets pass 99.56% to 99.98% excl-SKIP — but the targets evaluate different denominators. leap-python attempts 96.6% of mainline's records; leap-rust 89.5%; leap-zig 76.5%; leap-go 74.0%; leap-c **only 63.7%**. The narrow excl-SKIP gap (0.44pp for leap-c) is on a 36% smaller corpus than mainline's. The story isn't 'leap-c is 0.44pp behind mainline' — it's 'leap-c attempts 63.7% of what mainline runs and passes 99.56% of that subset.'"

**Scope caveats that must be quoted alongside any pass-rate claim:**
- Per-file 60s timeout; files that hang are counted as deferred. A no-timeout run would surface more crashes/hangs as failures, not advantages.
- Record-level pass-rate, not file-level. File-level is in §A.3 below for comparison with the older v1 measurement.
- **Denominator asymmetry is material.** Each target's excl-SKIP percentage is computed against its own (target-specific, smaller) total, not against mainline's. The `exec/mainline` column makes the asymmetry explicit; it must be reported alongside the excl-SKIP number, not buried.
- **Crashes are real, not noise.** leap-c has 88 crashes (largely a planner-perf timeout cluster in `random/index/*` and `random/groupby/*`); leap-python 17; leap-zig 11; leap-rust and leap-go zero. Mainline crashed on 1 file (likely a recursive-CTE depth-bound). These crashes are publication-relevant and must not be hidden when the excl-SKIP percentage is quoted.
- mainline's incl-SKIP (80.02%) is *lower* than leap-c's (86.91%) because mainline reports more rows as SKIP on this harness's strict comparison **on its own larger denominator**. Use excl-SKIP + `exec/mainline` together for cross-engine comparison.

### A.2 — 335-file post-G3 sample, Mac arm64 (2026-04-27, retained for comparison)

The same harness's earlier sample-only run, kept as a regression-tracking baseline. Source: `tests/sqllogictest/results/corpus_2026_04_27_post_G3/summary.json`. **This is no longer the headline rate** — A.1 above replaces it.

| Target | excl-SKIP (sample) | excl-SKIP (full corpus, A.1) | Δ |
|---|---:|---:|---:|
| rust | 99.99% | 99.98% | -0.01pp |
| python | 99.98% | 99.98% | 0.00pp |
| go | 99.99% | 99.92% | -0.07pp |
| zig | 99.97% | 99.83% | -0.14pp |
| c | 99.99% | 99.56% | **-0.43pp** |

The sample was slightly favorable across the board; leap-c was the most affected (0.43pp drop). The order of targets is preserved (rust ≈ python > go > zig > c). The story is consistent; the sample was not a cherry-pick of the corpus, but it was a real underestimate of where the targets land on the long tail.

### A.3 — 622-file v1 full corpus (2026-04-23, archival)

The pre-v2-spec full-corpus run, kept for historical comparison. **File-level** pass-rate (binary per file), so not directly comparable to A.1's record-level rate.

| Target | file-level | Source |
|---|---:|---|
| sqlite-leap-rust | 99.68% (620/622) | `tests/sqllogictest/results/2026-04-23-rust-full-v5.log` |
| sqlite-leap-c | 94.53% (588/622) | `tests/sqllogictest/results/2026-04-23-c-full-v5.log` |

The v2 spec lifted file-level pass-rate substantially (especially on C, where the v1 94.53% became a much higher record-level rate post-v2; the file-level rate isn't broken out in A.1's summary but is recoverable from the per-file logs).

---

## B. Linux x86_64 lib-mode benchmarks

Source CSVs: `bench/results/2026-04-27-linux-native/raw.csv` (L3, L4) and `bench/results/2026-04-27-linux-native/lane2-parseonly/raw.csv` (L2 filtered). Hardware: Ubuntu 22.04, kernel 6.8, glibc 2.35, rustc 1.89.0, gcc 11.4.0, single 32-core box. Library-mode = both engines invoked as `<lib_bench> <workload> --time-setup --db /tmp/x.<target>`.

### B.1 — Survivable claims

| Lane | Target | Measurement | Scope |
|---|---|---:|---|
| L2 parse-only filtered | sqlite-leap-c | **1,857,806 stmt/s** | filtered 65,653-statement corpus; lane is parse-only, never opens a DB; harness asymmetry below does not apply |
| L2 parse-only filtered | sqlite-mainline | 1,060,065 stmt/s | same |
| L2 parse-only filtered | sqlite-leap-rust | 710,430 stmt/s | same |
| L2 ratio leap-c vs mainline | — | **1.75× win** | publishable as "leap-c parses 1.75× faster than mainline on this filtered corpus, lib-mode" with the L2 caveat below |

**L2 caveat that must be quoted with any L2 number:** mainline's `prepare_v2` fast-rejects 39,448 of 65,653 (60%) at name-resolution because CREATEs aren't run in `--parse-only` mode; leap parsers don't do name-resolution. Per-success cost: mainline 2.4 µs, leap-rust 1.75 µs (1.4× faster per success); but leap-c's total throughput is the headline metric. Unfiltered L2 in `linux-x86_64/raw.csv` reports leap-c 2,378 vs mainline 64,955 = leap-c **loses 27×** on the unfiltered corpus, same name-resolution asymmetry without filtering. **Both filtered and unfiltered numbers must be cited together** when L2 is published.

### B.2 — Engine-vs-engine claims (leap-rust ↔ mainline only — apples-to-apples)

| Lane | mainline | leap-rust | leap-rust vs mainline |
|---|---:|---:|---:|
| L2 parse-only filtered (stmt/s) | 1,060,065 | 710,430 | **0.67× (lose)** |
| L3 SELECT in-memory (sel/s) | 631,752 | 505,008 | **0.80× (lose)** |
| L4 INSERT file-backed (ins/s) | 678,258 | 555,862 | **0.82× (lose)** |

leap-rust is **correctness-equivalent and slower**. The L4 row is the only bench in the project today where both sides are verifiably file-backed with WAL + fsync (Pin 18.1d, commit `7abf1f7`).

### B.3 — Retracted

- **leap-c L3 1.51×, L4 1.81×** (Linux lib-mode, 2026-04-27). **Cause:** `src-c/examples/lib_bench.c::main()` parses `--prepared/--rows/--time-setup` but silently drops `--db`; database is unconditionally `leap_storage_database_new()` (in-memory). PRAGMA `journal_mode=WAL` and `synchronous=NORMAL` are classified `STMT_NOOP` (line 220). `build_lib_bench.sh` does not link `storage_wal.c` / `wal_bridge.c` / `page_cache.c`. So the comparison was leap-c-in-RAM vs mainline-WAL-fsynced-to-disk — a category error, not a 1.51×/1.81× win. **Not republishable** until task #413 (5-target lib_bench --db honoring) lands.
- **leap-zig, leap-go, leap-python lib-mode** — harnesses not audited for `--db` honor. No lib-mode claim publishable.

---

## C. Process-level metrics — Mac arm64 + Linux x86_64

Source CSVs: `bench/results/2026-04-28-StanislacStudio.csv` (Mac M-series arm64), `bench/results/2026-04-28-stanislav-s.csv` (Ubuntu 22.04 x86_64). These are process-spawn wallclock measurements, **not engine-vs-engine throughput**.

### C.1 — L1 cold start (lower=better, ms)

Both Mac and Linux CSVs contain **two timestamped runs** per host: an initial 03:36 UTC sweep where some targets were missing built binaries (`NA,missing-binary`) and a follow-up 04:01–04:10 sweep after toolchain installs/builds completed. The numbers below are from the **completed-build runs**; the row date in the CSV identifies which.

| target | Mac (run) | Linux (run) |
|---|---:|---:|
| sqlite-leap-c | 3.51 (03:36) | 0.54 (04:10) |
| sqlite-leap-rust | 3.41 (03:36) | 0.42 (03:36) |
| sqlite-leap-zig | **n/a — Mac CSV has no cold-start zig row** | 0.44 (04:01) |
| sqlite-leap-go | 4.23 (04:03) | 0.93 (04:01) |
| sqlite-leap-python | 156.1 (04:03) | 98.3 (04:01) |
| sqlite-mainline | 9.17 (03:36) | 1.68 (03:36) |
| turso | 11.02 (03:36) | 1.66 (03:36) |
| turso-core | 6.10 (03:36) | n/a (not measured) |

**Publishable:** leap-c, leap-rust, and leap-go beat mainline cold-start 2–4× on Mac and 2–4× on Linux. leap-zig beats mainline 3.8× on Linux; **on Mac, no cold-start measurement for leap-zig is in the cited CSV** — earlier drafts of this table reported a Mac leap-zig L1 of 3.84 ms which is not sourceable from `bench/results/2026-04-28-StanislacStudio.csv` and is therefore retracted; if a Mac-zig L1 is wanted, it needs a fresh CSV row. Python is the cold-start laggard on both platforms (CPython startup).

### C.2 — L5 binary size (lower=better, KB)

| target | Mac | Linux |
|---|---:|---:|
| sqlite-leap-c | **361 KB** | **500 KB** |
| sqlite-leap-rust | 1937 KB | 1681 KB |
| sqlite-leap-zig | 1145 KB | 8042 KB (unstripped) |
| sqlite-leap-go | 4496 KB | 4502 KB |
| sqlite-leap-python (script) | 21 KB | 21 KB |
| sqlite-mainline (CLI) | 1191 KB | 1191 KB |
| turso (CLI) | 13170 KB | 13170 KB |
| turso-core (lib harness) | 6182 KB | 6182 KB |

**Publishable:** leap-c is 3.3× smaller than mainline `sqlite3` CLI on Mac, 2.4× on Linux. **Mandatory caveat:** mainline's number includes its CLI shell + readline + ICU. An engine-only mainline build would shrink the gap; the apples-to-apples comparison is between leap-c's library harness and an engine-only mainline build, which is not measured.

### C.3 — L6 peak RSS (lower=better, MB)

L6 is **run-to-run noisy**. Latest demo run on Mac (2026-04-27) shows leap-c at 0.98× mainline (loses by 2%). Earlier runs showed leap-c winning by 1.29×. Until L6 measurement methodology is hardened (e.g., median-of-N runs at fixed warmup), **no fixed L6 win or loss claim is publishable**. The CSVs above are recorded for reproduction; the doc layer does not lead with them.

### C.4 — CLI-mode L2/L3/L4 — methodology caveat

The `bench/run-all.sh` CLI lanes for L2/L3/L4 feed SQL through a shell pipe to each binary. On a fast process that exits before doing real work, wall-clock approaches 0 → reported throughput approaches infinity. Linux mainline lane-2 reports 6.07 GB/s parse, lane-3 reports 56M qps SELECT, lane-4 reports 34.7M ips INSERT — clearly impossible engine numbers, observed because `sqlite3 :memory: < workload.sql` exits in <1ms with most work skipped at name-resolution. **CLI-mode L2/L3/L4 numbers are not publishable as engine-vs-engine claims.** Use lib-mode (Section B) for engine throughput.

---

## D. On-disk format byte-identity

Two fixtures, all 5 leap targets + mainline produce SHA1-identical .db files; mainline `PRAGMA integrity_check` returns `ok` on every leap-emitted file.

| Fixture | SHA1 | Targets agreeing |
|---|---|---|
| 270-row split | `b5f1f8978407c13291c0fa124ec1e955e2b45ff4` | rust, c, zig, go, python (5/5) + mainline |
| 5,000-row deep-split | `fef632262aa2b02fb620b6c3dcfab5ba55cb1bda` | rust, c, zig, go, python (5/5) + mainline |

**Scope caveat:** two fixtures, not random-shape fuzz. Random-shape `.db` byte-identity at scale is **not** claimed.

---

## E. WASM build

| Artifact | Size | Smoke |
|---|---:|---|
| `src-wasm/sqlite_leap.wasm` | **231 KB** | 6/6 SELECT-expression smokes pass under Node |

Source: `generators/wasm/build.sh` (shells out to `cargo build --target wasm32-unknown-unknown` from src-rust).

---

## F. Code volume

| Metric | Count | Source |
|---|---:|---|
| Spec lines (parts/) | ~33,000 | `wc -l parts/**/*.md` |
| Engine source lines (src-*) | ~234,000 | `wc -l src-*/**/*.{c,rs,zig,go,py}` (5 target trees) |

**Scope caveat that must be quoted alongside any "33K → 234K" claim:** raw counts are correct; the **causal arrow is partial**. `generators/c/generate.sh` and `generators/rust/generate.sh` invoke `leapgen.py` to assemble a build brief; the actual emission step is an LLM agent run. The five engines were emitted leaf-by-leaf and are maintained as source. Convergence (byte-identity, SLT parity) is real; one-button regeneration covers leaf parts up to ~3K LOC per target reliably. Monolithic files (e.g., `compiler.rs` ~19K) are past the regen envelope and hand-maintained — see `docs/DASHBOARD.md` for regen-debt accounting.

---

## Changelog

- **2026-04-28** (third pass, after audit) — Critic flagged: (a) Mac leap-zig L1 = 3.84 ms not in cited CSV → row marked `n/a` with retraction note in §C.1; (b) Mac leap-python L1 was 158.1 ms in doc, CSV has 156.11 → corrected to 156.1; (c) §C.1 now names the timestamped run for each cell (CSVs contain two sweeps per host, initial 03:36 with NA-binaries and follow-up 04:01–04:10 after toolchain installs); (d) §A.1 gained an `exec/mainline` column (target's total / mainline's total = 63.7%–96.6%) — the "0.44pp behind mainline" framing was eliding that leap-c attempts only 63.7% of mainline's record set. README and PUBLICATION TL;DRs updated to lead with denominator asymmetry, not the percentage gap.

- **2026-04-28** (later) — A.1 promoted to full-corpus 622-file Linux native record-level rate. Sample (former A.1) demoted to A.2 with a Δ column showing the sample was ~0.01–0.43pp favorable per target. v1 file-level archival moved to A.3. Headline now cites real full-corpus, not a sample.

- **2026-04-28** — File created. Migrates published numbers from README.md and docs/PUBLICATION.md. Retractions formalized: leap-c L3/L4 lib-mode wins (B.3) removed; L6 fixed-direction claim (C.3) removed pending methodology hardening. The "33K → 234K" claim (F) gains a mandatory causal-arrow caveat.

- **History prior to file creation** is in `git log -- README.md docs/PUBLICATION.md`. Notable retraction events:
  - `61a5116` (2026-04-27) — first retraction of leap-c L3/L4 wins; Rust harness fix `7abf1f7` followed; C harness fix did not.
  - `fd102ee` (2026-04-27) — re-published the retracted leap-c numbers; caught externally.
  - 2026-04-28 — second retraction (this file's B.3 entry).
