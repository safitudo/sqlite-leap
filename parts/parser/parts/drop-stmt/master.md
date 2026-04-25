---
name: drop-stmt
kind: leaf
emits:
  rust: { path: src-rust/parser/drop_stmt.rs }
  c:    { path: src-c/parser/drop_stmt.c, headers: [src-c/parser/drop_stmt.h] }
---

# DROP statement parser

Parses `DROP TABLE`, `DROP INDEX`, and `DROP VIEW` from a `Token`
stream. The simplest DDL leaf — three near-identical forms behind a
discriminator. No expression delegation.

## Scope

Admitted:
- `DROP TABLE [IF EXISTS] <name>`.
- `DROP INDEX [IF EXISTS] <name>`.
- `DROP VIEW  [IF EXISTS] <name>`.

Deferred:
- Schema-qualified names (`schema.t`).
- `DROP TRIGGER` (no trigger support yet).

## Algorithm

```
parse_drop(tokens, i):
    expect tokens[i] == KwDrop; i += 1
    kind = match tokens[i]:
        KwTable:   Table
        KwIndex:   Index
        KwView:    View
        else:      error("expected TABLE / INDEX / VIEW after DROP")
    i += 1
    if_exists = false
    if tokens[i] == KwIf:
        i += 1
        expect tokens[i] == KwExists; i += 1
        if_exists = true
    if tokens[i] != Ident: error("expected name after DROP")
    name = tokens[i].text; i += 1
    if tokens[i] == Dot: error("deferred: schema-qualified name")
    return Ok({ kind, if_exists, name }, next: i)
```

## Correctness pins

1. **DROP TABLE minimal** — `DROP TABLE t` →
   `{ kind: Table, if_exists: false, name: "t" }`.
2. **DROP INDEX minimal** — `DROP INDEX idx` →
   `{ kind: Index, if_exists: false, name: "idx" }`.
3. **DROP VIEW minimal** — `DROP VIEW v` →
   `{ kind: View, if_exists: false, name: "v" }`.
4. **IF EXISTS** — `DROP TABLE IF EXISTS t` sets `if_exists = true`.
   Bare `IF` not followed by `EXISTS` is an error.
5. **Unknown object kind** — `DROP TRIGGER tr` is `deferred: TRIGGER`;
   `DROP DATABASE x` is `"expected TABLE / INDEX / VIEW after DROP"`.
6. **Statement terminator** — stops BEFORE `;` / Eof; `next` points
   at the terminator.
7. **Owned strings** — `name` is an owned copy.
8. **No inline tests, no invented helpers** — file exports only
   `parse_drop` and the declared AST types.

## Regeneration envelope

- Line budget: **~80-130 lines** of Rust.
- No dependencies beyond std.
- Public items: `DropStmt`, `DropKind`, `DropParseOk`, `parse_drop`.

## Smoke probe

Covered in `src-rust/examples/ddl_parse_smoke.rs`:
`DROP TABLE IF EXISTS t`, `DROP INDEX idx_b`, `DROP VIEW v`.
