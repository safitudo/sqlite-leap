# Phase 9h harness — name-resolution error propagation

Phase 9h is the spec-pin fixture that closes the three cross-target error-
surface findings from the 2026-04-21 fuzz campaign
(`tests/fuzz/results/2026-04-21-README.md`). It is a spec-pin-only phase —
no new opcodes, no new invariants, no new grammar. The fixture's role is
to make the pin executable: every case must produce the same
`ENGINE_ERROR` kind (or alias-equivalent) on both the C and Rust builds.

## Bugs pinned

1. **Bug A — INSERT VALUES with a bare unresolved identifier.**
   `INSERT INTO t VALUES (x)` after `CREATE TABLE t(a INTEGER)`. Pre-fix
   leap-rust aborted (`SIGABRT` from `panic = abort` hitting an
   `.expect(...)` inside `resolve_outer_bare`). Leap-c correctly raised
   `ENGINE_ERROR EVAL_COLUMN_WITHOUT_TABLE`. The spec (Phase 2c-1,
   Amendment 2 in Phase 6j) pins `EVAL_COLUMN_WITHOUT_TABLE` as the
   condition for a bare ColumnRef in a no-table context; INSERT VALUES
   is a no-table context. Phase 9h adds the rule that **every
   ColumnRef-lowering site** must validate the name and surface a
   structured error, with no unchecked assertion fallback.

2. **Bug B — SELECT with an unresolved column under GROUP BY.**
   `SELECT i, SUM(v) FROM t GROUP BY k` where `i` is not a column of
   `t`. Leap-c raised `STORAGE_COLUMN_NOT_FOUND`; leap-rust aborted at
   the same `.expect(...)` site, reached via the
   `collect_bare_columns_not_in_group_by` → `compile_expression_scoped`
   path in `compile_grouped_aggregated`. Same spec fix as Bug A — the
   GROUP BY scan-emit path is a ColumnRef-lowering site and must
   validate before emitting.

3. **Bug C — Deep recursive CTE error-kind divergence.**
   `WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM c WHERE n < 1000000) SELECT COUNT(*) FROM c`.
   Leap-c trips the Phase 6bl 1000-iteration cap at runtime and raises
   `RUNTIME_RECURSIVE_CTE_LIMIT`. Leap-rust's engine driver did not
   implement the fixed-point loop end-to-end; the recursive reference
   compiled as an unknown table and raised `COMPILE_UNKNOWN_TABLE`.
   Phase 9h pins that a self-referencing recursive-CTE binding MUST
   surface `RUNTIME_RECURSIVE_CTE_LIMIT` regardless of whether the
   generator implements the fixed-point loop — a generator that
   cannot iterate must detect the self-reference at CTE-materialize
   time and raise the runtime-limit error directly (treating "no
   iteration possible" as "cap trivially exceeded on iteration 1").

## Cross-target comparison

Both builds must produce the SAME `ENGINE_ERROR` kind for every case.
The harness's error-alias layer
(`src-rust/src/harness.rs::error_name_aliases`,
`src-c/harness.c::error_name_aliases`) treats
`COMPILE_UNKNOWN_COLUMN` / `STORAGE_COLUMN_NOT_FOUND` as equivalent —
Bug B fixtures pin `STORAGE_COLUMN_NOT_FOUND` but the Rust target is
allowed to emit `COMPILE_UNKNOWN_COLUMN` and still pass.

## Invariants

`max_invariant=45` unchanged from Phase 6bu. No new opcodes, no new
type machinery. The fix is entirely in the compile-time and
engine-dispatch paths — how an unresolved name or unmaterialisable CTE
surfaces as an error.

## Rerun steps

```
src-c/bin/phase9h-test tests/cross-build/phase9h-name-resolution-errors.json
src-rust/target/release/phase9h-test tests/cross-build/phase9h-name-resolution-errors.json
```

Plus the fuzz re-run gate:

```
python3 tests/fuzz/sql/mutator.py \
  --harness src-rust/target/release/fuzz_exec \
  --seeds tests/fuzz/corpus/sql/valid \
  --out /tmp/fuzz/exec_rust_phase9h \
  --log tests/fuzz/results/2026-04-23-sql-exec-rust-phase9h.log \
  --duration-s 600 --seed 14
```

The post-fix Rust exec-fuzz crash count must be `0` over a 10-minute
smoke against seeds at `--seed=14` (same seed the 2026-04-21 campaign
used).
