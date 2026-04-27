---
name: attach-stmt
kind: leaf
shapes: ./shapes.json
emits:
  rust: { path: src-rust/parser/attach_stmt.rs }
  c:    { path: src-c/parser/attach_stmt.c, headers: [src-c/parser/attach_stmt.h] }
---

# ATTACH statement parser

Parses an `ATTACH` statement that binds an additional database
file under a logical schema name in the current connection's
catalog. The grammar is the published SQLite surface
(sqlite.org/lang_attach.html):

```
attach-stmt ::= ATTACH [DATABASE] expr AS schema-name [KEY expr]
```

`expr` is parsed via `parse_expr` from `/parts/parser/parts/expr`
and represents the filename / URI of the database to attach. The
optional `KEY` clause carries an encryption key expression; v1
admits the syntax but the executor rejects it (see pin 12).

This is a **statement-level leaf**. It owns the AST node and the
parse function only. Catalog mutation, file open, and busy checks
live downstream in `/parts/storage/parts/multi-db` and the
executor.

## Scope

Admitted forms:
- `ATTACH 'file.db' AS alias`
- `ATTACH DATABASE 'file.db' AS alias`
- `ATTACH expr AS alias` — any valid Expr; semantic typing is
  deferred to the executor.
- `ATTACH expr AS alias KEY expr2`
- `ATTACH DATABASE expr AS alias KEY expr2`

`schema-name` is parsed as a single identifier token (quoted or
unquoted, per tokenizer rules). It MUST NOT be `main` or `temp`
(see pin 7).

Deferred / rejected:
- Any continuation past the optional `KEY expr` other than the
  statement terminator.

## Declared shapes (in `shapes.json`)

- `AttachStmt` — `{ db_expr, schema_name, key_expr (present|absent) }`.
- `AttachParseOk` — `{ stmt, next: u32 }`.
- `parse_attach(tokens, start) -> result<AttachParseOk, ParseError>`.
- `ParseError` is imported from `/parts/parser/parts/expr`.

## Algorithm (recursive descent, single pass)

```
parse_attach(tokens, i):
    expect tokens[i] == KwAttach; i += 1
    if tokens[i] == KwDatabase: i += 1
    db_expr, i = parse_expr(tokens, i)
    expect tokens[i] == KwAs; i += 1
    if tokens[i] != Ident: error("expected schema name after AS")
    schema_name = tokens[i].text; i += 1
    key_expr = absent
    if tokens[i] == KwKey:
        i += 1
        k, i = parse_expr(tokens, i)
        key_expr = present(k)
    return Ok({ db_expr, schema_name, key_expr }, next: i)
```

Stops BEFORE the terminating `;` or Eof.

## Correctness pins

1. **Keyword shape** — leading token MUST be `ATTACH`. Optional
   `DATABASE` keyword is consumed when present and is a syntactic
   no-op.
2. **DB expression mandatory** — absent expression after
   `ATTACH [DATABASE]` is a ParseError
   `"expected expression after ATTACH"` propagated from
   `parse_expr`.
3. **AS keyword required** — missing `AS` is a ParseError
   `"expected AS"`. Bare-ident alias (no `AS`) is NOT accepted.
4. **Schema name is a single Ident token** — quoted forms
   allowed; a dot-qualified identifier (`a.b`) at this position
   is a ParseError `"expected schema name after AS"`.
5. **Owned strings** — `schema_name` is OWNED, copied from the
   token's slice. Embedded expressions own their substructure
   per the expression parser's contract.
6. **KEY clause optional and trailing** — when present it MUST
   come AFTER `AS schema-name` and contain a single expression.
   Anything past `KEY expr` other than the terminator is a
   ParseError `"expected end of statement"`.
7. **Reserved schema names rejected** — case-folded ASCII match
   against `main` and `temp` raises ParseError
   `"cannot attach as reserved schema 'main'"` /
   `"... 'temp'"`. These two slots are owned by the catalog.
8. **Schema name length cap** — `schema_name` length MUST be in
   `[1, 64]` chars; out-of-range raises
   `"schema name length out of range"`.
9. **Reserved comparison case-insensitive** — `MAIN`, `Main`,
   `mAIn` all reject; non-ASCII bytes compared bytewise.
10. **Statement terminator** — stops BEFORE `;` or Eof;
    `AttachParseOk.next` points at it.
11. **No inline tests, no invented helpers** — exports only
    `parse_attach` plus its records. No catalog access, no file
    I/O, no expression re-implementation.
12. **KEY parser does not interpret** — `key_expr` is parsed
    syntactically only; executor raises
    `EncryptionNotSupported` (see
    `/parts/storage/parts/multi-db` pin 14).
13. **Recursive integration** — both `db_expr` and `key_expr` go
    through the imported `parse_expr`. Expression errors
    propagate as-is.
14. **Compound-statement isolation** — `ATTACH … ; SELECT …`
    splits at the executor layer; this parser is
    single-statement.
15. **Language-neutral surface** — no Rust `String`, no
    `char *`, no `Path`. `db_expr` / `key_expr` are abstract
    Expr trees; `schema_name` is the neutral `string` shape per
    `/spec/type-system.spec.md`.
16. **Informative deferred errors** — stray tokens past KEY's
    expression produce
    `"expected end of statement after ATTACH"`, not a generic
    unexpected-token message.

## Regeneration envelope

- Line budget: ~80-130 lines of Rust.
- No dependencies beyond std and the tokenizer / expr part.
- Public items: `AttachStmt`, `AttachParseOk`, `parse_attach`.

## Smoke probe

```text
1. ATTACH 'a.db' AS alias              → schema_name="alias", key=absent
2. ATTACH DATABASE 'a.db' AS alias     → DATABASE keyword consumed
3. ATTACH 'a.db' AS x KEY 'pw'         → key=present(StrLit "pw")
4. ATTACH :p AS x                      → db_expr=Param(p), key=absent
5. ATTACH 'a.db' AS main               → ParseError reserved 'main'
6. ATTACH 'a.db' alias                 → ParseError expected AS
7. ATTACH 'a.db' AS                    → ParseError expected schema name
```
