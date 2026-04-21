# Phase 6bh harness — UPSERT (ON CONFLICT DO NOTHING / DO UPDATE SET)

Extends Phase 6ab's INSERT-OR-IGNORE/REPLACE with the SQL-standard UPSERT form: `INSERT ... ON CONFLICT(<target>) DO NOTHING` and `INSERT ... ON CONFLICT(<target>) DO UPDATE SET <assigns> [WHERE <cond>]`.

No new VDBE opcodes; reuses 9g UNIQUE-probe + DeleteRow + UpdateRow + InsertRow infra. `max_invariant=45` unchanged. One new reserved keyword: `KEYWORD_EXCLUDED` (the pseudo-table for the would-be-inserted row). `ON` / `CONFLICT` / `DO` / `NOTHING` / `SET` — some already reserved; verify.

Gate: 8 fixtures green both targets. `SUMMARY phase=6bh target=<c|rust> passed=8 failed=0 total=8`.

### Grammar

```
insert-stmt := KEYWORD_INSERT
              [ KEYWORD_OR ( KEYWORD_IGNORE | KEYWORD_REPLACE ) ]
              KEYWORD_INTO IDENTIFIER
              ( values-clause | select-stmt )
              [ upsert-clause ]
              [ returning-clause ]

upsert-clause := KEYWORD_ON KEYWORD_CONFLICT LPAREN conflict-target RPAREN
                 upsert-action

conflict-target := IDENTIFIER ( COMMA IDENTIFIER )*    -- list of column names

upsert-action := KEYWORD_DO KEYWORD_NOTHING
               | KEYWORD_DO KEYWORD_UPDATE KEYWORD_SET assignment-list [ KEYWORD_WHERE expression ]

assignment-list := assignment ( COMMA assignment )*
assignment      := IDENTIFIER EQ expression
```

### Semantics

**Conflict target resolution (compile time)**:
- The column-list in `ON CONFLICT(col, col, …)` must correspond to either:
  - The PRIMARY KEY columns of the table (single-col or multi-col), OR
  - A UNIQUE index's key columns (by column-list match)
- If no matching index/constraint exists → `COMPILE_NO_CONFLICT_TARGET`.

**DO NOTHING**:
- If the tentative insert would violate the specified conflict target, silently skip the row. No update, no delete. Semantically equivalent to `INSERT OR IGNORE` scoped to ONE specific constraint.
- Behavior on conflicts with a DIFFERENT constraint (not named in conflict-target) → normal error propagation (STORAGE_UNIQUE_VIOLATION). Differs from OR IGNORE which swallows ALL uniqueness conflicts.

**DO UPDATE SET assignments [WHERE predicate]**:
- On conflict with the named target, fetch the existing row. Evaluate SET assignments using:
  - Table-column references = existing row values (pre-update)
  - `excluded.<col>` references = would-be-inserted values
- Apply the optional WHERE predicate (also with both scopes). If false, skip the update (row unchanged).
- If true, emit UpdateRow with the computed new values.
- Index maintenance fires normally (secondary indexes updated if values change).

**No-conflict case**: ON CONFLICT clause is inert; proceeds as a normal INSERT.

### Errors

- `COMPILE_NO_CONFLICT_TARGET { columns }` — conflict-target column-list doesn't match any PK or UNIQUE index.
- `COMPILE_UNKNOWN_COLUMN` — assignment references a column that doesn't exist (reuses existing).
- `COMPILE_EXCLUDED_COLUMN_NOT_FOUND` — `excluded.<col>` where col isn't in the INSERT's column-list (or isn't a table column).

### Implementation

- AST: extend `Ast::Insert` with `upsert: Option<Upsert>`.
  - `Upsert { target: Vec<ColumnName>, action: UpsertAction }`
  - `UpsertAction = DoNothing | DoUpdate { assignments, where_clause: Option<Expr> }`
- Parser: after VALUES / select-clause, peek for `KEYWORD_ON KEYWORD_CONFLICT`; on match, parse the upsert-clause.
- Compiler:
  1. Resolve conflict-target → index id. Fail early if none.
  2. On each tuple: emit index-probe; on hit:
     - For DO NOTHING: jump past InsertRow + index maintenance.
     - For DO UPDATE: allocate registers for `excluded.*` (the would-be-inserted row values), load existing row values, evaluate WHERE (if any), then evaluate assignments and emit UpdateRow.
  3. On miss: normal InsertRow + index maintenance.
- Name resolution: during assignment compilation, `excluded` is a pseudo-table alias that resolves to the tuple's register set; other identifiers resolve to the target table's columns.

### Non-goals (v1)

- Multi-constraint conflict target (ON CONFLICT without target, targeting ANY violation) — mainline SQLite supports this form; deferred.
- WHERE clause on DO NOTHING — not meaningful; permanent non-goal.
- UPSERT combined with INSERT ... SELECT form — defer; fixture uses VALUES only.
