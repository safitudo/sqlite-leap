---
name: create-index-stmt
kind: leaf
emits:
  rust: { path: src-rust/parser/create_index_stmt.rs }
  c:    { path: src-c/parser/create_index_stmt.c, headers: [src-c/parser/create_index_stmt.h] }
---

# CREATE INDEX statement parser

Parses a `CREATE INDEX` statement (optionally UNIQUE). Delegates the
optional partial-index `WHERE` predicate to `parse_expr` from
`/parts/parser/parts/expr`.

## Scope

Admitted:
- `CREATE [UNIQUE] INDEX [IF NOT EXISTS] <name> ON <table> ( <col> [ASC|DESC] [, ...] ) [WHERE <expr>]`.

Deferred (flag ParseError `deferred: <construct>`):
- Schema-qualified `<schema>.<name>` or `<schema>.<table>`.
- Indexed expressions in the column list (`((a + b))`, `(lower(a))`).
- `COLLATE <name>` per indexed column.
- `CREATE INDEX IF EXISTS` etc. (only `IF NOT EXISTS` admitted).

## Algorithm

```
parse_create_index(tokens, i):
    expect tokens[i] == KwCreate; i += 1
    unique = false
    if tokens[i] == KwUnique: unique = true; i += 1
    expect tokens[i] == KwIndex; i += 1
    if_not_exists = false
    if tokens[i] == KwIf:
        i += 1
        expect tokens[i] == KwNot; i += 1
        expect tokens[i] == KwExists; i += 1
        if_not_exists = true
    if tokens[i] != Ident: error("expected index name")
    name = tokens[i].text; i += 1
    if tokens[i] == Dot: error("deferred: schema-qualified index name")
    expect tokens[i] == KwOn; i += 1
    if tokens[i] != Ident: error("expected table name after ON")
    table = tokens[i].text; i += 1
    if tokens[i] == Dot: error("deferred: schema-qualified table")
    expect tokens[i] == LParen; i += 1
    columns = []
    loop:
        if tokens[i] == LParen: error("deferred: indexed expression")
        if tokens[i] != Ident: error("expected indexed column name")
        col_name = tokens[i].text; i += 1
        if tokens[i] == KwCollate: error("deferred: COLLATE in index column")
        desc = false
        if tokens[i] == KwAsc: i += 1
        elif tokens[i] == KwDesc: desc = true; i += 1
        columns.push({ name: col_name, desc })
        if tokens[i] == Comma: i += 1; continue
        break
    expect tokens[i] == RParen; i += 1
    where_ = None
    if tokens[i] == KwWhere:
        i += 1
        e, i = parse_expr(tokens, i)
        where_ = Some(e)
    return Ok({ name, table, unique, if_not_exists, columns, where_ }, next: i)
```

## Correctness pins

1. **Minimal form** — `CREATE INDEX i ON t (a)` parses to
   `{ name: "i", table: "t", unique: false, if_not_exists: false,
   columns: [{name:"a", desc:false}], where_: None }`.
2. **UNIQUE flag** — `CREATE UNIQUE INDEX i ON t (a)` sets `unique = true`.
3. **IF NOT EXISTS** — `CREATE INDEX IF NOT EXISTS i ON t (a)` sets it.
4. **DESC** — `CREATE INDEX i ON t (a DESC)` sets `columns[0].desc = true`.
5. **ASC explicit** — accepted as a no-op, `desc = false`.
6. **Multi-column** — `(a, b DESC, c)` produces three IndexedColumn
   entries with the appropriate desc flags.
7. **Partial index** — `... WHERE a > 0` is parsed via `parse_expr`
   into `where_: Some(Binary(Gt, Col(a), IntLit(0)))`.
8. **Empty column list rejected** — `CREATE INDEX i ON t ()` is
   `"expected indexed column name"`.
9. **Deferred indexed expression** — leading `(` inside the column
   list is `deferred: indexed expression`.
10. **Deferred COLLATE** — `a COLLATE NOCASE` inside the column list
    is `deferred: COLLATE in index column`.
11. **Statement terminator** — stops BEFORE `;` / Eof; `next`
    points at the terminator.
12. **Owned strings** — `name`, `table`, and each column `name` are
    owned copies.
13. **Expression errors propagate** — WHERE failures bubble up.
14. **No inline tests, no invented helpers** — file exports only
    `parse_create_index` and the declared AST types.

## Regeneration envelope

- Line budget: **~150-220 lines** of Rust.
- No dependencies beyond std.
- Public items: `CreateIndexStmt`, `IndexedColumn`,
  `CreateIndexParseOk`, `parse_create_index`.

## Smoke probe

Covered in `src-rust/examples/ddl_parse_smoke.rs`:
`CREATE UNIQUE INDEX idx_b ON t (b DESC)` and
`DROP INDEX idx_b` (the latter via drop-stmt).
