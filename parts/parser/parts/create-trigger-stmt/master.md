---
name: create-trigger-stmt
kind: leaf
emits:
  rust: { path: src-rust/parser/create_trigger_stmt.rs }
  c:    { path: src-c/parser/create_trigger_stmt.c, headers: [src-c/parser/create_trigger_stmt.h] }
---

# CREATE TRIGGER statement parser

Parses a `CREATE TRIGGER` statement from a `Token` stream, delegating
each statement of the trigger body to the appropriate per-statement
parser (`parse_insert`, `parse_update`, `parse_delete`, `parse_select`)
and the `WHEN` predicate to `parse_expr`. The first parser leaf whose
output is a *list of statements* — the trigger body — and therefore the
first leaf whose AST contains references to every DML statement
parser. Pure parser concern: no compilation, no execution, no
storage.

## Scope

Admitted (matches the published `CREATE TRIGGER` grammar at
sqlite.org/lang_createtrigger.html):

- `CREATE [TEMP|TEMPORARY] TRIGGER [IF NOT EXISTS] <name>`
- Timing: `BEFORE | AFTER | INSTEAD OF` (one required).
- Event:
  - `DELETE ON <table>`
  - `INSERT ON <table>`
  - `UPDATE [OF <col> [, <col>]*] ON <table>`
- Optional `FOR EACH ROW`. (Statement-level triggers — the absence
  of `FOR EACH ROW` — are admitted but mapped to the same row-level
  semantics by the compiler. Parser only records the flag.)
- Optional `WHEN <expr>` predicate.
- Body: `BEGIN <stmt> [; <stmt>]* [;] END`. Each `<stmt>` is one of
  `INSERT`, `UPDATE`, `DELETE`, `SELECT`. Each statement is followed
  by a mandatory `;`. The closing `END` may be followed by an
  outer-statement terminator the caller consumes (`;` or Eof).

Deferred (flagged with `deferred: <construct>` ParseError):

- Schema-qualified trigger or table name (`main.tr`, `main.t`).
- `CREATE TRIGGER` without `BEFORE | AFTER | INSTEAD OF` — SQL
  default is `BEFORE`, but the parser requires the keyword for
  clarity (deferred: `implicit BEFORE`).
- Body statements other than INSERT / UPDATE / DELETE / SELECT
  (e.g. nested `CREATE`, `DROP`, `WITH ... INSERT`).
- `RAISE(...)` expression in `WHEN` or body — the expression parser
  does not yet recognise it; surfaces as a normal expression error.

## Declared shapes (in `shapes.json`)

- `TriggerTiming` — variant `Before | After | InsteadOf`.
- `TriggerEvent` — variant `Delete | Insert | UpdateOf { columns }`.
  `Update` with no column list is encoded as `UpdateOf { columns: [] }`.
- `TriggerBodyStmt` — variant wrapping each admitted body statement
  kind: `Insert(InsertStmt) | Update(UpdateStmt) | Delete(DeleteStmt) | Select(SelectStmt)`.
- `CreateTriggerStmt` — top-level record (see shapes.json for full shape).
- `CreateTriggerParseOk` — `{ stmt, next: u32 }`.

## Algorithm (single-pass recursive descent)

```
parse_create_trigger(tokens, i):
    expect tokens[i] == KwCreate; i += 1
    is_temp = false
    if tokens[i] in {KwTemp, KwTemporary}: is_temp = true; i += 1
    expect tokens[i] == KwTrigger; i += 1
    if_not_exists = false
    if tokens[i] == KwIf:
        i += 1
        expect tokens[i] == KwNot;    i += 1
        expect tokens[i] == KwExists; i += 1
        if_not_exists = true
    if tokens[i] != Ident: error("expected trigger name")
    name = tokens[i].text; i += 1
    if tokens[i] == Dot: error("deferred: schema-qualified trigger name")

    timing, i = parse_timing(tokens, i)
    event,  i = parse_event(tokens, i)

    expect tokens[i] == KwOn; i += 1
    if tokens[i] != Ident: error("expected table name after ON")
    table = tokens[i].text; i += 1
    if tokens[i] == Dot: error("deferred: schema-qualified table name")

    for_each_row = false
    if tokens[i] == KwFor:
        i += 1
        expect tokens[i] == KwEach;  i += 1
        expect tokens[i] == KwRow;   i += 1
        for_each_row = true

    when_ = None
    if tokens[i] == KwWhen:
        i += 1
        expr, i = parse_expr(tokens, i)
        when_ = Some(expr)

    expect tokens[i] == KwBegin; i += 1
    body, i = parse_trigger_body(tokens, i)
    expect tokens[i] == KwEnd; i += 1

    return Ok({ name, is_temp, if_not_exists, timing, event, table,
                for_each_row, when_, body }, next: i)

parse_timing(tokens, i):
    case tokens[i]:
        KwBefore:  return Before,    i+1
        KwAfter:   return After,     i+1
        KwInstead: expect KwOf at i+1;  return InsteadOf, i+2
    error("expected BEFORE / AFTER / INSTEAD OF")

parse_event(tokens, i):
    case tokens[i]:
        KwDelete: return Delete, i+1
        KwInsert: return Insert, i+1
        KwUpdate:
            i += 1
            cols = []
            if tokens[i] == KwOf:
                i += 1
                loop:
                    if tokens[i] != Ident: error("expected column name in UPDATE OF list")
                    cols.push(tokens[i].text); i += 1
                    if tokens[i] == Comma: i += 1; continue
                    break
            return UpdateOf { columns: cols }, i
    error("expected DELETE / INSERT / UPDATE")

parse_trigger_body(tokens, i):
    stmts = []
    loop:
        if tokens[i] == KwEnd: break
        s, i = parse_one_body_stmt(tokens, i)
        stmts.push(s)
        if tokens[i] != Semicolon: error("expected ';' after trigger body statement")
        i += 1
        # next iteration will see either another stmt or KwEnd
    if stmts.len() == 0: error("trigger body must contain at least one statement")
    return stmts, i

parse_one_body_stmt(tokens, i):
    case tokens[i]:
        KwInsert: ok, i = parse_insert(tokens, i); return Insert(ok.stmt), i
        KwUpdate: ok, i = parse_update(tokens, i); return Update(ok.stmt), i
        KwDelete: ok, i = parse_delete(tokens, i); return Delete(ok.stmt), i
        KwSelect: ok, i = parse_select(tokens, i); return Select(ok.stmt), i
        else:     error("trigger body statement must be INSERT/UPDATE/DELETE/SELECT")
```

## Correctness pins

1. **Minimal AFTER INSERT** — `CREATE TRIGGER tr AFTER INSERT ON t
   BEGIN SELECT 1; END` parses to `{ name: "tr", is_temp: false,
   if_not_exists: false, timing: After, event: Insert, table: "t",
   for_each_row: false, when_: None, body: [Select(...)] }`.
2. **Timing keyword required** — bare `CREATE TRIGGER tr INSERT ON t
   ...` (no BEFORE/AFTER/INSTEAD OF) is `deferred: implicit BEFORE`.
   The grammar treats absence as a deferred form to keep both target
   generators free of an implicit-default branch.
3. **INSTEAD OF is two tokens** — `INSTEAD OF` consumes `KwInstead`
   then `KwOf`. A bare `KwInstead` not followed by `KwOf` is
   `"expected OF after INSTEAD"`.
4. **UPDATE OF column list** — `BEFORE UPDATE OF a, b ON t ...`
   produces `event = UpdateOf { columns: ["a", "b"] }`. Plain
   `UPDATE ON t` produces `UpdateOf { columns: [] }`. The empty list
   is the canonical "any column" form.
5. **FOR EACH ROW flag** — the keywords FOR EACH ROW MUST appear in
   sequence; partial occurrence (`FOR EACH` without `ROW`) is a
   ParseError. Statement-level triggers (no FOR EACH ROW) parse with
   `for_each_row = false`; the parser does not reject them. Compiler
   semantics for statement-level vs row-level are owned by
   `/parts/compiler/parts/triggers/`.
6. **WHEN delegates to parse_expr** — the WHEN predicate is parsed
   through the imported `parse_expr`. Expression-parser errors
   propagate verbatim (token_index, line, column preserved).
7. **WHEN may reference OLD/NEW** — at parse time, `OLD` and `NEW`
   are ordinary identifiers; the qualifier is captured via the
   expression parser's column-reference path. Resolution happens at
   compile time. The trigger parser does NOT validate
   OLD-only-on-DELETE / NEW-only-on-INSERT — that is a compiler pin.
8. **Body delimited by BEGIN/END** — both keywords required. A body
   statement MUST be followed by `;`. The final `;` before `END` is
   mandatory (the published grammar requires it).
9. **Body is non-empty** — `BEGIN END` is `"trigger body must
   contain at least one statement"`. (The published grammar allows
   an empty body via repetition `(stmt ';')*`; we reject it for
   clarity. If a downstream test requires empty bodies, this pin
   relaxes — note as a candidate spec change rather than fix in
   target.)
10. **Body delegates to per-statement parsers** — each body stmt is
    parsed by importing the corresponding parser leaf:
    `parse_insert`, `parse_update`, `parse_delete`, `parse_select`.
    No body-statement re-implementation in this leaf.
11. **Body statement kinds restricted** — anything other than
    INSERT/UPDATE/DELETE/SELECT (e.g. `CREATE`, `DROP`, `BEGIN`,
    `COMMIT`, `WITH`) at body-statement position is a ParseError
    `"trigger body statement must be INSERT/UPDATE/DELETE/SELECT"`.
12. **Statement terminator** — `parse_create_trigger` stops AFTER
    consuming the closing `END`; `next` points at the outer
    terminator (`;` or Eof) the caller still consumes.
13. **TEMP / TEMPORARY are equivalent** — both keywords admitted,
    both set `is_temp = true`.
14. **IF NOT EXISTS** — three-token sequence (KwIf, KwNot, KwExists);
    partial sequence is a ParseError. Sets `if_not_exists = true`.
15. **Schema-qualified names rejected** — both `main.tr` (after
    trigger name) and `main.t` (after `ON`) produce
    `"deferred: schema-qualified <kind> name"`.
16. **Owned strings** — `name`, `table`, every UPDATE-OF column name,
    and every owned-string field of a body stmt are copied from the
    token's borrowed slice.
17. **No inline tests, no invented helpers** — file exports only
    `parse_create_trigger` plus the locally-necessary sub-parsers
    (`parse_timing`, `parse_event`, `parse_trigger_body`). Body
    statement parsing is delegated, not duplicated.
18. **Recursive integration** — the WHEN clause goes through
    `parse_expr`; body statements through their owning parsers. No
    local re-implementation of any expression or statement form.
19. **Two-keyword pairs are atomic** — a partial match for `INSTEAD
    OF`, `FOR EACH ROW`, `IF NOT EXISTS` MUST raise an error at the
    first missing token, not silently accept and reposition.
20. **Parser does not enforce trigger semantics** — type-check of
    OLD/NEW availability per event kind, INSTEAD-OF-only-on-views,
    cycle detection, recursive-trigger semantics — all live in the
    compiler. The parser's job ends at producing a structurally
    valid `CreateTriggerStmt`.

## Regeneration envelope

- Line budget: **~250–400 lines** per target.
- Public items: `TriggerTiming`, `TriggerEvent`, `TriggerBodyStmt`,
  `CreateTriggerStmt`, `CreateTriggerParseOk`, `parse_create_trigger`.

## Smoke probe (out of scope this round — to be added when emission lands)

A future hand-written `examples/create_trigger_smoke.rs` should cover:

```text
1. CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END
   → minimal AFTER INSERT, no WHEN, single SELECT body.
2. CREATE TRIGGER tr BEFORE UPDATE OF a, b ON t FOR EACH ROW
   WHEN OLD.a > 0 BEGIN UPDATE log SET n = n + 1; END
   → UpdateOf with cols, for_each_row=true, when_ present.
3. CREATE TRIGGER IF NOT EXISTS tr INSTEAD OF DELETE ON v
   BEGIN DELETE FROM t WHERE id = OLD.id; END
   → InsteadOf timing, if_not_exists=true.
4. CREATE TEMP TRIGGER tr AFTER INSERT ON t BEGIN
     INSERT INTO log VALUES (NEW.id);
     UPDATE counter SET n = n + 1;
   END
   → is_temp=true, body length 2.
5. CREATE TRIGGER tr AFTER INSERT ON t BEGIN END  → ParseError.
6. CREATE TRIGGER tr INSERT ON t BEGIN SELECT 1; END
   → ParseError "deferred: implicit BEFORE".
```
