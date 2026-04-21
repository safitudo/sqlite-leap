# Phase 6bi harness — STRICT tables

Extends CREATE TABLE with an optional `STRICT` table-modifier. STRICT tables enforce column types at INSERT/UPDATE time (matching SQLite 3.37+). One new reserved keyword `KEYWORD_STRICT`. One new error: `RUNTIME_STRICT_TYPE_MISMATCH`. No new VDBE opcodes (runtime check fires from InsertRow/UpdateRow storage paths).

Gate: 8 fixtures green both targets.

### Grammar extension

```
create-table-stmt := <existing> [ KEYWORD_STRICT ]
```

After the closing RPAREN of the column-list, an optional `STRICT` keyword marks the table strict. Catalog stores `strict: bool`.

### STRICT type rules

The column-type declaration is taken literally (not via affinity mapping). Allowed types in STRICT tables:

- `INT` / `INTEGER` — INTEGER values only.
- `REAL` — REAL values only; **INTEGER → REAL widening is accepted** (integer stored as real).
- `TEXT` — TEXT values only.
- `BLOB` — BLOB values only.
- `ANY` — any type accepted (no enforcement for that column).

NULL is always accepted unless NOT NULL is also declared.

Mismatch at INSERT / UPDATE → `RUNTIME_STRICT_TYPE_MISMATCH { table, column, expected_type, actual_type }`.

### Non-strict behavior unchanged

Non-STRICT tables retain SQLite's classic type-affinity permissiveness: `INSERT INTO t(int_col) VALUES ('42')` stores the integer 42 via coercion. STRICT tables disable this coercion.

### Implementation hints

- CREATE TABLE parser: after closing RPAREN, peek for `STRICT` (bare identifier / contextual keyword). If present, set `table.strict = true`.
- Catalog: extend `TableDef` with `strict: bool` and per-column `declared_type: StrictType` (when parent table is strict, enforce; when not, affinity-only).
- Storage insert/update: if table is strict, validate each value against its column's strict type before writing. On mismatch, raise the new error.
- INTEGER → REAL widening: if actual is INTEGER and column is REAL, coerce to REAL and accept. No other cross-type coercion in STRICT mode.

### Non-goals (v1)

- Strict table enforcement on bulk `INSERT INTO t SELECT …` — accept if flowing through the same code path; otherwise fixture covers row-at-a-time.
- Dynamic type change of a STRICT column via ALTER — ALTER TABLE ADD COLUMN with strict enforcement is inherited from the table's existing strictness.
