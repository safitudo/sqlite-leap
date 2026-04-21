# Phase 6au harness — multi-column table-level PRIMARY KEY

Extends table-constraint grammar with `PRIMARY KEY (col1, col2, …)` in the table-constraint list. Composite PK enforces uniqueness of the tuple and creates an auto-index on the composite key. Uses existing UNIQUE enforcement path (9g) — composite PK = composite UNIQUE + NOT NULL on each member.

Gate: 7 fixtures green both targets. `SUMMARY phase=6au target=<c|rust> passed=7 failed=0 total=7`.

### Grammar extension

```
table-constraint := <existing>
                  | KEYWORD_PRIMARY KEYWORD_KEY LPAREN column-name ( COMMA column-name )* RPAREN
```

Single-column column-level `PRIMARY KEY` (6ar) is unchanged. Single-column table-level PK should also be accepted via this rule (list of one).

### Semantics

- Composite PK imposes:
  - Each PK column is implicitly `NOT NULL` (matches SQLite; NULL in any PK column → `RUNTIME_NOT_NULL_VIOLATION`, using column name of first NULL member).
  - The tuple of PK columns must be unique across the table → duplicate raises `RUNTIME_UNIQUE_VIOLATION { table, columns }`.
- Auto-created index: name `sqlite_autoindex_<table>_1`, over the PK columns in declaration order. Used by 9d range-lookup / ORDER BY when WHERE constrains the PK.
- Only one PRIMARY KEY clause per table is permitted. Combining with a column-level `PRIMARY KEY` → `COMPILE_MULTIPLE_PRIMARY_KEYS`.
- Composite PK is NOT the `rowid` alias (only single-column INTEGER PRIMARY KEY is the rowid alias, per 6ar). The table is a regular rowid table with a unique-index on the PK columns.

### Errors

- `COMPILE_MULTIPLE_PRIMARY_KEYS { table }` — more than one PRIMARY KEY clause (column-level or table-level) in the same CREATE TABLE.
- `COMPILE_UNKNOWN_COLUMN { table, column }` — PK column-name list references a column not in the CREATE TABLE (existing error, reused).
- `RUNTIME_NOT_NULL_VIOLATION { table, column }` — NULL in any PK member (existing error, reused).
- `RUNTIME_UNIQUE_VIOLATION { table, columns }` — **new canonical error kind for composite-PK uniqueness violations**. Split from the pre-existing `STORAGE_UNIQUE_VIOLATION { index, key }`: the storage-layer error continues to fire for non-PK UNIQUE index violations, while the new runtime-layer `RUNTIME_UNIQUE_VIOLATION` fires when the violating UNIQUE index's columns exactly match the table's composite primary_key_columns list. Both generators (C and Rust) will independently hit this split; canonize the new variant.

### Implementation

- Catalog: `TableDef.primary_key: Option<Vec<ColumnId>>`.
- CREATE TABLE compile: when a table-level PK is present, set `primary_key` and, for each member, mark `column.not_null = true` unless already so.
- Index creation: auto-create a UNIQUE index over the PK columns named `sqlite_autoindex_<table>_1`; indistinguishable from an explicit `CREATE UNIQUE INDEX`.
- INSERT/UPDATE: existing 9g UNIQUE enforcement runs over the composite-index — no new code path.
- Query planner: composite PK index participates in 9d lookups exactly as other composite indexes.

### Non-goals (v1)

- `WITHOUT ROWID` tables (composite PK becomes the row's key) — defer. A composite-PK table in v1 is always a rowid table with a unique index.
- `ASC` / `DESC` per PK member in the table-level list — accept-and-ignore in v1.
- Composite foreign-key referencing a composite PK — defer (FKs are a separate phase).
