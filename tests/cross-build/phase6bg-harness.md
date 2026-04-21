# Phase 6bg harness — RETURNING clause on INSERT / UPDATE / DELETE

Parser + compile extension. After the DML operation, project a row per affected row (like a SELECT result set). No new VDBE opcodes — reuses existing ResultRow emission. `max_invariant=45` unchanged. One new reserved keyword: `KEYWORD_RETURNING`.

Gate: 8 fixtures green both targets. `SUMMARY phase=6bg target=<c|rust> passed=8 failed=0 total=8`.

### Grammar

```
insert-stmt := existing-insert [ returning-clause ]
update-stmt := existing-update [ returning-clause ]
delete-stmt := existing-delete [ returning-clause ]

returning-clause := KEYWORD_RETURNING projection-list
```

Where `projection-list` is the same as SELECT's: `STAR`, or `expression ( AS alias )? ( COMMA expression ( AS alias )? )*`.

### Semantics

**INSERT RETURNING**:
- For each inserted row, emit a result row with the RETURNING projection evaluated over the just-inserted row's column values.
- For multi-row INSERT, emit one result row per inserted tuple.
- `RETURNING *` = all columns of the target table, in declared order.
- Expressions can reference table columns (post-insert values — defaults applied, autoincrement-assigned rowid visible).

**UPDATE RETURNING**:
- For each updated row, emit one result row with RETURNING evaluated over the POST-UPDATE row values.
- `RETURNING *` = all columns of the target table.
- Rows that match WHERE but are unchanged by the UPDATE SET still emit (unchanged for this v1 — SQLite spec is clear: RETURNING fires for every row that matched WHERE).

**DELETE RETURNING**:
- For each deleted row, emit one result row with RETURNING evaluated over the PRE-DELETE row values (they're about to be gone).
- `RETURNING *` = all columns.

### Error surface

- `PARSE_UNEXPECTED_TOKEN` if RETURNING appears on a non-DML statement.
- Column references in RETURNING that don't resolve → `COMPILE_UNKNOWN_COLUMN` (reuses existing error).

### Implementation

- AST: add `returning: Option<Vec<Projection>>` to Insert / Update / Delete AST nodes.
- Compile: after the existing DML opcodes emit, insert a ResultRow emission per affected row. The row-values come from the same registers the DML path already has loaded.
- For INSERT: emit ResultRow after each InsertRow/per-tuple path.
- For UPDATE: emit ResultRow inside the per-row update loop.
- For DELETE: emit ResultRow BEFORE the row-delete (capture pre-delete values).

### Non-goals (v1)

- RETURNING on INSERT ... ON CONFLICT DO UPDATE — reserved for UPSERT phase; may defer (fixture doesn't exercise).
- Subqueries / CTEs inside RETURNING expressions — accept if free from the existing expression-parsing path.
