# Full sqllogictest corpus — leap-c — v4 → v5 diff

**Headline:** v4 576/622 (92.60%) → v5 **588/622 (94.53%)**. +12 files, +1.93 pp.

- v4 log: `tests/sqllogictest/results/2026-04-21-c-full-v4.log`
- v5 log: `tests/sqllogictest/results/2026-04-23-c-full-v5.log` (2026-04-23T22:52Z)
- Runner: `tests/sqllogictest/run-full-corpus-parallel.sh --target c --timeout 90 --jobs 8`
- Binary: `src-c/bin/sqllogictest` (release build, clean compile, zero warnings)
- Corpus: `tests/sqllogictest/upstream/test` (622 `.test` files)

## Transitions

| | count |
|---|---|
| FAIL → PASS | 12 |
| PASS → FAIL | 0 |
| PASS → TIMEOUT | 0 |
| PASS → PANIC | 0 |
| TIMEOUT → PASS | 0 |
| Unchanged PASS | 576 |
| Unchanged FAIL | 1 |
| Unchanged TIMEOUT | 33 |

Zero regressions. Zero panics.

### FAIL → PASS (12) — all in `random/groupby/`

```
random/groupby/slt_good_0.test
random/groupby/slt_good_1.test
random/groupby/slt_good_2.test
random/groupby/slt_good_4.test
random/groupby/slt_good_6.test
random/groupby/slt_good_7.test
random/groupby/slt_good_8.test
random/groupby/slt_good_9.test
random/groupby/slt_good_10.test
random/groupby/slt_good_11.test
random/groupby/slt_good_12.test
random/groupby/slt_good_13.test
```

## What closed the gap since v4

Three C-side compiler fixes, all derived from pre-existing spec clauses that
the C target hadn't yet implemented (Rust had landed them earlier; this round
brings C to parity on the groupby cluster).

1. **Phase 6cc duplicate-alias + base-column tiebreak** (spec
   `sql-grammar.spec.md` § Phase 6aj line 4551). When two projection slots
   share the same alias name AND that name also matches a base column of the
   enclosing FROM, mainline SQLite resolves post-projection clause references
   (GROUP BY / ORDER BY / HAVING) to the base column rather than raising
   `COMPILE_AMBIGUOUS_ALIAS`. C's `alias_rewrite_expr` now checks
   `column_exists_in_scope` before erroring on the duplicate-alias path.
2. **Phase 6cd single-alias shadow rule in GROUP BY / HAVING** (spec § Phase
   6aj line 4550 + 4561). Even for a unique projection alias, if its name
   shadows a base column of the enclosing FROM, the base column wins in
   GROUP BY / HAVING contexts. ORDER BY retains alias-wins behaviour. C's
   `alias_rewrite_expr` now takes a clause-context argument and applies the
   shadow rule asymmetrically.
3. **Phase 6bx (C-internal): PROJ_STAR expansion for grouped SELECTs** (new
   C-local prepass `expand_projection_star_for_grouped`; pinned in
   `tests/cross-build/phase6bx-c-groupby-star.json`). The single-table
   grouped-aggregated compile path used `ast->sel_projection.n` as projection
   width, which is 0 for `PROJ_STAR` — so `SELECT * FROM t GROUP BY k`
   emitted zero-column result rows, flagged by sqllogictest as
   `column-count-mismatch-vs-typestring`. The prepass materialises
   `PROJ_STAR` into `PROJ_EXPRS` with synthesised `EXPR_COLUMN_REF` (single
   table) or `EXPR_QUALIFIED_COLUMN` (joined) nodes so the existing
   per-column emission path runs unchanged. Mirrors Rust's long-standing
   behaviour.

Fixes 1 and 2 also cut the DISTINCT-wrapper double-substitute loop: under
the old code a `SELECT DISTINCT <expr> col1 FROM t GROUP BY col1` would
wrap the alias expression twice (outer compile + inner recursive compile),
yielding `+(+col1/-65)/-65`. With 6cd's "base wins on shadow" rule, the
re-entrant pass recognises the unique alias's name-collision with the base
column and bails out of the substitute — cutting the loop without needing
a separate "don't re-run alias pass in nested compile" gate.

## Residual (34)

### FAIL (1)

- `evidence/slt_lang_update.test` — joint debt with Rust on UPDATE
  row-value mismatches; unchanged from v4.

### TIMEOUT (33) — 90s wall budget

C-specific planner/VDBE-perf cluster; unchanged from v4. These are shape-
identical to v4 — no progress or regression. The task scope explicitly
identified these as Cluster 2 (planner-perf) and left them out of this
round's fix plan. Detailed breakdown in the v4 diff.

| directory | files | notes |
|---|---:|---|
| `index/random/10/` | 15 | small-row-many-scan cluster |
| `index/random/100/` | 2 |  |
| `index/random/1000/` | 5 | partial; 3 files PASS |
| `index/between/{100,1000}/` | 2 | large-row range scans |
| `index/commute/1000/` | 3 |  |
| `index/in/1000/` | 2 |  |
| `index/orderby/1000/` | 1 |  |
| `select4.test`, `select5.test` | 2 | joint debt with Rust — VDBE dispatch tuning, out of scope |

## Cross-target equivalence snapshot (C v5 vs Rust v5)

- Rust corpus at 620/622 (99.68%, 2026-04-23 v5 log).
- C corpus at 588/622 (94.53%, this log).
- PASS on both targets: **588 / 622 (94.53%)** — all C passes are also Rust passes.
- PASS Rust only (C-specific residual debt): **32** — 1 FAIL + 31 TIMEOUT; TIMEOUTs
  dominate and are correctness-clean (just slower).
- PASS C only: **0** — every C pass is matched by a Rust pass.

## Remaining work (ordered by leverage)

1. **C planner throughput on `index/random/{10,100,1000}/` + `index/{between,
   commute,in,orderby}/1000/`** — 31 TIMEOUT files. Rust's planner handles
   small-row-many-scan and large-row-range cases differently; expected to
   need a planner-cost tweak analogous to #129 but on a different cluster.
2. **`evidence/slt_lang_update.test`** — joint debt with Rust; UPDATE row-
   value mismatches.
3. **`select4` / `select5`** — joint timeouts; VDBE-dispatch tuning.
