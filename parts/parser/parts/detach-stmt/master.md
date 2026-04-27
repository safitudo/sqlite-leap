---
name: detach-stmt
kind: leaf
shapes: ./shapes.json
emits:
  rust: { path: src-rust/parser/detach_stmt.rs }
  c:    { path: src-c/parser/detach_stmt.c, headers: [src-c/parser/detach_stmt.h] }
---

# DETACH statement parser

Parses a `DETACH` statement that unbinds a previously attached
database from the connection's catalog
(sqlite.org/lang_detach.html):

```
detach-stmt ::= DETACH [DATABASE] schema-name
```

Catalog mutation, busy checks, and pending-cursor / open-statement
guards live downstream in `/parts/storage/parts/multi-db` and the
executor (see `multi-db` pin 12). The parser only validates the
syntactic shape and the schema-name reservation rule.

## Scope

Admitted forms:
- `DETACH alias`
- `DETACH DATABASE alias`

Rejected:
- `DETACH 'expr'` — schema-name MUST be an identifier, not an
  expression (parser-level error, not deferred).
- Any continuation past the schema-name other than the statement
  terminator.

## Declared shapes (in `shapes.json`)

- `DetachStmt` — `{ schema_name }`.
- `DetachParseOk` — `{ stmt, next: u32 }`.
- `parse_detach(tokens, start) -> result<DetachParseOk, ParseError>`.

## Algorithm (recursive descent, single pass)

```
parse_detach(tokens, i):
    expect tokens[i] == KwDetach; i += 1
    if tokens[i] == KwDatabase: i += 1
    if tokens[i] != Ident: error("expected schema name after DETACH")
    schema_name = tokens[i].text; i += 1
    return Ok({ schema_name }, next: i)
```

Stops BEFORE the terminating `;` or Eof.

## Correctness pins

1. **Keyword shape** — leading token MUST be `DETACH`. Optional
   `DATABASE` keyword consumed when present, syntactic no-op.
2. **Schema name is a single Ident token** — quoted forms
   allowed; dot-qualified (`a.b`) is a ParseError
   `"expected schema name after DETACH"`.
3. **Reserved schema names rejected at parse time** — `main`
   and `temp` (ASCII case-folded) raise ParseError
   `"cannot detach reserved schema 'main'"` /
   `"... 'temp'"`. Mainline-equivalent error.
4. **Owned strings** — `schema_name` is OWNED, copied from the
   token's slice.
5. **Statement terminator** — stops BEFORE `;` or Eof;
   `DetachParseOk.next` points at it.
6. **Schema name length cap** — `[1, 64]` chars; out-of-range
   raises `"schema name length out of range"`.
7. **No expression body** — DETACH does NOT take an `expr`. A
   string-literal token at the schema-name position is a
   ParseError `"expected schema name after DETACH"`. (The
   tokenizer's StrLit kind is distinct from Ident.)
8. **No trailing clauses** — anything after the schema-name
   other than `;` or Eof is a ParseError
   `"expected end of statement after DETACH"`.
9. **Reserved comparison case-insensitive** — `MAIN`, `Temp`,
   `mAIn` all reject; non-ASCII bytes bytewise.
10. **Busy-guard NOT enforced here** — the parser does NOT check
    whether `schema_name` is currently bound, has open cursors,
    or is in an active transaction. That is the executor's job
    (see `/parts/storage/parts/multi-db` pin 12). The parser
    succeeds for any well-formed identifier that is not
    `main` / `temp`.
11. **No inline tests, no invented helpers** — exports only
    `parse_detach`, `DetachStmt`, `DetachParseOk`.
12. **Compound-statement isolation** — `DETACH x ; SELECT ...`
    splits at the executor layer; single-statement here.
13. **Language-neutral surface** — `schema_name` is the neutral
    `string` shape; no Rust / C type leaks.
14. **Recursive integration** — DETACH does not embed any Expr,
    so it does NOT depend on `parse_expr`. Tokenizer-only
    dependency.
15. **Informative error messages** — every error names the
    construct (`"expected schema name after DETACH"`,
    `"cannot detach reserved schema 'main'"`, etc.); no generic
    unexpected-token messages.
16. **Idempotent re-parse** — parsing the same token slice
    twice yields the same AST and same `next` index;
    side-effect-free.

## Regeneration envelope

- Line budget: ~50-90 lines of Rust.
- Tokenizer dependency only (no expr).
- Public items: `DetachStmt`, `DetachParseOk`, `parse_detach`.

## Smoke probe

```text
1. DETACH alias                  → schema_name="alias"
2. DETACH DATABASE alias         → DATABASE keyword consumed
3. DETACH "Quoted Name"          → schema_name="Quoted Name"
4. DETACH main                   → ParseError reserved 'main'
5. DETACH                        → ParseError expected schema name
6. DETACH 'literal'              → ParseError expected schema name
7. DETACH a junk                 → ParseError expected end of statement
```
