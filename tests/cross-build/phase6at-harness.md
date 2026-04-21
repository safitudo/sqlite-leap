# Phase 6at harness — CHECK constraints

Extends CREATE TABLE column-constraint and table-constraint grammar with `CHECK (expr)`. Evaluated on INSERT and UPDATE; failure raises `RUNTIME_CHECK_CONSTRAINT_FAILED`. One new reserved keyword `KEYWORD_CHECK`. No new VDBE opcodes (expression-compile machinery reused from WHERE).

Gate: 8 fixtures green both targets. `SUMMARY phase=6at target=<c|rust> passed=8 failed=0 total=8`.

### Grammar extension

```
column-constraint := <existing> | KEYWORD_CHECK LPAREN expression RPAREN
table-constraint  := <existing> | KEYWORD_CHECK LPAREN expression RPAREN
```

A column-level CHECK appears after a column-def; a table-level CHECK appears in the table's constraint list after all column-defs.

### Semantics

- On every INSERT and UPDATE, evaluate each CHECK expression against the resulting row (new values substituted).
- The expression is evaluated with the same semantics as WHERE: result is boolean (TRUE, FALSE, NULL).
  - TRUE  → passes
  - NULL  → **passes** (SQLite semantics: CHECK passes unless strictly FALSE)
  - FALSE → fails with `RUNTIME_CHECK_CONSTRAINT_FAILED { table, constraint_index }`
- All CHECK constraints on a table must pass; evaluation order is declaration order; first failing constraint aborts the statement.
- Column-level CHECK may reference any column of the row (not only its own column).
- Expression constraints: no subqueries, no aggregates, no cross-row refs (same as generated columns in 6bj).

### Errors

- `RUNTIME_CHECK_CONSTRAINT_FAILED { table, constraint_index }` — one (zero-based) index per CHECK as declared.

### Implementation

- Catalog: extend `TableDef` with `checks: Vec<AstExpr>` (ordered by declaration).
- INSERT/UPDATE compile: after register assembly for the new row, for each CHECK expression, emit expression evaluation against row registers; on FALSE, jump to an error-emit block; on TRUE or NULL, fall through.
- Abort-on-fail uses existing error-emit path (shared with NOT NULL / UNIQUE).

### Non-goals (v1)

- `CONSTRAINT <name> CHECK (…)` — named constraint prefix is accepted in parse but the name is not retained for error reporting (error reports index only). `KEYWORD_CONSTRAINT` is an existing-or-new keyword depending on current table-constraint grammar.
- CHECK referencing `sqlite_master` or other tables — defer (tied to subquery in CHECK; out of scope).
- Deferred CHECK (after statement) — SQLite does not support this either; we match.
