# Phase 6am harness — NOT NULL column constraint

New runtime error `RUNTIME_NOT_NULL_VIOLATION { table, column }`. Column-schema flag `not_null: bool`. INSERT and UPDATE check.

Gate: 7 fixtures green both targets. `SUMMARY phase=6am target=<c|rust> passed=7 failed=0 total=7`.

Notes:
- Error fires AFTER default evaluation — so `NOT NULL DEFAULT 0` accepts omitted columns.
- `NOT NULL DEFAULT NULL` rejects omission (default is literally NULL, so NULL-check fires).
- UPDATE path must also check.
- Error kind must be identical between C and Rust — spec pins `RUNTIME_NOT_NULL_VIOLATION`.
