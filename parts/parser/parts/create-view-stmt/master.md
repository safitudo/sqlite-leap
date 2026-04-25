---
name: create-view-stmt
kind: leaf
emits:
  rust: { path: src-rust/parser/create_view_stmt.rs }
  c:    { path: src-c/parser/create_view_stmt.c, headers: [src-c/parser/create_view_stmt.h] }
---

# CREATE VIEW statement parser

Parses a `CREATE VIEW` statement, delegating the body to
`parse_select` from `/parts/parser/parts/select-stmt`. This is the
first DDL leaf to import another statement-parser leaf and validates
that the dependency works without circularity.

## Scope

Admitted:
- `CREATE VIEW [IF NOT EXISTS] <name> [(<col> [, <col>]*)] AS <select_stmt>`.

Deferred (flag ParseError `deferred: <construct>`):
- `CREATE TEMP VIEW`, `CREATE TEMPORARY VIEW`.
- Schema-qualified names (`schema.view`).
- `CREATE RECURSIVE VIEW` (non-standard SQLite extension; n/a).

## Algorithm

```
parse_create_view(tokens, i):
    expect tokens[i] == KwCreate; i += 1
    expect tokens[i] == KwView;   i += 1   # otherwise "expected VIEW"
    if_not_exists = false
    if tokens[i] == KwIf:
        i += 1
        expect tokens[i] == KwNot; i += 1
        expect tokens[i] == KwExists; i += 1
        if_not_exists = true
    if tokens[i] != Ident: error("expected view name")
    name = tokens[i].text; i += 1
    if tokens[i] == Dot: error("deferred: schema-qualified view")
    columns = []
    if tokens[i] == LParen:
        i += 1
        loop:
            if tokens[i] != Ident: error("expected column name")
            columns.push(tokens[i].text); i += 1
            if tokens[i] == Comma: i += 1; continue
            break
        if tokens[i] != RParen: error("expected ) after view column list")
        i += 1
    expect tokens[i] == KwAs;     i += 1
    if tokens[i] != KwSelect: error("expected SELECT after AS")
    sel_ok, i = parse_select(tokens, i)
    return Ok({ name, if_not_exists, columns, select: sel_ok.stmt }, next: i)
```

## Correctness pins

1. **Minimal form** — `CREATE VIEW v AS SELECT 1` parses with empty
   `columns` and a SelectStmt body whose projection contains
   `IntLit("1")`.
2. **IF NOT EXISTS** — `CREATE VIEW IF NOT EXISTS v AS SELECT 1`
   sets `if_not_exists = true`.
3. **Column list** — `CREATE VIEW v (a, b) AS SELECT 1, 2` produces
   `columns: ["a", "b"]`.
4. **Empty column list rejected** — `CREATE VIEW v () AS SELECT 1`
   is `"expected column name"`.
5. **Body is parsed via parse_select** — the imported SelectStmt is
   verbatim; this leaf does not touch projection / FROM / WHERE.
6. **AS required** — `CREATE VIEW v SELECT 1` is
   `"expected AS before SELECT"` (i.e. error before consuming SELECT).
7. **SELECT required after AS** — `CREATE VIEW v AS 1` is
   `"expected SELECT after AS"`.
8. **Statement terminator** — stops where `parse_select` stops
   (BEFORE `;` / Eof); `next` is `parse_select`'s `next`.
9. **Owned strings** — `name` and each column name are owned.
10. **Expression / SELECT errors propagate** — `parse_select`
    failures bubble up as-is.
11. **No inline tests, no invented helpers** — exports only
    `parse_create_view` and the declared AST types. No
    re-implementation of select-clause parsing.

## Regeneration envelope

- Line budget: **~120-180 lines** of Rust.
- No dependencies beyond std.
- Public items: `CreateViewStmt`, `CreateViewParseOk`,
  `parse_create_view`.

## Smoke probe

Covered in `src-rust/examples/ddl_parse_smoke.rs`:
`CREATE VIEW v AS SELECT a FROM t WHERE a > 5`.
