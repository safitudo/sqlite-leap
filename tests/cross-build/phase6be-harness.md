# Phase 6be test harness — INSERT INTO <table> <select-statement>

Extends INSERT with SELECT-as-source (in addition to existing VALUES form). Reuses existing `OP_INSERT` and SELECT machinery. `max_invariant=43` unchanged.

## Invocation

`<harness-binary> <path-to-phase6be.json>`

Generated into `src-{lang}/bin/phase6be-test`.

## Output

`SUMMARY phase=6be target=<c|rust|wasm> passed=<int> failed=<int> total=<int>`

## Gate

10 cases green both targets. Byte-identical cross-build.

Corpus win: projected +30K records across 4 index subcorpora (orderby_nosort, between, in, delete), each blocked in test-setup by `INSERT INTO ... SELECT FROM ...` shape.

## Implementation notes

- Parser: extend INSERT production to accept either `VALUES row-list` OR `select-statement` after the table (+ optional column list).
- AST: `Insert` node's `source` field becomes a sum type: `Values(rows)` | `SelectSource(select_stmt)`.
- Compile: for SelectSource, compile the SELECT's body loop but swap the terminal `OP_RESULT_ROW` for `OP_INSERT` targeted at the (already-opened) target-table write cursor.
- Column-count check: project-count vs target-column-count mismatch raises `COMPILE_INSERT_COLUMN_COUNT_MISMATCH { expected, got }` — reuses existing error kind.
- Self-insert semantics: snapshot-at-start. Generators must buffer rows via the sorter (`OP_SORTER_OPEN` / `OP_SORTER_INSERT` / `OP_SORTER_SORT` / iterate) before emitting INSERTs, to avoid scan/insert b-tree disturbance. Both generators must choose the SAME strategy for byte-identical self-insert output.
- Explicit column list (`INSERT INTO u (b, a) SELECT x, y FROM t`) — reuses the existing INSERT-VALUES column reorder logic.

## Cross-build risks

- **Self-insert b-tree stability**: streaming inserts during a scan of the same table may or may not cause page-split-induced re-reads. Buffer via sorter to eliminate this. MANDATORY for byte-identical output.
- **Error kind**: `COMPILE_INSERT_COLUMN_COUNT_MISMATCH` already exists for INSERT VALUES — reuse exactly. Do not introduce a new error for the SELECT-source variant.
- **No VALUES keyword**: the SELECT form is just `INSERT INTO t SELECT ...` — no VALUES keyword at all. Don't accidentally require VALUES.
