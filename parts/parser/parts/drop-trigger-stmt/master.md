---
name: drop-trigger-stmt
kind: leaf
emits:
  rust: { path: src-rust/parser/drop_trigger_stmt.rs }
  c:    { path: src-c/parser/drop_trigger_stmt.c, headers: [src-c/parser/drop_trigger_stmt.h] }
---

# DROP TRIGGER statement parser

Parses `DROP TRIGGER [IF EXISTS] <name>`. Lifts the `DROP TRIGGER`
form that `/parts/parser/parts/drop-stmt` defers. A separate leaf,
not a fourth case in `drop-stmt`, because the trigger drop's
downstream wiring (compiler-side trigger cache invalidation,
storage-side trigger registry mutation) is distinct from drop of
schema objects whose definitions live in `sqlite_master` rows
without companion in-memory state.

## Scope

Admitted:
- `DROP TRIGGER [IF EXISTS] <name>`.

Deferred:
- Schema-qualified trigger name (`schema.tr`).

## Algorithm

```
parse_drop_trigger(tokens, i):
    expect tokens[i] == KwDrop;    i += 1
    expect tokens[i] == KwTrigger; i += 1
    if_exists = false
    if tokens[i] == KwIf:
        i += 1
        expect tokens[i] == KwExists; i += 1
        if_exists = true
    if tokens[i] != Ident: error("expected trigger name after DROP TRIGGER")
    name = tokens[i].text; i += 1
    if tokens[i] == Dot: error("deferred: schema-qualified trigger name")
    return Ok({ if_exists, name }, next: i)
```

## Correctness pins

1. **Minimal form** — `DROP TRIGGER tr` →
   `{ if_exists: false, name: "tr" }`.
2. **IF EXISTS** — `DROP TRIGGER IF EXISTS tr` sets
   `if_exists = true`. A bare `KwIf` not followed by `KwExists` is
   `"expected EXISTS after IF"`.
3. **DROP keyword sequence** — first token must be `KwDrop`, second
   `KwTrigger`. A drop of any other object kind belongs to
   `parts/parser/parts/drop-stmt`; this leaf MUST NOT advance past
   `KwDrop` if `KwTrigger` does not follow. The dispatcher in the
   statements router decides which leaf parses based on the
   second-token lookahead.
4. **Trigger name required** — missing identifier after the keyword
   sequence (or after `IF EXISTS`) is `"expected trigger name after
   DROP TRIGGER"`.
5. **Schema-qualified name rejected** — `DROP TRIGGER main.tr` is
   `"deferred: schema-qualified trigger name"`.
6. **Statement terminator** — stops BEFORE `;` / Eof; `next` points
   at the terminator the caller still consumes.
7. **Owned strings** — `name` is an owned copy.
8. **No inline tests, no invented helpers** — exports only
   `parse_drop_trigger` and the declared AST types.
9. **Parser does not check existence** — whether a trigger of that
   name exists is a runtime concern owned by
   `/parts/storage/parts/triggers/`. The `if_exists` flag is
   captured but not interpreted here.
10. **Case sensitivity follows the tokenizer** — keyword matching
    uses the tokenizer's keyword kinds; identifier text is preserved
    verbatim. Case-insensitive identifier comparison (mainline
    SQLite default) is a downstream concern.
11. **No body parsing** — DROP TRIGGER carries no body, no WHERE,
    no expression. The leaf is intentionally minimal and shares NO
    code with `parse_create_trigger`.
12. **Error messages match the drop-stmt family** — for
    cross-statement consistency, error strings follow the same
    pattern as `parts/parser/parts/drop-stmt` ("expected … after
    DROP", "deferred: …").

## Regeneration envelope

- Line budget: **~70–110 lines** per target.
- No dependencies beyond std.
- Public items: `DropTriggerStmt`, `DropTriggerParseOk`,
  `parse_drop_trigger`.

## Smoke probe (out of scope this round — to be added when emission lands)

A future hand-written smoke should cover:

```text
1. DROP TRIGGER tr                  → if_exists=false, name="tr"
2. DROP TRIGGER IF EXISTS tr        → if_exists=true,  name="tr"
3. DROP TRIGGER                     → ParseError "expected trigger name…"
4. DROP TRIGGER main.tr             → ParseError "deferred: schema-qualified…"
```
