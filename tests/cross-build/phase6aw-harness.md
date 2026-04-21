# Phase 6aw harness — PRAGMA core subset

Adds a narrow set of PRAGMAs for introspection + header-metadata read/write. One new reserved keyword: `KEYWORD_PRAGMA`. No new VDBE opcodes (PRAGMAs either read catalog state or set header bytes — both use existing mechanisms). `max_invariant=45` unchanged.

Gate: 9 fixtures green both targets. `SUMMARY phase=6aw target=<c|rust> passed=9 failed=0 total=9`.

### PRAGMAs supported in this phase

**Read-only introspection** (return rows like a SELECT):

- `PRAGMA table_info(<name>)` — 6 cols per row: `cid, name, type, notnull, dflt_value, pk`
- `PRAGMA index_list(<table>)` — 5 cols per row: `seq, name, unique, origin, partial`. `origin` is `"c"` for user-created, `"u"` for auto-unique, `"pk"` for auto-PK. `partial` always 0 (no partial indexes in v1).
- `PRAGMA index_info(<index>)` — 3 cols per row: `seqno, cid, name`
- `PRAGMA page_size` — returns the file page size (we use 4096). Read-only in v1.
- `PRAGMA page_count` — returns total pages in the DB file.

**Header-metadata read/write** (affect 4-byte header fields):

- `PRAGMA application_id [= <int>]` — read or set the application_id header (offset 68 of SQLite file).
- `PRAGMA user_version [= <int>]` — read or set the user_version header (offset 60 of SQLite file).

**Accept-and-ignore**:

- `PRAGMA foreign_keys [= <bool>]` — accepted, stored, returned, but has no runtime effect (FKs not enforced in v1).

### Unknown-PRAGMA behavior

Unknown PRAGMA name → **silent no-op**, zero rows returned, no error. Matches SQLite's `PRAGMA nonexistent_pragma` behavior. This is critical for corpus compatibility — many tests use PRAGMAs we don't implement; silently accepting them (with no-op semantics) is much better than erroring.

### Syntax notes

- `PRAGMA <name>;` — read form.
- `PRAGMA <name>(<arg>);` — read form with a function-like argument (used by table_info / index_list / index_info).
- `PRAGMA <name> = <value>;` — write form.
- `<value>` in the write form can be an integer literal or a bare identifier (`ON`/`OFF`/`YES`/`NO` variants). For v1 just accept integer + bare identifier; fold `ON`/`YES`/`TRUE` → 1 and `OFF`/`NO`/`FALSE` → 0.

### Implementation hints

- Parse PRAGMAs as a top-level statement (sibling to SELECT/INSERT). New `Ast::Pragma { name, arg, value }` node.
- At compile: for KNOWN pragmas, emit the appropriate opcode sequence (schema walk for table_info; header-field load for page_size; register-store for user_version; etc.). For UNKNOWN: emit a trivial "no-op, return zero rows" program.
- For `table_info`: walk the catalog's column list and emit one ResultRow per column with the 6-tuple.
- For `index_list` / `index_info`: similar walks over the index catalog.
- For `application_id` / `user_version`: read from or write to the SQLite file header's fixed offsets. On in-memory DBs, use a per-Database field; persistence happens on disk-backed DBs.
- For `foreign_keys`: store a bool in the Database state; never consulted elsewhere.
- Error: `PRAGMA table_info(unknown_table)` → 0 rows, NOT an error.

### Spec-ambiguity

- `index_list` column order within the result: SQLite returns newest-first (seq 0 = most-recently-created index). Test fixture follows this.
- `dflt_value` in `table_info`: SQLite returns the original SQL text of the default expression, quoted (e.g. `'x'` for `DEFAULT 'x'`). We follow this convention. For numeric defaults, SQLite returns the bare numeric text (`0`, `-1`). For NULL/no-default: NULL.
