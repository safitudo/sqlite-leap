# Phase 6ar harness — INTEGER PRIMARY KEY + AUTOINCREMENT

Column becomes a rowid alias. Values aren't stored in the row body; the b-tree key IS the column's value. `SELECT *` must project rowid as this column. **Critical for bidirectional file-format compat with mainline SQLite.**

Gate: 9 fixtures green both targets. `SUMMARY phase=6ar target=<c|rust> passed=9 failed=0 total=9`.

Notes:
- Only applicable to `INTEGER`-typed columns; TEXT/REAL PK rejected.
- AUTOINCREMENT only valid after PRIMARY KEY.
- On read: detect rowid-alias from schema (parse declared column type === INTEGER and has `PRIMARY KEY` clause). Project rowid as that column's value.
- On write: store rowid; do NOT store the alias column in row body; the INSERT cost drops from N-columns to N-1.
- INSERT NULL for PK → auto-assign (matches SQLite behavior).
- INSERT explicit conflicting value → `STORAGE_UNIQUE_VIOLATION` (unified with 9g's PK-duplicate error name as of 2026-04-20; earlier drafts used `STORAGE_PRIMARY_KEY_CONFLICT`).
- Non-INTEGER `PRIMARY KEY` (e.g. `TEXT PRIMARY KEY`) is ACCEPTED via the 9f auto-index path — NOT rejected. Only `INTEGER PRIMARY KEY` triggers the rowid-alias optimization.
- AUTOINCREMENT: rowid = max(max(existing rowid), sqlite_sequence.seq) + 1. Preserve across DELETE. For v1 you may use an in-memory monotonic counter per table (don't require the `sqlite_sequence` schema table — note this is a v1 simplification, but must be named in the report).

After 6ar lands, smoke test should pass: SQLite writes a file with INT PK + REAL + INDEX, LEAP reads it back without error.
