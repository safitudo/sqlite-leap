# sqllogictest leap-c corpus: v2 -> v3 diff

**Headline:** 161/622 (25.88%) -> **561/622 (90.19%)**, delta **+400 files / +64.31 pp**.

Run metadata:
- Binary: `src-c/bin/sqllogictest` (clean rebuild, zero warnings)
- Runner: `tests/sqllogictest/run-full-corpus-parallel.sh --target c --timeout 90 --jobs 8`
- Log: `tests/sqllogictest/results/2026-04-21-c-full-v3.log`
- Date (UTC): 2026-04-21

Fixes landed between v2 and v3:
1. #129 C planner IDX\* pc-remap (3 splicing paths)
2. #133 DISTINCT copy-loop (agg_distinct + scalar\*_kind fields)
3. (Minor, already in v2: NULLIF + DIV-zero; new kqueue backend is additive to corpus.)

## Counts

| Status   | v2  | v3  | delta |
|----------|-----|-----|-------|
| PASS     | 161 | 561 | +400  |
| FAIL     | 271 |  28 | -243  |
| TIMEOUT  | 190 |  33 | -157  |
| PANIC    |   0 |   0 |   0   |

## Transitions

- FAIL/TIMEOUT -> PASS: **400**
  - of which TIMEOUT -> PASS: **147** (planner fix, as projected: 155 of 190)
  - TIMEOUT -> FAIL: 10 (no longer wedging, now localisable)
  - FAIL -> TIMEOUT: 0
- **PASS -> not-PASS (regressions): 0**

## FAIL/TIMEOUT -> PASS by subdirectory

| Subdir                 | Flipped | v2 non-pass |
|------------------------|---------|-------------|
| random/aggregates      |  +130   | 130 (100%)  |
| random/expr            |  +120   | 120 (100%)  |
| index/commute          |   +49   |  52         |
| index/orderby_nosort   |   +47   |  47 (100%)  |
| index/orderby          |   +29   |  30         |
| index/between          |   +11   |  13         |
| index/in               |   +11   |  13         |
| random/groupby         |    +2   |  14         |
| random/select          |    +1   |   1         |

`random/aggregates` and `random/expr` were completely fixed (the DISTINCT copy-loop bug dominated both). Index subdirs heavily picked up from the planner IDX\* fix, consistent with the TIMEOUT-heavy profile seen in v2.

## Top-5 residual failure kinds (v3)

1. **`index/view/*` FAIL (15 files)** — every `index/view` failure lines up with a file Rust passes, so this is a C-specific debt in VIEW handling (likely a missing VIEW-expansion path in the compiler or planner, not a spec gap).
2. **`index/random/*` TIMEOUT (23 files)** — large index workloads still slower on C than on Rust (Rust passes 1 of these, times out 1; C times out all 23 at 10-row and 100/1000 variants). Planner cost / index-scan throughput issue.
3. **`random/groupby` FAIL (12 files)** — cross-target: Rust also fails 10 of the 14 groupby files but passes 2 that C fails; shared GROUP BY issues plus a small C-specific increment.
4. **`select4.test` / `select5.test` TIMEOUT (2 files)** — same files that time out on Rust v2 (both targets). Hardest/largest in the suite; joint debt, not C-only.
5. **Miscellaneous index/* TIMEOUT (8 files)**: `index/commute/1000` (3), `index/in/1000` (2), `index/between` (2), `index/orderby/1000` (1). Large-row variants where Rust also needs attention on one.

## Cross-target equivalence (C v3 vs Rust v2)

- **PASS on both targets: 558** (both-targets-green, the real LEAP claim)
- **PASS Rust only (C-specific debt): 26**
  - 17 FAIL on C: 15x `index/view/*`, 2x `random/groupby/{2,4}`
  - 9 TIMEOUT on C: large-row `index/{between,commute,in,orderby,random}/1000`
- **PASS C only: 3** (`random/aggregates/slt_good_{7,47,126}.test`; Rust still fails these — DISTINCT fix likely hasn't landed Rust-side yet)

Rust v2 as reported in the task note (614 / 98.71%) does not match this run's Rust v2 log (584 / 93.89%). The 614 figure may be a different Rust build or later re-run; the number above uses `results/2026-04-20-rust-full-v2.log` as the on-disk source of truth. The 558 both-targets-green count is based on that file.

## Remaining work after this measurement

Ordered by fix leverage:

1. **`index/view/*` on C** — 15 files in one coherent cluster, Rust passes them all; likely a single compiler-path bug.
2. **C planner perf on large index workloads** — 9 large-row TIMEOUTs; not correctness. Separate from correctness lift.
3. **GROUP BY joint debt** — random/groupby fails 12 on C, 10 on Rust; spec-level issue, regen both targets after fix.
4. **select4/select5 joint timeouts** — deferred, both targets.

Evidence file failure (`evidence/slt_lang_update.test`): 1 FAIL, non-cluster; probably a small quirk. Low priority.
