---
name: storage/foreign-keys
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /parts/core/master.md
  - /parts/storage/master.md
  - /parts/storage/parts/btree/master.md
  - /parts/storage/parts/index/master.md
emits:
  c:      { path: src-c-v2/storage/foreign_keys.c, headers: [src-c-v2/storage/foreign_keys.h] }
  rust:   { path: src-rust-v2/storage/foreign_keys.rs }
  zig:    { path: src-zig-v2/storage/foreign_keys.zig }
  go:     { path: src-go-v2/storage/foreign_keys.go }
  python: { path: src-python-v2/storage/foreign_keys.py }
---

# Part: storage/foreign-keys

Foreign-key constraint enforcement. Reference: sqlite.org/foreignkeys.html
(published — allowed input). Off by default; turned on by
`PRAGMA foreign_keys = ON` per connection. The PRAGMA toggle is
**connection-scoped**, takes effect outside any active transaction,
and is silently ignored mid-transaction (mainline behavior).

## Schema records

Each `TableSchema` carries a list of FK declarations:

```
ForeignKey {
  id:               u32              // unique within child table
  child_columns:    [ColumnIdx]      // FK column tuple in child
  parent_table:     TableName
  parent_columns:   [ColumnIdx]      // referenced cols in parent;
                                     // empty ⇒ parent's PK
  on_delete:        Action           // NoAction | Restrict | SetNull | SetDefault | Cascade
  on_update:        Action           // same enum
  match_kind:       MatchKind        // Simple (default) | Full | Partial — only Simple supported in v1
  deferrable:       bool
  initially_deferred: bool
}
```

Mismatched arity (`len(child_columns) != len(parent_columns)`) is a
DDL error at `CREATE TABLE` time: `SCHEMA_FK_ARITY_MISMATCH`.

## Action semantics

| Action      | On parent DELETE                              | On parent UPDATE of referenced cols           |
|-------------|-----------------------------------------------|------------------------------------------------|
| NoAction    | check at end of statement (or commit if deferred); raise if violation | same |
| Restrict    | check **immediately**; raise even if deferred | same |
| SetNull     | child columns set to NULL                     | same |
| SetDefault  | child columns set to declared DEFAULT (or NULL if no default) | same |
| Cascade     | child rows deleted                            | child columns updated to new parent values     |

`SetNull` / `SetDefault` / `Cascade` rewrites are performed inside
the same transaction; they trigger the **child's** triggers (if/when
triggers land) and child-side FK checks (cascade can chain).

## State machine — per statement

```
START_STMT:
  pending_violations := []          // immediate-mode FK deferred to end-of-stmt
  cascade_queue     := []           // (action, child_tuple) pairs
GO:
  on each row mutation by the executing statement:
    if parent-side change:
      for each inbound FK referencing this parent row:
        apply Action (Cascade / SetNull / SetDefault) → enqueue child mutations
        Restrict → check immediately, raise on violation
        NoAction → record violation candidate; re-check at END_STMT
    if child-side change (INSERT or UPDATE introducing FK row):
      lookup parent in parent_table by parent_columns;
      missing → record violation candidate (NoAction) or raise (Restrict)
  drain cascade_queue to fixpoint or until cycle-cap exceeded.
END_STMT:
  for each violation candidate:
    re-check parent existence;
    if still violating and not deferred → raise ConstraintForeignKey
    if deferred → push into transaction.deferred_violations
COMMIT:
  if transaction.deferred_violations not empty (after re-check) → raise
ROLLBACK / SAVEPOINT_ROLLBACK:
  drop pending and deferred violation sets contributed since the savepoint.
```

## Deferred semantics

- Per-FK `deferrable` + `initially_deferred` flags follow SQL standard.
- A connection may toggle current-transaction default via
  `PRAGMA defer_foreign_keys = 1`; this elevates **NoAction** FKs to
  deferred-until-commit for the lifetime of the current transaction.
  `Restrict` is **never** deferred regardless. Spec pin 8.
- Deferred violations live on the transaction object as a multiset
  keyed by `(child_table_id, child_rowid_or_pk)`; entries are
  removed when subsequent mutations within the same transaction
  resolve the missing parent.

## Cycle handling — DELETE CASCADE

Cascading deletes can form cycles (A→B, B→A) or self-cycles. The
enforcement engine uses a per-statement **visited set** keyed on
`(table_id, rowid_or_pk_tuple)`:

- A row already in the visited set is **not** re-visited; cascade
  fixes its own fixpoint.
- A hard depth cap of `FK_CASCADE_MAX_DEPTH = 65536` raises
  `RuntimeCondition::ForeignKeyCascadeDepth` (matches mainline limit
  ladder; published).
- Cycle detection is structural, not value-based: it does not depend
  on the contents of FK columns, only on visit identity.

## Storage surface (canonical signatures)

### Rust

```rust
use crate::core::{Value, RuntimeCondition};
use crate::storage::{Database, TableSchema, ForeignKey};

/// Connection-scoped toggle. Returns the previous value.
pub fn fk_set_enabled(db: &Database, enabled: bool) -> bool;
pub fn fk_is_enabled (db: &Database) -> bool;

/// Hooks invoked by INSERT / UPDATE / DELETE opcodes.
pub fn fk_on_child_insert(
    db: &Database, schema: &TableSchema, new_row: &[Value],
) -> Result<(), RuntimeCondition>;

pub fn fk_on_child_update(
    db: &Database, schema: &TableSchema,
    old_row: &[Value], new_row: &[Value],
) -> Result<(), RuntimeCondition>;

pub fn fk_on_parent_update(
    db: &Database, schema: &TableSchema,
    old_row: &[Value], new_row: &[Value],
) -> Result<(), RuntimeCondition>;

pub fn fk_on_parent_delete(
    db: &Database, schema: &TableSchema, old_row: &[Value],
) -> Result<(), RuntimeCondition>;

/// End-of-statement and end-of-transaction check points.
pub fn fk_end_statement   (db: &Database) -> Result<(), RuntimeCondition>;
pub fn fk_end_transaction (db: &Database) -> Result<(), RuntimeCondition>;
```

### C

```c
bool leap_fk_set_enabled(LeapDatabase*, bool enabled);
bool leap_fk_is_enabled (const LeapDatabase*);

LeapRuntimeCondition leap_fk_on_child_insert (LeapDatabase*, const LeapTableSchema*, const LeapValue* new_row, size_t len);
LeapRuntimeCondition leap_fk_on_child_update (LeapDatabase*, const LeapTableSchema*, const LeapValue* old_row, size_t old_len, const LeapValue* new_row, size_t new_len);
LeapRuntimeCondition leap_fk_on_parent_update(LeapDatabase*, const LeapTableSchema*, const LeapValue* old_row, size_t old_len, const LeapValue* new_row, size_t new_len);
LeapRuntimeCondition leap_fk_on_parent_delete(LeapDatabase*, const LeapTableSchema*, const LeapValue* old_row, size_t len);

LeapRuntimeCondition leap_fk_end_statement  (LeapDatabase*);
LeapRuntimeCondition leap_fk_end_transaction(LeapDatabase*);
```

## RuntimeCondition additions

- `ForeignKeyViolation`         — generic NoAction / immediate violation
- `ForeignKeyRestrictViolation` — Restrict triggered (cannot be deferred)
- `ForeignKeyCascadeDepth`      — depth cap exceeded

All three must be promoted to all 5 targets' `RuntimeCondition` enum
in lockstep with this part.

## Correctness pins

1. FK enforcement is **off** unless `PRAGMA foreign_keys = ON` was
   issued on the current connection while no transaction was active;
   mid-transaction toggles silently no-op.
2. Empty `parent_columns` resolves to the parent table's declared
   PRIMARY KEY at FK-action plan time, not at parse time (mainline).
3. `len(child_columns) != len(parent_columns)` after PK resolution is
   a DDL-time error `SCHEMA_FK_ARITY_MISMATCH`.
4. `Restrict` is checked **immediately** at the offending row mutation;
   it is never deferred, regardless of `DEFERRABLE INITIALLY DEFERRED`
   or `PRAGMA defer_foreign_keys`.
5. `NoAction` defers checks to **end of statement** by default; if the
   FK is `INITIALLY DEFERRED` (or `defer_foreign_keys=1` is set on the
   transaction), checks defer to **commit**.
6. `SetNull` writes SQL NULL into each child column in `child_columns`,
   regardless of column NOT NULL — and a subsequent NOT NULL violation
   is then raised by the column-constraint check at end of statement.
7. `SetDefault` writes each child column's declared DEFAULT, or NULL
   if none declared; the FK is then re-checked (the new default value
   may itself violate the FK → that re-check raises if so).
8. `PRAGMA defer_foreign_keys = 1` is reset at end of transaction
   (commit OR rollback). It does **not** persist across transactions.
9. Cascading mutations triggered by FK actions inherit the **same
   statement context** for end-of-statement deferred checks; nested
   cascades do not produce nested statement boundaries.
10. Cascade depth > `FK_CASCADE_MAX_DEPTH` (65536) raises
    `ForeignKeyCascadeDepth`; the value is exposed as a named constant
    in each target so it can be referenced by tests.
11. A self-referential row delete (cycle of length 1) terminates via
    visited-set membership, not via depth cap.
12. ROLLBACK or rollback to a savepoint discards both the
    end-of-statement violation set AND any deferred-until-commit
    violations contributed after the savepoint.
13. A successful mutation inside the same transaction that **resolves**
    a previously deferred violation removes it from the deferred set;
    end-of-transaction sees only the still-unresolved entries.
14. INSERT into a child row whose parent is **the same row being
    inserted in a multi-row INSERT** is not specially supported;
    end-of-statement re-check resolves it cleanly.
15. FK violation paths must not leave partially-applied cascade
    mutations visible: a violation discovered mid-cascade rolls the
    statement back to its pre-statement snapshot (statement-journal
    or equivalent — handled by `parts/storage/parts/wal/`).
16. WITHOUT ROWID parent tables: the FK's parent-row identity is the
    PK tuple, not a rowid; `fk_on_parent_*` hooks accept the PK tuple
    via `old_row`/`new_row` and route through
    `parts/storage/parts/without-rowid/` cursors when applicable.
17. FK enforcement does **not** require any new on-disk format —
    declarations live in the `sqlite_schema` DDL text, parsed back at
    open time. Mainline-produced .db files retain identical FK
    semantics when opened by LEAP.
18. The four hook entry points (`fk_on_child_insert`,
    `fk_on_child_update`, `fk_on_parent_update`, `fk_on_parent_delete`)
    are the **only** call sites; DML opcodes must invoke them
    unconditionally when `fk_is_enabled(db)` is true. No silent skip
    paths.

## Phase pins

- **Phase 15a** — schema parse + `PRAGMA foreign_keys` toggle.
- **Phase 15b** — immediate-mode NoAction + Restrict.
- **Phase 15c** — Cascade / SetNull / SetDefault.
- **Phase 15d** — deferred FKs + `defer_foreign_keys`.
- **Phase 15e** — cascade-depth cap + cycle handling.
- **Phase 15f** — WITHOUT ROWID parent integration.

## Regeneration envelope

- Target leaf size: 500–800 lines per target.
- Spec < 240 lines.
