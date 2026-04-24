---
name: delete-stmt
kind: leaf
emits:
  rust: { path: src-rust/parser/delete_stmt.rs }
  c:    { path: src-c/parser/delete_stmt.c, headers: [src-c/parser/delete_stmt.h] }
---

# DELETE statement parser

Parses a basic `DELETE FROM <table> [WHERE <expr>]` statement. The
simplest DML form — proves the statement-parser pattern handles
plain conditional bulk-delete.

## Scope

Admitted:
- `DELETE FROM <ident>` — delete all rows.
- `DELETE FROM <ident> WHERE <expr>` — delete filtered rows.

Deferred (`deferred: <construct>`):
- `DELETE ... RETURNING ...`.
- `DELETE FROM <schema>.<table>` (qualified table).
- `DELETE FROM <table> AS <alias>` (alias).
- `WITH ... DELETE ...` (CTE prefix).
- Table-valued functions as target.

## Algorithm

```
parse_delete(tokens, i):
    expect tokens[i] == KwDelete; i += 1
    expect tokens[i] == KwFrom;   i += 1
    if tokens[i] != Ident: ParseError "expected table name after DELETE FROM"
    table_name = tokens[i].text; i += 1
    if tokens[i] == Dot: ParseError "deferred: schema-qualified table"
    if tokens[i] == KwAs: ParseError "deferred: DELETE alias"
    where_ = None
    if tokens[i] == KwWhere:
        i += 1
        expr, i = parse_expr(tokens, i)
        where_ = Some(expr)
    if tokens[i] == KwReturning: ParseError "deferred: RETURNING"
    return Ok({ stmt: { table: table_name, where_ }, next: i })
```

## Correctness pins

1. **No-WHERE** — `DELETE FROM t` parses to
   `{ table: "t", where_: None }`. This is the "delete all rows" form.
2. **With WHERE** — `DELETE FROM t WHERE a = 1` parses with
   `where_: Some(Binary(Eq, Col(a), IntLit(1)))`.
3. **Missing FROM** — `DELETE t` is a ParseError (`"expected FROM"`).
4. **Missing table** — `DELETE FROM` (immediately followed by `;`)
   is a ParseError (`"expected table name after DELETE FROM"`).
5. **Schema-qualified deferred** — `DELETE FROM s.t` is
   `deferred: schema-qualified table`.
6. **Alias deferred** — `DELETE FROM t AS x` is `deferred: DELETE alias`.
7. **RETURNING deferred** — `DELETE FROM t RETURNING a` is
   `deferred: RETURNING`.
8. **WHERE delegates** — embedded expression errors propagate as-is.
9. **Owned strings** — `table` is an owned copy.
10. **Statement terminator** — parser stops BEFORE `;` / Eof.
11. **No inline tests, no invented helpers**.

## Regeneration envelope

- Line budget: **~90-140 lines** of Rust / **~180-280 lines** of C.
- No dependencies beyond std.
- Public items: `DeleteStmt`, `DeleteParseOk`, `parse_delete`.
