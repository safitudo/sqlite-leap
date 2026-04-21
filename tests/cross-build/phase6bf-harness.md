# Phase 6bf harness — ALTER TABLE subset (RENAME TABLE, RENAME COLUMN, ADD COLUMN)

Parser + catalog mutator. Three ALTER TABLE variants. No new VDBE opcodes (all work happens in the schema/catalog layer via existing opcode primitives). `max_invariant=45` unchanged. One new reserved keyword: `KEYWORD_ALTER`. (`RENAME`, `TO`, `ADD`, `COLUMN` — some already reserved; check and add.)

Gate: 9 fixtures green both targets. `SUMMARY phase=6bf target=<c|rust> passed=9 failed=0 total=9`.

### Grammar

```
alter-table-stmt := KEYWORD_ALTER KEYWORD_TABLE IDENTIFIER alter-action
alter-action := KEYWORD_RENAME KEYWORD_TO IDENTIFIER
              | KEYWORD_RENAME [ KEYWORD_COLUMN ] IDENTIFIER KEYWORD_TO IDENTIFIER
              | KEYWORD_ADD [ KEYWORD_COLUMN ] column-def
```

The `COLUMN` keyword is optional in the RENAME / ADD forms (matches SQLite).

### Semantics

**RENAME TABLE**:
- Verify table exists. Missing → `COMPILE_UNKNOWN_TABLE`.
- Verify new name is not already taken. Collision → `COMPILE_DUPLICATE_TABLE`.
- Update the catalog entry: rename the table.
- Update any index entries that reference the old table name.
- Update any view entries that reference the old table in their stored SELECT (v1 simplification: may skip view-text rewrite and rely on view re-resolution at USE time; if fixtures break, do the rewrite).
- No data movement required (rows are keyed by rowid, not table name).

**RENAME COLUMN**:
- Verify table exists. Missing → `COMPILE_UNKNOWN_TABLE`.
- Verify old column name exists. Missing → `COMPILE_UNKNOWN_COLUMN`.
- Update the catalog's column-list.
- Update any index entries that reference the renamed column.
- No data movement.

**ADD COLUMN**:
- Verify table exists.
- Verify the new column name is not already used. Duplicate → `COMPILE_DUPLICATE_COLUMN`.
- Accept the full column-def grammar (type, NOT NULL, DEFAULT, etc.) — reuses 6al / 6am / 6ar machinery.
- Update the catalog's column-list (append at end).
- For existing rows: treat the new column as NULL (SQLite v1 semantics; later reads synthesize NULL for the missing slot). If DEFAULT is declared, existing rows read back the DEFAULT value (not actually stored).
- No data migration — lazy NULL-fill / DEFAULT-fill on read.

### Errors

- `COMPILE_UNKNOWN_TABLE` — RENAME or ADD on a missing table.
- `COMPILE_UNKNOWN_COLUMN` — RENAME COLUMN of a non-existent source column.
- `COMPILE_DUPLICATE_TABLE` — RENAME TO a name that already exists.
- `COMPILE_DUPLICATE_COLUMN` — ADD COLUMN of a name already in the table.

### Non-goals (v1)

- `ALTER TABLE … DROP COLUMN` — SQLite 3.35+; deferred.
- `ALTER TABLE … RENAME INDEX` — not in SQLite grammar; permanent non-goal.
- `ALTER TABLE … ALTER COLUMN …` (change type) — SQLite doesn't support this at all; permanent non-goal.
- ADD COLUMN with `PRIMARY KEY` or `UNIQUE` constraint — SQLite rejects these in ALTER (would require rewriting all existing rows). Permanent non-goal for v1.
- ADD COLUMN with CHECK constraint — deferred to post-6at.

### Implementation hints

- The ADD COLUMN lazy-NULL strategy: when the reader walks a row's serial-type array, if the row has FEWER types than the current column count, synthesize NULL (or DEFAULT) for the missing trailing columns. This is already how SQLite stores the "added column after existing rows" case. Existing row-decoder paths may need to be relaxed to accept short serial-type arrays.
- For RENAME: edit the catalog and any derived lookup tables. Do NOT rewrite row data.
- For in-memory DBs: catalog is in-memory state; trivial to mutate.
- For disk-backed DBs: the CREATE TABLE SQL string stored in sqlite_schema gets rewritten. On reopen, parse the new SQL.
