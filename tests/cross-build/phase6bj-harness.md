# Phase 6bj harness — GENERATED columns (virtual only)

Extends CREATE TABLE column-def with a computed-column form: `<name> <type> [ GENERATED ALWAYS ] AS ( <expr> ) [ VIRTUAL ]`. Virtual (not stored); value computed on every read from the expression over the row's other columns.

One new reserved keyword `KEYWORD_GENERATED`. (`ALWAYS`, `AS`, `VIRTUAL` — some already reserved; `AS` is, others may need adding.) One new runtime error `RUNTIME_CANNOT_INSERT_INTO_GENERATED_COLUMN`. No new VDBE opcodes (expression-compile machinery from SELECT is reused).

Gate: 7 fixtures green both targets. `SUMMARY phase=6bj target=<c|rust> passed=7 failed=0 total=7`.

### Grammar extension

```
column-def := IDENTIFIER [ type-decl ] ( column-constraint | generated-clause )*
generated-clause := [ KEYWORD_GENERATED KEYWORD_ALWAYS ] KEYWORD_AS LPAREN expression RPAREN [ KEYWORD_VIRTUAL | KEYWORD_STORED ]
```

`STORED` is accepted-and-rejected in v1 (see non-goals). `VIRTUAL` is optional and the default.

### Semantics

- A generated column's declared type is recorded in catalog but NO STORAGE SLOT is allocated.
- INSERT: the tuple must NOT provide a value for the generated column. If an INSERT explicitly names the generated column with a value → `RUNTIME_CANNOT_INSERT_INTO_GENERATED_COLUMN`.
- SELECT: when projecting a generated column, evaluate its stored expression against the row's other columns. Cost is per-read; no caching.
- WHERE / ORDER BY / GROUP BY references to a generated column: inline the expression at compile time.
- UPDATE: generated column values are recomputed on next read; SET cannot target a generated column (same error as INSERT).

### Expression constraints

- The generated expression must reference only other columns of the SAME row (no subqueries, no cross-row references, no aggregates).
- No recursive references (a generated column cannot reference another generated column that references it).

### Errors

- `RUNTIME_CANNOT_INSERT_INTO_GENERATED_COLUMN { column }` — INSERT/UPDATE targeting a generated column.
- `COMPILE_GENERATED_COLUMN_RECURSIVE { column }` — reserved for the cycle detector; not fixture-tested in v1.

### Implementation

- Catalog: extend `ColumnDef` with `generated: Option<GeneratedDef>`, where `GeneratedDef { expr: AstExpr, virtual_or_stored: Virtual }`.
- INSERT compile: skip generated columns in the implicit column-list for unspecified-column INSERTs; raise runtime error if generated columns appear in explicit column-list.
- SELECT compile: when emitting a column projection, if column is generated, substitute its expression (with table-alias-qualified references). For `SELECT *`, project generated columns like any other column (expression-evaluated).
- Storage layout: rows have fewer serial-type slots than total columns (the generated slots are absent). The column → slot mapping skips generated columns.
- Row decoder: when rebuilding a row for read, for each generated column, evaluate its expression over the other decoded values; fill the output register with the result.

### Non-goals (v1)

- `STORED` generated columns (values persisted, precomputed on insert) — permanent non-goal; reject with parse error at v1 (or just do not accept STORED keyword).
- Generated column in a UNIQUE constraint — defer.
- Generated column in PRIMARY KEY — defer.
- Generated column in index (`CREATE INDEX ON t(generated_col)`) — would require index-maintenance extension; defer.
