# Phase 6ac harness — CREATE VIEW / DROP VIEW (read-only)

Parser + compile + catalog extension. No new VDBE opcodes. `max_invariant=45` unchanged. Two new reserved keywords: `KEYWORD_VIEW`. (`CREATE`, `DROP`, `IF`, `EXISTS`, `NOT`, `AS` already reserved.)

Gate: 11 fixtures green both targets. `SUMMARY phase=6ac target=<c|rust> passed=11 failed=0 total=11`.

Notes:
- A view is a stored SELECT statement. References to the view name in a FROM clause substitute the SELECT at compile time (macro expansion).
- Optional column-list: `CREATE VIEW v (x, y) AS SELECT a, b FROM t;` renames projected columns. Column count MUST match the select's output arity → `COMPILE_VIEW_COLUMN_COUNT_MISMATCH` otherwise.
- Views stored in the catalog with type='view' and the original SQL text preserved.
- `IF NOT EXISTS` clause: skip silently if a view with that name already exists. Without it: `COMPILE_DUPLICATE_VIEW`.
- `DROP VIEW [IF EXISTS] <name>`: remove the view from the catalog. Without IF EXISTS, missing view → `COMPILE_UNKNOWN_VIEW`.
- Read-only: INSERT/UPDATE/DELETE on a view → `COMPILE_VIEW_NOT_WRITABLE` (v1; writable views via INSTEAD OF triggers are deferred).
- View resolution: compiler checks view catalog BEFORE table catalog (views can shadow tables? — NO, views and tables share a namespace; a name collision raises `COMPILE_DUPLICATE_VIEW` or `COMPILE_DUPLICATE_TABLE` at CREATE time).
- Dropping a view referenced by another view should cascade-fail at the outer view's next compile (not at DROP time) → flag as `COMPILE_UNKNOWN_TABLE` (or `COMPILE_UNKNOWN_VIEW`, implementation-defined for v1; fixture doesn't exercise).
- View SELECT may reference aggregates, joins, expressions — anything a regular SELECT can contain.
- The view's SELECT is parsed and stored as AST; re-evaluated on every reference. No caching of result rows.

Implementation hints:
- At CREATE VIEW: parse the SELECT subtree, keep it in catalog. Don't resolve column refs yet (lazy — resolved at USE site).
- At FROM reference to a view name: substitute the view's SELECT AST into the query, then compile normally. Handle potential infinite recursion (view A references view B references view A) → `COMPILE_VIEW_RECURSIVE` (not fixture-tested in v1; gracefully bail after depth >= 16).
- At DROP VIEW: remove from catalog. Existing prepared statements that referenced the view become stale (not a problem for our single-statement runner).
- TEMP VIEW: accept but ignore the TEMP flag in v1 (persists identically).
