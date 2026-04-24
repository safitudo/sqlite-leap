---
name: insert-stmt
kind: leaf
emits:
  rust: { path: src-rust/parser/insert_stmt.rs }
  c:    { path: src-c/parser/insert_stmt.c, headers: [src-c/parser/insert_stmt.h] }

---

# INSERT statement parser

Parses a basic `INSERT INTO t [(col-list)] VALUES (expr-list) [, (expr-list) ...]`
SQL statement from a `Token` stream. Delegates every value expression to
the shared `parse_expr` from `/parts/parser/parts/expr`. This leaf is the
DML counterpart to `select-stmt` and validates that the statement-parser
pattern scales to write paths.

## Scope

Admitted:
- `INSERT INTO <ident>`
- Optional column list: `(col1, col2, ...)`.
- `VALUES` keyword (required).
- One or more parenthesized value lists, comma-separated. Each value is a
  full Expr (parsed via `parse_expr`).

Deferred (flag ParseError with `"deferred: <construct>"`):
- `OR REPLACE`, `OR IGNORE`, `OR ABORT`, `OR FAIL`, `OR ROLLBACK`.
- `INSERT INTO ... SELECT ...` (SELECT-source).
- `DEFAULT VALUES`.
- `RETURNING`.
- `UPSERT` / `ON CONFLICT`.
- Qualified table name `schema.table`.
- Table alias (`INSERT INTO t AS x`).
- `WITH ... INSERT ...` (CTE-prefixed).

## Algorithm

```
parse_insert(tokens, i):
    expect tokens[i] == KwInsert; i += 1
    # deferred: OR-conflict
    if tokens[i] == KwOr: ParseError "deferred: OR-conflict"
    expect tokens[i] == KwInto; i += 1
    if tokens[i] != Ident: ParseError "expected table name after INTO"
    table_name = tokens[i].text; i += 1
    # deferred: schema-qualified table
    if tokens[i] == Dot: ParseError "deferred: schema-qualified table"
    # deferred: alias
    if tokens[i] == KwAs: ParseError "deferred: INSERT alias"
    columns = []
    if tokens[i] == LParen:
        i += 1
        loop:
            if tokens[i] != Ident: ParseError "expected column name"
            columns.push(tokens[i].text); i += 1
            if tokens[i] == Comma: i += 1; continue
            break
        if tokens[i] != RParen: ParseError "expected ) after column list"
        i += 1
    # deferred: DEFAULT VALUES
    if tokens[i] == KwDefault: ParseError "deferred: DEFAULT VALUES"
    # deferred: INSERT ... SELECT
    if tokens[i] == KwSelect: ParseError "deferred: INSERT SELECT"
    if tokens[i] != KwValues: ParseError "expected VALUES"
    i += 1
    rows = []
    loop:
        if tokens[i] != LParen: ParseError "expected ( starting value row"
        i += 1
        values = []
        loop:
            expr, i = parse_expr(tokens, i)   # delegate
            values.push(expr)
            if tokens[i] == Comma: i += 1; continue
            break
        if tokens[i] != RParen: ParseError "expected ) ending value row"
        i += 1
        rows.push({ values })
        if tokens[i] == Comma: i += 1; continue
        break
    # deferred: RETURNING
    if tokens[i] == KwReturning: ParseError "deferred: RETURNING"
    # deferred: UPSERT
    if tokens[i] == KwOn: ParseError "deferred: ON CONFLICT"
    return Ok({ stmt: { table: table_name, columns, rows }, next: i })
```

## Correctness pins

1. **Minimal valid form** — `INSERT INTO t VALUES (1)` parses to
   `{ table: "t", columns: [], rows: [{values: [IntLit("1")]}] }`.
2. **Explicit columns** — `INSERT INTO t (a, b) VALUES (1, 2)` parses
   with `columns: ["a", "b"]` and one row of two expressions.
3. **Multi-row** — `INSERT INTO t VALUES (1), (2), (3)` parses to three
   rows, each containing one expression.
4. **Multi-column multi-row** — `INSERT INTO t (a, b) VALUES (1, 2), (3, 4)`
   parses to two rows of two expressions each.
5. **Embedded expressions** — `INSERT INTO t VALUES (1+2, 'a' || 'b')`
   parses values through `parse_expr`, preserving precedence and
   operator semantics.
6. **Column list must be non-empty parens** — `INSERT INTO t () VALUES (1)`
   is a ParseError (`"expected column name"`). The parser does NOT accept
   an empty paren list — match SQLite.
7. **At least one row** — the parser requires at least one `(...)` after
   `VALUES`. A bare `INSERT INTO t VALUES;` is a ParseError
   (`"expected ( starting value row"`).
8. **No trailing comma** — `INSERT INTO t VALUES (1),;` is a
   ParseError (the comma implies another row, but the next token is `;`,
   not `(`).
9. **Deferred OR** — any `INSERT OR ...` form is an explicit
   `deferred: OR-conflict` ParseError.
10. **Deferred DEFAULT VALUES** — `INSERT INTO t DEFAULT VALUES` is
    `deferred: DEFAULT VALUES`.
11. **Deferred SELECT-source** — `INSERT INTO t SELECT ...` is
    `deferred: INSERT SELECT`. Detected by `SELECT` appearing where
    `VALUES` is expected.
12. **Deferred RETURNING** — a `RETURNING` token after the value rows
    is `deferred: RETURNING`.
13. **Owned strings** — `table` and each `columns` entry are owned
    copies, not borrowed token slices.
14. **No inline tests, no invented helpers** — same discipline as
    select-stmt. The leaf exports only `parse_insert` and the AST
    types declared in `shapes.json`.
15. **Statement terminator** — `parse_insert` stops BEFORE `;` / Eof.
    `InsertParseOk.next` points at whichever came.
16. **Expression errors propagate** — a parse failure inside any value
    expression bubbles up as-is (token_index, line, column preserved).

## Regeneration envelope

- Line budget: **~200-300 lines** of Rust / **~350-500 lines** of C.
  Simpler than select-stmt because there's only one clause structure
  (no optional WHERE/ORDER BY/LIMIT).
- No dependencies beyond std.
- Public items: `InsertStmt`, `InsertRow`, `InsertParseOk`,
  `parse_insert`.

## Smoke probe

`src-rust/examples/insert_smoke.rs` (hand-written runner, leaplint:
runner) tokenizes + parses these seven snippets and asserts the Debug
output contains the expected substrings:

1. `INSERT INTO t VALUES (1)` → single row, single value, no columns.
2. `INSERT INTO t (a) VALUES (1)` → one column.
3. `INSERT INTO t (a, b) VALUES (1, 'hi')` → two columns, mixed types.
4. `INSERT INTO t VALUES (1), (2), (3)` → three rows.
5. `INSERT INTO t (a, b) VALUES (1+2, 'x' || 'y')` → expressions.
6. `INSERT OR IGNORE INTO t VALUES (1)` → ParseError with
   `deferred: OR-conflict`.
7. `INSERT INTO t DEFAULT VALUES` → ParseError with
   `deferred: DEFAULT VALUES`.
