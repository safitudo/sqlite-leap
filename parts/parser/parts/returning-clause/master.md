---
name: returning-clause
kind: leaf
emits:
  rust: { path: src-rust/parser/returning_clause.rs }
  c:    { path: src-c/parser/returning_clause.c, headers: [src-c/parser/returning_clause.h] }
---

# RETURNING-clause parser fragment

Shared parser fragment for the trailing `RETURNING <result_column> [, ...]`
clause that may appear on `INSERT`, `UPDATE`, and `DELETE` statements.

Originally inlined inside `insert-stmt` (because INSERT was the first DML
statement to land), but `delete-stmt` and `update-stmt` consume the same
function via cross-module reference. Promoting it to its own leaf makes
the contract explicit and breaks the implicit dependency that
`delete-stmt` / `update-stmt` have on a phantom public symbol exposed by
`insert-stmt`'s emission.

The `ResultColumn` type itself stays owned by `insert-stmt` for now (all
three callers already import it from there); only the parsing function
moves.

## Scope

Admitted:
- A leading `RETURNING` keyword followed by a comma-separated list of
  result columns. Each result column is one of:
  - `*` — every column of the affected row.
  - `<ident> .*` — every column of one table.
  - `<expr> [AS <ident>]` — a single projection, optionally aliased.
- Absence of a `RETURNING` keyword at the cursor position — returns an
  empty list and the unchanged token index.

Deferred (caller raises before reaching the fragment):
- `RETURNING` with surrounding parentheses — disallowed by SQL grammar.
- `RETURNING DISTINCT ...` — not part of the SQLite surface.

## Algorithm

```
parse_returning_opt(tokens, start):
    i = start
    if kind_at(tokens, i) != KwReturning:
        return ([], i)        # no clause present, no consumption
    i += 1
    items = []
    loop:
        item = match kind_at(tokens, i):
            Star                              -> ResultColumn::Star;          i += 1
            Ident(t) followed by Dot, Star    -> ResultColumn::TableStar{t};  i += 3
            otherwise                          -> parse_expr(tokens, i),
                                                  optional KwAs + Ident alias,
                                                  ResultColumn::Expr{expr, alias}
        items.push(item)
        if kind_at(tokens, i) == Comma:
            i += 1
            continue
        break
    return (items, i)
```

## Correctness pins

1. **Absent clause** — when the token at `start` is not `KwReturning`,
   return `([], start)` without consuming.
2. **Star item** — `RETURNING *` produces `[ResultColumn::Star]`.
3. **Table-star item** — `RETURNING t.*` produces
   `[ResultColumn::TableStar { table: "t" }]`.
4. **Expr item** — `RETURNING a` produces
   `[ResultColumn::Expr { expr: <Col a>, alias: None }]`.
5. **Aliased expr** — `RETURNING a AS x` sets `alias = Some("x")`.
6. **Multi-item list** — `RETURNING *, b, c.*` parses three items in order.
7. **Trailing comma rejected** — `RETURNING a,` raises a `ParseError`.
8. **Returns next index** — the second tuple element points to the first
   token AFTER the clause, ready for the caller's next sub-parser.

## Declared shapes (in `shapes.json`)

- `parse_returning_opt(tokens, start) -> result<(list<ResultColumn>, u32), ParseError>`
  (imports `ResultColumn` from `/parts/parser/parts/insert-stmt`,
  `Token`/`TokenKind` from `/parts/parser/parts/tokenizer`,
  `ParseError` from `/parts/parser/parts/expr`).

## Regeneration envelope

- Line budget: **~50-100 lines** of Rust / **~80-150 lines** of C.
- No dependencies beyond std + the imports above.
- Public items: `parse_returning_opt`.

## Callers

`insert-stmt`, `delete-stmt`, and `update-stmt` each invoke
`parse_returning_opt` once at the tail of their own statement-parser.
None of them re-implement the loop.
