# Phase 6ax harness — sqlite_master / sqlite_schema introspection

Adds two read-only virtual tables with identical content: `sqlite_master` and `sqlite_schema`. Both expose the catalog: one row per user-created table, index, view, and trigger. Read-only from v1 (writes → `RUNTIME_READONLY_TABLE`). No new VDBE opcodes (read-path reuses existing table-cursor machinery against a synthesized row stream).

Gate: 7 fixtures green both targets. `SUMMARY phase=6ax target=<c|rust> passed=7 failed=0 total=7`.

### Schema

Both tables present as:

```
CREATE TABLE sqlite_master (
  type    TEXT,     -- 'table' | 'index' | 'view' | 'trigger'
  name    TEXT,     -- object name
  tbl_name TEXT,    -- table this object belongs to (for tables/views: == name)
  rootpage INTEGER, -- storage root page number; 0 for views and auto-indexes in v1
  sql     TEXT      -- original CREATE text, NULL for implicit objects (auto-indexes)
);
```

`sqlite_schema` is an alias — same rowset, same column layout. Either name works in any SELECT / FROM / subquery.

### Semantics

- The row set is computed at query start from the current catalog snapshot — not materialized on disk.
- Ordering: no implicit order. Tests must use `ORDER BY` for determinism.
- `sql` column stores the original CREATE statement, best-effort canonicalized: whitespace collapsed, keywords uppercased, column-type retained verbatim. Implicit objects (auto-indexes from PRIMARY KEY / UNIQUE) have `sql = NULL`.
- Rows for the introspection tables themselves are NOT included (they are not user-created).
- `rootpage` reports the actual b-tree root for tables/indexes; views and auto-indexes return 0.
- The table supports full SELECT grammar including WHERE, ORDER BY, JOIN against user tables, subqueries.
- Write attempts: INSERT / UPDATE / DELETE → `RUNTIME_READONLY_TABLE { table: "sqlite_master" }`.
- DROP TABLE sqlite_master / sqlite_schema → `RUNTIME_READONLY_TABLE`.

### Errors

- `RUNTIME_READONLY_TABLE { table }` — any write to `sqlite_master` or `sqlite_schema`.

### Implementation

- Catalog: a synthetic TableDef named `sqlite_master` is registered at database-open time. Its cursor-open path routes to a catalog-enumeration iterator rather than a b-tree cursor.
- The iterator yields `(type, name, tbl_name, rootpage, sql)` tuples over the catalog's current table/index/view/trigger collections in insertion order (caller can ORDER BY for determinism).
- `sqlite_schema` is registered as an alias pointing at the same TableDef.
- Write opcodes (InsertRow / UpdateRow / DeleteRow) check a `readonly: bool` flag on TableDef and raise `RUNTIME_READONLY_TABLE` before any storage path.

### Non-goals (v1)

- Write support (SQLite allows some writes with `PRAGMA writable_schema=ON` — defer).
- `sqlite_temp_master` / `sqlite_temp_schema` — defer (we have no temp DB concept yet).
- `sqlite_stat1` etc. — ANALYZE support is a separate phase.
- `partitioned` view aliases (some SQLite builds expose more introspection tables) — defer.
