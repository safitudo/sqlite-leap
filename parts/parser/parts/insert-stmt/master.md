---
name: insert-stmt
kind: leaf
emits:
  rust: { path: src-rust/parser/insert_stmt.rs }
  c:    { path: src-c/parser/insert_stmt.c, headers: [src-c/parser/insert_stmt.h] }

---

# INSERT statement parser

Parses the full SQLite INSERT surface admitted at scope-B: VALUES (single
and multi-row), INSERT-from-SELECT, DEFAULT VALUES, OR-action prefix
(REPLACE / IGNORE / ABORT / FAIL / ROLLBACK), ON CONFLICT (UPSERT —
DO NOTHING and DO UPDATE), and RETURNING. Embedded value expressions
are delegated to `parse_expr`. The SELECT body of INSERT-from-SELECT
is parsed via `parse_select` from `/parts/parser/parts/select-stmt`.

## Scope

Admitted:
- `INSERT [OR <action>] INTO <ident>` — `<action>` ∈ {REPLACE, IGNORE,
  ABORT, FAIL, ROLLBACK}.
- Optional column list `(col1, col2, ...)`.
- Body forms (mutually exclusive):
  - `VALUES (expr, ...) [, (expr, ...)]*` — one or more rows.
  - `SELECT ...` — INSERT-from-SELECT, full single SelectStmt.
  - `DEFAULT VALUES` — every column takes its column default.
- Optional `ON CONFLICT (col_list) DO NOTHING`.
- Optional `ON CONFLICT (col_list) DO UPDATE SET col = expr [, ...] [WHERE expr]`.
- Optional trailing `RETURNING <result_column> [, ...]`.

Deferred (still flagged with `deferred: <construct>`):
- Schema-qualified table `schema.t`.
- Table alias on INSERT target.
- `WITH ... INSERT ...` (CTE prefix).
- ON CONFLICT without an explicit `(col_list)` target.
- Multiple ON CONFLICT clauses.

## Algorithm (sketch)

```
parse_insert(tokens, i):
    expect KwInsert; i += 1
    or_action = parse_or_action_opt(tokens, i)   # consumes `OR <action>`
    expect KwInto; i += 1
    table = ident; i += 1
    reject Dot (deferred: schema-qualified)
    reject KwAs (deferred: INSERT alias)
    columns = optional_paren_column_list(tokens, i)

    if KwDefault:
        expect KwDefault, KwValues; default_values = true
    else if KwSelect:
        from_select, i = parse_select(tokens, i)
    else:
        expect KwValues; one-or-more `(expr, ...)` rows

    on_conflict = parse_on_conflict_opt(tokens, i)
    returning   = parse_returning_opt(tokens, i)
    return Ok({ stmt, next: i })
```

`parse_on_conflict_opt`:
```
if not KwOn: return None
expect KwOn, KwConflict
expect LParen; col_list = ident-comma-list; expect RParen
expect KwDo
if KwNothing: return DoNothing(target=col_list)
if KwUpdate: expect KwSet; assignments = col=expr[,col=expr]*;
             where_ = optional KwWhere expr
             return DoUpdate(target=col_list, set_list=assignments, where_)
ParseError "expected NOTHING or UPDATE after DO"
```

`parse_returning_opt` is owned by `/parts/parser/parts/returning-clause`
and imported here. Insert-stmt invokes it at the tail of the parse and
stores the result on `InsertStmt.returning`. See that part's master.md
for the loop body and pins. Delete-stmt and update-stmt import the same
fragment.

## Correctness pins

1. **VALUES single-row** — `INSERT INTO t VALUES (1)` parses to a stmt
   with `rows.len() == 1`, `default_values == false`, `from_select` and
   `on_conflict` absent, `returning.is_empty()`, `or_action == None`.
2. **Multi-row VALUES** — `INSERT INTO t VALUES (1), (2), (3)` has
   `rows.len() == 3`.
3. **OR-action** — `INSERT OR REPLACE INTO t VALUES (1)` sets
   `or_action == Some(Replace)`. Same for IGNORE / ABORT / FAIL / ROLLBACK.
4. **INSERT-from-SELECT** — `INSERT INTO t SELECT * FROM other` sets
   `from_select == Some(SelectStmt)` and `rows` is empty.
5. **DEFAULT VALUES** — `INSERT INTO t DEFAULT VALUES` sets
   `default_values == true`; `rows` empty; `from_select` absent.
6. **ON CONFLICT DO NOTHING** — admitted.
7. **ON CONFLICT DO UPDATE** — `ON CONFLICT (id) DO UPDATE SET name='b' WHERE id > 0`
   parses target `["id"]`, set_list one assignment, where_ `Some(Binary(Gt,...))`.
8. **RETURNING** — `INSERT INTO t VALUES (1) RETURNING id, rowid` has
   `returning.len() == 2`, both `ResultColumn::Expr` with no alias.
9. **RETURNING star** — `RETURNING *` parses to a single `ResultColumn::Star`.
10. **Column list still rejected empty** — `INSERT INTO t () VALUES (1)`
    is ParseError.
11. **Body must be one of three** — bare `INSERT INTO t` (no VALUES /
    SELECT / DEFAULT) is ParseError.
12. **Body mutex** — VALUES, SELECT, DEFAULT VALUES are mutually
    exclusive at parse time. Parser picks based on the first body token.
13. **ON CONFLICT requires explicit target** — `ON CONFLICT DO NOTHING`
    (no parens) is `deferred: ON CONFLICT without target`.
14. **Owned strings** — `table`, `columns`, ON CONFLICT target columns,
    ResultColumn aliases — all owned.
15. **No inline tests, no invented helpers**.
16. **Statement terminator** — parser stops BEFORE `;` / Eof.
17. **Expression errors propagate** — token_index/line/column preserved.

## Regeneration envelope

- Line budget: ~500-700 lines of Rust / ~900-1300 lines of C.
- Public items: `OrAction`, `ConflictClause`, `ResultColumn`,
  `UpdateAssignment` (local re-decl), `InsertStmt`, `InsertRow`,
  `InsertParseOk`, `parse_insert`.
- Imports: `parse_expr` from expr, `parse_select` from select-stmt.

## Smoke probe

`src-rust/examples/dml_extensions_parse_smoke.rs` (leaplint: runner)
covers all 9 scope-B forms across INSERT/UPDATE/DELETE.
