---
name: savepoint-stmt
kind: leaf
shapes: ./shapes.json
emits:
  rust: { path: src-rust/parser/savepoint_stmt.rs }
  c:    { path: src-c/parser/savepoint_stmt.c, headers: [src-c/parser/savepoint_stmt.h] }
---

# SAVEPOINT / RELEASE / ROLLBACK-TO statement parser

Parses the three savepoint-related statement forms from a `Token`
stream produced by `/parts/parser/parts/tokenizer`. Each form names
exactly one savepoint identifier; no embedded expressions, no
clauses, no recursion. This is the simplest statement-level parser
part in the tree.

The three accepted forms (lang_savepoint.html — published spec):

```
savepoint-stmt    := SAVEPOINT name
release-stmt      := RELEASE [SAVEPOINT] name
rollback-to-stmt  := ROLLBACK [TRANSACTION] TO [SAVEPOINT] name
```

`name` is a single identifier (regular or quoted). Names follow the
same identifier rules as table names. Names are case-sensitive in
this parser; the compiler does its own normalization.

## Scope

Admitted:

- `SAVEPOINT <ident>` — declare a new savepoint.
- `RELEASE <ident>` — release a savepoint by name (the optional
  `SAVEPOINT` keyword between `RELEASE` and the name is accepted).
- `ROLLBACK TO <ident>` — revert changes to a savepoint by name
  (the optional `TRANSACTION` keyword between `ROLLBACK` and `TO`,
  and the optional `SAVEPOINT` keyword between `TO` and the name,
  are both accepted in any combination).

Deferred (flag `ParseError` with `"deferred: <construct>"`):

- A bare `ROLLBACK` (no `TO` clause) — that's a top-level
  transaction rollback, owned by a separate `transaction-stmt`
  part. The savepoint parser only handles the `TO` form.

## Declared shapes (in `shapes.json`)

- `SavepointStmt` — `{ name: string }`.
- `ReleaseStmt` — `{ name: string }`.
- `RollbackToStmt` — `{ name: string }`.
- `SavepointParseOk` — `{ stmt, next: u32 }` where `stmt` is one
  of three variants (`Savepoint | Release | RollbackTo`).
- `parse_savepoint_family(tokens, start) -> result<SavepointParseOk, ParseError>`.

## Algorithm (single-pass recursive descent)

```
parse_savepoint_family(tokens, i):
    case tokens[i]:
        KwSavepoint:
            return parse_savepoint(tokens, i)
        KwRelease:
            return parse_release(tokens, i)
        KwRollback:
            return parse_rollback_to(tokens, i)
        else:
            error("expected SAVEPOINT / RELEASE / ROLLBACK")

parse_savepoint(tokens, i):
    expect tokens[i] == KwSavepoint; i += 1
    if tokens[i] != Ident: error("expected savepoint name after SAVEPOINT")
    name = tokens[i].text; i += 1
    return Ok(Savepoint { name }, next: i)

parse_release(tokens, i):
    expect tokens[i] == KwRelease; i += 1
    if tokens[i] == KwSavepoint: i += 1
    if tokens[i] != Ident: error("expected savepoint name after RELEASE")
    name = tokens[i].text; i += 1
    return Ok(Release { name }, next: i)

parse_rollback_to(tokens, i):
    expect tokens[i] == KwRollback; i += 1
    if tokens[i] == KwTransaction: i += 1
    if tokens[i] != KwTo:
        # bare ROLLBACK — out of scope for this part
        error("deferred: bare ROLLBACK (transaction rollback)")
    i += 1   # consume TO
    if tokens[i] == KwSavepoint: i += 1
    if tokens[i] != Ident: error("expected savepoint name after ROLLBACK TO")
    name = tokens[i].text; i += 1
    return Ok(RollbackTo { name }, next: i)
```

## Correctness pins

1. **Three forms only** — `SAVEPOINT name`, `RELEASE [SAVEPOINT]
   name`, `ROLLBACK [TRANSACTION] TO [SAVEPOINT] name`. Any other
   prefix is a `ParseError` `"expected SAVEPOINT / RELEASE /
   ROLLBACK"`.
2. **Name is a single identifier** — `name` MUST be a `TokenKind::Ident`.
   Numeric literals, string literals, and qualified names like
   `schema.name` are rejected with `"expected savepoint name after
   <KEYWORD>"`. Quoted identifiers go through the tokenizer's
   identifier path; this parser sees them as `Ident`.
3. **Optional keywords are accepted, never required** — `RELEASE
   SAVEPOINT x` and `RELEASE x` both parse to the same
   `ReleaseStmt { name: "x" }`. `ROLLBACK TRANSACTION TO SAVEPOINT
   x`, `ROLLBACK TO SAVEPOINT x`, `ROLLBACK TRANSACTION TO x`,
   `ROLLBACK TO x` all parse to the same `RollbackToStmt { name:
   "x" }`.
4. **Bare ROLLBACK is out of scope** — `ROLLBACK` not followed by
   `TRANSACTION` or `TO` (i.e. `ROLLBACK ;`, `ROLLBACK Eof`) is a
   `ParseError` `"deferred: bare ROLLBACK (transaction rollback)"`.
   The transaction-stmt parser owns that form. Likewise `ROLLBACK
   TRANSACTION ;` (no TO) — same error.
5. **No expressions, no clauses** — savepoint statements take no
   `WHERE`, no projection, no `LIMIT`. The first non-name token
   after the name MUST be a statement terminator (`;` or `Eof`).
   Encountering any other token leaves it for the caller; the
   parser does not consume it (matches `select-stmt` pin 10).
6. **Owned strings** — the `name` field is owned (copied from the
   token's borrowed slice). Source-buffer lifetime does not
   constrain the AST.
7. **Statement terminator behavior** — `parse_savepoint_family`
   stops BEFORE the terminating `;` or `Eof`; `SavepointParseOk.next`
   points at whichever terminator was reached. The caller checks
   and consumes.
8. **Missing-name diagnostics name the keyword** — the error
   message includes the keyword that introduced the form
   (`SAVEPOINT`, `RELEASE`, `ROLLBACK TO`) so a user reading the
   error knows which form was being parsed.
9. **No inline tests, no invented helpers** — the file exports
   only `parse_savepoint_family` plus the three locally-necessary
   sub-parsers. No cross-part state, no tokenizer re-invocation.
10. **Case-insensitivity is the tokenizer's job** — this parser
    matches on `TokenKind` values (e.g. `KwSavepoint`), not on
    raw source text. Case folding for the keyword spellings
    happens in `/parts/parser/parts/tokenizer`.

## Regeneration envelope

- Line budget: **~120-180 lines** of Rust. Three tiny parse
  functions + a dispatch + a `SavepointStmt` enum.
- No dependencies beyond std and the imported `Token` /
  `TokenKind` / `ParseError` types.
- Public items: `SavepointStmt`, `SavepointParseOk`,
  `parse_savepoint_family`. (Sub-parsers may be private.)

## Smoke probe

`src-rust/examples/savepoint_smoke.rs` (hand-written, NOT
regenerated) tokenizes + parses the following statements and
asserts the resulting variant + name:

```text
1. SAVEPOINT a                    → Savepoint{name="a"}
2. RELEASE a                      → Release{name="a"}
3. RELEASE SAVEPOINT a            → Release{name="a"}
4. ROLLBACK TO a                  → RollbackTo{name="a"}
5. ROLLBACK TO SAVEPOINT a        → RollbackTo{name="a"}
6. ROLLBACK TRANSACTION TO a      → RollbackTo{name="a"}
7. ROLLBACK TRANSACTION TO SAVEPOINT a → RollbackTo{name="a"}
8. ROLLBACK                       → ParseError "deferred: bare ROLLBACK..."
9. SAVEPOINT 42                   → ParseError "expected savepoint name after SAVEPOINT"
```

Runner prints `OK: all N statements parse to expected shape` on
success.
