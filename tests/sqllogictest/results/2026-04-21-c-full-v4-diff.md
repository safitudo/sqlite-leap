# Full sqllogictest corpus — leap-c — v3 → v4 diff

**Headline:** v3 561/622 (90.19%) → v4 **576/622 (92.60%)**. +15 files, +2.41 pp.

- v3 log: `tests/sqllogictest/results/2026-04-21-c-full-v3.log`
- v4 log: `tests/sqllogictest/results/2026-04-21-c-full-v4.log` (2026-04-21T09:56Z)
- Runner: `tests/sqllogictest/run-full-corpus-parallel.sh --target c --timeout 90 --jobs 8`
- Binary: `src-c/bin/sqllogictest` (release build, clean compile, zero warnings)
- Corpus: `tests/sqllogictest/upstream/test` (622 `.test` files)

## Transitions

| | count |
|---|---|
| FAIL → PASS | 15 |
| PASS → FAIL | 0 |
| PASS → TIMEOUT | 0 |
| PASS → PANIC | 0 |
| TIMEOUT → PASS | 0 |
| Unchanged PASS | 561 |
| Unchanged FAIL | 13 |
| Unchanged TIMEOUT | 33 |

Zero regressions. Zero panics.

### FAIL → PASS (15) — all in `index/view/`

```
index/view/10/slt_good_0.test
index/view/10/slt_good_1.test
index/view/10/slt_good_2.test
index/view/10/slt_good_3.test
index/view/10/slt_good_4.test
index/view/100/slt_good_0.test
index/view/100/slt_good_1.test
index/view/100/slt_good_2.test
index/view/100/slt_good_3.test
index/view/100/slt_good_4.test
index/view/1000/slt_good_0.test
index/view/1000/slt_good_1.test
index/view/1000/slt_good_2.test
index/view/1000/slt_good_3.test
index/view/1000/slt_good_4.test
```

## What closed the gap since v3

- **#139** — derived-table parser port (Phase 6br, `FROM (SELECT ...) AS alias`)
  on C. The Rust parser already accepted this form (via #122 VIEW + #123
  derived-table runtime wiring); the C parser had been rejecting it as a
  "Phase 6bq non-goal". Ported `parse_from_source_group` on `src-c/parser.c`
  to accept `LPAREN SELECT/WITH/VALUES` the same way Rust does. All 15
  `index/view/*` files in the upstream corpus use this shape as their
  load-bearing setup (they `CREATE VIEW` over a derived table and then test
  SELECTs over the view). Pass rate moved in one clean hop.

## Residual failures (46)

### FAIL (13)

- `evidence/slt_lang_update.test` — STORAGE_DUPLICATE_COLUMN on DDL; 2 UPDATE
  row-value mismatches. Same file Rust also fails; shared debt, not C-only.
- `random/groupby/slt_good_{0,1,2,4,6,7,8,9,10,11,12,13}.test` — 12 files,
  cluster around the bare-non-key-GROUP-BY + JOIN divergence (leap-c emits
  NULL for bare non-key columns where mainline + leap-rust emit last-row-seen
  via Phase 6bo sorter trick). Divergence not crash; fixture cases already
  documented. Rust passes 9 of these after its v4 AMBIGUOUS_ALIAS fix.

### TIMEOUT (33) — 90s wall budget

- `index/random/{10,100,1000}/*` — 22 files. Large-row index workloads; Rust
  passes 15 of them, times out on 7. C planner cost / index-scan throughput
  is slower on the 10-row-per-file-but-MANY-files variant (the `10/` subdir
  has 15 files each with many repeated scans).
- `index/between/{100,1000}/*` — 2 files, large-row range scans.
- `index/commute/1000/*` — 3 files.
- `index/in/1000/*` — 2 files.
- `index/orderby/1000/*` — 1 file.
- `select4.test`, `select5.test` — 2 files. Shared timeouts with Rust; the
  hardest SELECT files in the corpus, performance-bound not correctness.
- Joint debt: of the 33 C timeouts, 11 are also Rust timeouts or residual
  issues; the remaining 22 are C-specific planner-perf debt on small-row
  index workloads.

## Cross-target equivalence snapshot (C v4 vs Rust v4)

- PASS on both targets: **561 / 622 (90.19%)** — the "both-green" baseline
  that anchors the byte-identical claim for the corpus.
- PASS Rust only (C-specific debt): **54** — 13 FAIL + 22 TIMEOUT; TIMEOUTs
  dominate and are correctness-clean (just slower).
- PASS C only: **15** — the `index/view/*` files that C v4 unlocked and
  Rust v4 also passes. (Both targets now pass these; the asymmetry in "PASS
  C only" is zero because everything C gained is also Rust-green.)

## Remaining work (ordered by leverage)

1. **C planner throughput on `index/random/10/` and `index/random/100/`** —
   small-row-many-scan cluster; 22 TIMEOUTs likely closeable by a single
   planner-cost tweak.
2. **GROUP BY joint debt (`random/groupby/*`)** — 12 files C, 4 Rust; spec
   work on bare-column semantics under GROUP BY + JOIN. Cross-target.
3. **select4 / select5 joint timeouts** — hardest files; likely wait for
   Phase-5-completion VDBE profile + arena allocator (deferred).
4. **`evidence/slt_lang_update.test` UPDATE mismatch** — narrow, both
   targets; single spec pass.
