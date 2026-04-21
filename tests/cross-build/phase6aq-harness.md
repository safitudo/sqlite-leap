# Phase 6aq harness — NATURAL JOIN + JOIN USING

Parser + compile desugar. Both NATURAL JOIN and USING (col-list) desugar at parse/compile time into JOIN ON equivalents. No new VDBE opcodes. `max_invariant=45` unchanged. Two new reserved keywords: `KEYWORD_NATURAL`, `KEYWORD_USING`.

Gate: 8 fixtures green both targets. `SUMMARY phase=6aq target=<c|rust> passed=8 failed=0 total=8`.

Notes:

- **NATURAL JOIN**: auto-JOIN-ON-equality on every column that appears by name in both tables. Compile-time determine the shared column list → emit `ON t1.a = t2.a AND t1.b = t2.b AND ...`.
- **NATURAL JOIN with no shared columns**: degenerates to a cross-product (desugared to `ON 1`). Matches SQLite.
- **`JOIN ... USING (col1, col2)`**: equivalent to `JOIN ... ON t1.col1 = t2.col1 AND t1.col2 = t2.col2` where the `col` references resolve to the shared column. Unlike ON-join, the USING columns are projected once (coalesced) rather than twice — but for our purposes the fixture queries use explicit column references so the projection-once rule isn't load-bearing.
- **LEFT variant**: `NATURAL LEFT JOIN`, `LEFT JOIN ... USING (…)` — both inherit the existing LEFT-join NULL-emission semantics from 6e.
- **USING column not found in BOTH tables**: `COMPILE_USING_COLUMN_NOT_FOUND`. (SQLite's exact error is "cannot join using column <x> — column not present in both tables"; we just raise the generic name.)
- **SQLite's USING column projection-once rule**: `SELECT * FROM t1 JOIN t2 USING (id)` returns `id` ONCE in the output (not twice). For v1 if `*`-projection is used, implement this; if the test uses explicit column names (most fixtures do), the rule is dormant.

Implementation hint:

- Parse `NATURAL` as a modifier on the JOIN-keyword stream. At parse-end, mark the JoinedSource with a `natural: bool` flag.
- Parse `USING (col, col, …)` after the right-side table reference. Mark with a `using: Option<Vec<ColumnName>>`.
- At compile: resolve the shared column list (NATURAL) or the explicit USING list. Emit a synthesized ON-expression: `t1.col1 = t2.col1 AND t1.col2 = t2.col2 AND …`. If list is empty (NATURAL no-shared), emit `ON 1` (always-true).
- The rest is 6e's JOIN ON machinery.
