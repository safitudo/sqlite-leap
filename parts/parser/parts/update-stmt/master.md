---
name: update-stmt
kind: leaf
emits:
  rust: { path: src-rust/parser/update_stmt.rs }
  c:    { path: src-c/parser/update_stmt.c, headers: [src-c/parser/update_stmt.h] }
---

# UPDATE statement parser

Parses `UPDATE <table> SET col=expr[, col=expr]... [WHERE <expr>]`.
Completes the DML quartet (INSERT / SELECT / DELETE / UPDATE).

## Scope

Admitted:
- `UPDATE <ident> SET <ident> = <expr>`
- Comma-separated assignments.
- Optional `WHERE <expr>`.
- Each value/WHERE expr goes through `parse_expr`.

Deferred (`deferred: <construct>`):
- `UPDATE OR ...` (OR-conflict).
- `UPDATE ... RETURNING`.
- `UPDATE ... FROM` (SQL:2003 FROM-clause in UPDATE — SQLite extension).
- Schema-qualified table.
- Alias on UPDATE target.
- `UPDATE ... WITH ...` (CTE prefix).
- `UPDATE ... SET (col1, col2) = (expr1, expr2)` (tuple-assign).

## Algorithm

```
parse_update(tokens, i):
    expect tokens[i] == KwUpdate; i += 1
    if tokens[i] == KwOr: ParseError "deferred: OR-conflict"
    if tokens[i] != Ident: ParseError "expected table name after UPDATE"
    table_name = tokens[i].text; i += 1
    if tokens[i] == Dot: ParseError "deferred: schema-qualified table"
    if tokens[i] == KwAs: ParseError "deferred: UPDATE alias"
    if tokens[i] != KwSet: ParseError "expected SET"
    i += 1
    assignments = []
    loop:
        if tokens[i] != Ident: ParseError "expected column name in SET"
        col_name = tokens[i].text; i += 1
        if tokens[i] != Eq: ParseError "expected = after column name"
        i += 1
        value, i = parse_expr(tokens, i)
        assignments.push({ column: col_name, value })
        if tokens[i] == Comma: i += 1; continue
        break
    where_ = None
    if tokens[i] == KwFrom: ParseError "deferred: UPDATE FROM"
    if tokens[i] == KwWhere:
        i += 1
        expr, i = parse_expr(tokens, i)
        where_ = Some(expr)
    if tokens[i] == KwReturning: ParseError "deferred: RETURNING"
    return Ok({ stmt: { table: table_name, assignments, where_ }, next: i })
```

## Correctness pins

1. **Single assignment** — `UPDATE t SET a = 1` parses to
   `{ table: "t", assignments: [{column: "a", value: IntLit("1")}], where_: None }`.
2. **Multiple assignments** — `UPDATE t SET a = 1, b = 2` parses to
   two assignments in order.
3. **With WHERE** — `UPDATE t SET a = 1 WHERE b = 2` attaches
   `where_: Some(Binary(Eq, Col(b), IntLit(2)))`.
4. **Expression RHS** — `UPDATE t SET a = b + 1` parses the RHS
   through `parse_expr`, preserving precedence.
5. **Missing SET** — `UPDATE t a = 1` is ParseError
   (`"expected SET"`).
6. **Missing column in SET** — `UPDATE t SET = 1` → ParseError
   (`"expected column name in SET"`).
7. **Missing `=`** — `UPDATE t SET a 1` → ParseError
   (`"expected = after column name"`).
8. **Deferred OR** — `UPDATE OR REPLACE t SET a = 1` →
   `deferred: OR-conflict`.
9. **Deferred FROM** — `UPDATE t SET a = 1 FROM x` →
   `deferred: UPDATE FROM`.
10. **Deferred RETURNING** — `UPDATE t SET a = 1 RETURNING a` →
    `deferred: RETURNING`.
11. **Expression errors propagate** — `UPDATE t SET a = 1 + ` is
    an Expr parser error surfaced verbatim.
12. **Owned strings** — `table` and each `assignment.column` are
    owned copies.
13. **Statement terminator** — `parse_update` stops BEFORE `;`/Eof.
14. **No inline tests, no invented helpers**.

## Regeneration envelope

- Line budget: **~150-220 lines** of Rust / **~260-420 lines** of C.
- No dependencies beyond std.
- Public items: `UpdateAssignment`, `UpdateStmt`, `UpdateParseOk`,
  `parse_update`.
