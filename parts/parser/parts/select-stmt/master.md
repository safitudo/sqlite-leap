---
name: select-stmt
kind: leaf
emits:
  rust: { path: src-rust/parser/select_stmt.rs }
  c:    { path: src-c/parser/select_stmt.c, headers: [src-c/parser/select_stmt.h] }
---

# SELECT statement parser

Parses a SELECT statement from a `Token` stream produced by
`/parts/parser/parts/tokenizer`, using `parse_expr` from
`/parts/parser/parts/expr` for every embedded expression. This is the
first **statement**-level parser part and validates that the
recursive-descent idiom scales from a ~300-line expression parser to a
larger grammar.

## Scope

Admitted clauses (in grammatical order):
- `SELECT [DISTINCT | ALL]`
- Projection list: `* | table.* | expr [AS alias]` comma-separated.
- `FROM` clause: a `TableRef` tree built from named tables and joins.
  Forms admitted (left-associative, see §JOINs below):
  - single named table with optional alias (`t`, `t AS t2`);
  - comma list `t1, t2` (treated as `t1 CROSS JOIN t2`);
  - `t1 [INNER] JOIN t2 ON <expr>` / `... USING (c1, ...)`;
  - `t1 LEFT [OUTER] JOIN t2 ON <expr>` / `... USING (c1, ...)`;
  - `t1 CROSS JOIN t2` (no ON/USING permitted);
  - 3+ way chains: `a JOIN b ON ... JOIN c ON ...`.
- `WHERE` expr.
- `GROUP BY` expr [, expr]* — comma-separated list of grouping expressions.
- `HAVING` expr — predicate evaluated post-aggregation.
- `ORDER BY` expr [ASC|DESC] comma-separated.
- `LIMIT` expr [`OFFSET` expr].

Deferred (flag ParseError with `"deferred: <construct>"` if seen;
resolve in follow-up leaves):
- RIGHT / FULL / NATURAL JOIN (the keywords are recognized and rejected
  with a clean `"deferred: RIGHT JOIN"` / `"deferred: FULL JOIN"` /
  `"deferred: NATURAL JOIN"` message).
- Subqueries in FROM (derived tables).
- `WITH` (CTE).
- Compound SELECT (UNION / INTERSECT / EXCEPT).
- Window functions (`OVER`).
- Bare-ident implicit alias (`SELECT expr alias` without AS).

## Declared shapes (in `shapes.json`)

- `SelectStmt` — the top-level parsed statement record.
- `ProjectionItem` — 3-case variant: `Star | TableStar | Expr`.
- `TableRef` — recursive variant: `Named { name, alias }` |
  `Joined { left, right, kind, on, using }`.
- `JoinKind` — `Inner | Left | Cross`.
- `OrderByItem` — `{ expr, desc: bool }`.
- `SelectParseOk` — `{ stmt, next: u32 }`.
- `parse_select(tokens, start) -> result<SelectParseOk, ParseError>`.
- `ParseError` is imported from `parts/parser/parts/expr`.

## Algorithm (single-pass recursive descent)

```
parse_select(tokens, i):
    expect tokens[i] == KwSelect; i += 1
    distinct = false
    if tokens[i] == KwDistinct: distinct = true; i += 1
    elif tokens[i] == KwAll:    distinct = false; i += 1

    projection, i = parse_projection_list(tokens, i)
    from,       i = parse_from_opt(tokens, i)
    where_,     i = parse_where_opt(tokens, i)
    group_by,   i = parse_group_by_opt(tokens, i)
    having,     i = parse_having_opt(tokens, i)
    order_by,   i = parse_order_by_opt(tokens, i)
    limit, offset, i = parse_limit_opt(tokens, i)

    return Ok({ distinct, projection, from, where_, group_by, having,
                order_by, limit, offset }, next: i)

parse_group_by_opt(tokens, i):
    if tokens[i] != KwGroup: return [], i
    i += 1
    expect tokens[i] == KwBy; i += 1
    items = []
    loop:
        expr, i = parse_expr(tokens, i)
        items.push(expr)
        if tokens[i] == Comma: i += 1; continue
        break
    return items, i

parse_having_opt(tokens, i):
    if tokens[i] != KwHaving: return None, i
    i += 1
    expr, i = parse_expr(tokens, i)
    return Some(expr), i

parse_projection_list(tokens, i):
    items = []
    loop:
        items.push(parse_projection_item(tokens, i))
        if tokens[i] == Comma: i += 1; continue
        break
    return items, i

parse_projection_item(tokens, i):
    if tokens[i] == Star:
        i += 1; return Star, i
    if tokens[i] == Ident and tokens[i+1] == Dot and tokens[i+2] == Star:
        name = tokens[i].text; i += 3
        return TableStar { table: name }, i
    expr, i = parse_expr(tokens, i)
    alias = None
    if tokens[i] == KwAs and tokens[i+1] == Ident:
        alias = tokens[i+1].text; i += 2
    return Expr { expr, alias }, i

parse_from_opt(tokens, i):
    if tokens[i] != KwFrom: return None, i
    i += 1
    left, i = parse_table_atom(tokens, i)
    # Left-associative join chain.
    loop:
        kind, on, using, right_or_none, i_or_break = try_parse_join_suffix(tokens, i, left)
        if right_or_none is None: break
        left = Joined { left, right: right_or_none, kind, on, using }
        i = i_or_break
    return Some(left), i

parse_table_atom(tokens, i):
    # Subquery / parenthesized table-ref:
    if tokens[i] == LParen:
        return Err("deferred: parenthesized table-ref / subquery in FROM")
    if tokens[i] != Ident: error("expected table name after FROM")
    name = tokens[i].text; i += 1
    alias = None
    if tokens[i] == KwAs and tokens[i+1] == Ident:
        alias = tokens[i+1].text; i += 2
    # bare-ident alias still deferred for now.
    return Named { name, alias }, i

try_parse_join_suffix(tokens, i, left):
    # Returns (kind, on, using, right, next_i) — or signals "no more joins"
    # by returning right=None.
    case tokens[i]:
        Comma:                       # implicit cross
            i += 1
            right = parse_table_atom(tokens, i)
            return (Cross, None, [], right, i')
        KwCross:                     # CROSS JOIN
            i += 1
            expect KwJoin; i += 1
            right = parse_table_atom(tokens, i)
            # CROSS forbids ON/USING:
            if tokens[i'] in {KwOn, KwUsing}: error("CROSS JOIN cannot have ON/USING")
            return (Cross, None, [], right, i')
        KwInner:                     # INNER [JOIN]
            i += 1
            expect KwJoin; i += 1
            right = parse_table_atom(tokens, i)
            on, using, i'' = parse_join_constraint(tokens, i')
            return (Inner, on, using, right, i'')
        KwLeft:                      # LEFT [OUTER] JOIN
            i += 1
            if tokens[i] == KwOuter: i += 1
            expect KwJoin; i += 1
            right = parse_table_atom(tokens, i)
            on, using, i'' = parse_join_constraint(tokens, i')
            return (Left, on, using, right, i'')
        KwJoin:                      # plain JOIN == INNER JOIN
            i += 1
            right = parse_table_atom(tokens, i)
            on, using, i'' = parse_join_constraint(tokens, i')
            return (Inner, on, using, right, i'')
        KwRight:  error("deferred: RIGHT JOIN")
        KwFull:   error("deferred: FULL JOIN")
        KwNatural: error("deferred: NATURAL JOIN")
        else: return (_, _, _, None, i)   # no join suffix; loop ends

parse_join_constraint(tokens, i):
    # ON or USING — at most one of each. INNER/LEFT JOIN must have one.
    if tokens[i] == KwOn:
        i += 1
        expr, i = parse_expr(tokens, i)
        return Some(expr), [], i
    if tokens[i] == KwUsing:
        i += 1
        expect LParen; i += 1
        cols = []
        loop:
            if tokens[i] != Ident: error("expected column ident in USING list")
            cols.push(tokens[i].text); i += 1
            if tokens[i] == Comma: i += 1; continue
            break
        expect RParen; i += 1
        return None, cols, i
    error("expected ON or USING after INNER/LEFT JOIN")

parse_where_opt(tokens, i):
    if tokens[i] != KwWhere: return None, i
    i += 1
    expr, i = parse_expr(tokens, i)
    return Some(expr), i

parse_order_by_opt(tokens, i):
    if tokens[i] != KwOrder: return [], i
    i += 1
    expect tokens[i] == KwBy; i += 1
    items = []
    loop:
        expr, i = parse_expr(tokens, i)
        desc = false
        if tokens[i] == KwDesc: desc = true; i += 1
        elif tokens[i] == KwAsc: desc = false; i += 1
        items.push({ expr, desc })
        if tokens[i] == Comma: i += 1; continue
        break
    return items, i

parse_limit_opt(tokens, i):
    if tokens[i] != KwLimit: return None, None, i
    i += 1
    limit_expr, i = parse_expr(tokens, i)
    offset_expr = None
    if tokens[i] == KwOffset:
        i += 1
        offset_expr, i = parse_expr(tokens, i)
    elif tokens[i] == Comma:
        # SQLite's `LIMIT offset, limit` swapped form — accept and swap
        i += 1
        real_limit, i = parse_expr(tokens, i)
        # swap: what we parsed as `limit` was actually offset
        offset_expr = Some(limit_expr)
        limit_expr  = real_limit
    return Some(limit_expr), offset_expr, i
```

Note the `LIMIT offset, limit` swap: in SQLite the two-arg form with
comma is `(offset, limit)`, the opposite of the `OFFSET`-keyword form.
This is pin #9 below.

## Correctness pins

1. **Distinct / All flag** — `SELECT DISTINCT` sets `distinct=true`;
   `SELECT ALL` is a syntactic no-op (explicitly accepted, same as
   omitting the keyword, `distinct=false`); plain `SELECT` leaves it
   false.
2. **Projection list always non-empty** — `SELECT FROM t` is a
   ParseError with `"expected projection item"`. At least one
   projection item is required.
3. **Projection forms** — `*`, `tablename.*`, `expr`, `expr AS alias`
   each produce the correct variant. `a.b` (column ref with dot)
   inside an expression is still deferred at the expression-parser
   layer (per expr master.md pin 9); here we ONLY accept `Ident.Star`
   as TableStar. An `Ident.Ident` would be a deferred qualified column
   ref passed through to the expression parser, which rejects it —
   and the overall parse fails with the expression parser's error.
4. **FROM optional** — omit FROM entirely and `from: None`. No-FROM
   SELECT (e.g. `SELECT 1 + 2`) is a valid SQLite form.
5. **JOIN forms** — comma-list, `[INNER] JOIN ... ON ...`,
   `[INNER] JOIN ... USING (...)`, `LEFT [OUTER] JOIN ... ON ...`,
   `LEFT [OUTER] JOIN ... USING (...)`, and `CROSS JOIN ...` all parse
   to `TableRef::Joined { left, right, kind, on, using }`. Multi-way
   joins are LEFT-ASSOCIATIVE: `a JOIN b ON p1 JOIN c ON p2` →
   `Joined(Joined(a,b,Inner,Some(p1),[]), c, Inner, Some(p2), [])`.
5a. **JOIN constraint discipline** — `INNER`/`LEFT` JOIN MUST be followed
    by `ON expr` OR `USING (cols...)` — neither is a ParseError
    `"expected ON or USING after INNER/LEFT JOIN"`. `CROSS JOIN` and the
    comma form MUST NOT have ON/USING — both is a ParseError
    `"CROSS JOIN cannot have ON/USING"`. ON and USING are mutually
    exclusive at one join — if both are written, the second is a
    ParseError `"ON and USING are mutually exclusive"`.
5b. **JOIN deferred forms** — `RIGHT JOIN`, `FULL JOIN`, `NATURAL JOIN`,
    parenthesized table-refs, and FROM-clause subqueries all produce
    ParseErrors with a `"deferred: <form>"` message at the first
    unexpected token. (Bare-ident alias `t t2` remains deferred too.)
6. **WHERE accepts any Expr** — delegates to `parse_expr`. Expression
   errors propagate as-is (token_index, line, column preserved).
6a. **GROUP BY** — appears AFTER WHERE, BEFORE HAVING/ORDER BY/LIMIT.
    Comma-separated list of expressions; at least one required after
    `GROUP BY`. Empty list (omitted clause) is the default. Expression
    errors propagate from `parse_expr`. Bare-column GROUP BY (`GROUP
    BY name`) is a `Col` Expr; integer-literal positional GROUP BY
    (`GROUP BY 1`) parses as an `IntLit` and is resolved by the
    compiler to a projection-position reference.
6b. **HAVING** — appears AFTER GROUP BY, BEFORE ORDER BY. Single
    expression; absent if not written. Expression errors propagate.
    Semantic rule (compiler): HAVING references must be aggregates,
    constants, or grouping expressions — enforced downstream.
7. **ORDER BY** — comma-separated list, ASC/DESC each optional per
   item, default ASC. Positional ORDER BY (`ORDER BY 1`) falls through
   because `1` is a valid `IntLit` expression — this is correct
   behavior (the compiler later resolves integer literals in
   ORDER-BY context to column positions).
8. **LIMIT** — `LIMIT n` sets limit only. `LIMIT n OFFSET m` sets
   both. `LIMIT m, n` is the SWAPPED SQLite form: `(offset=m, limit=n)`.
9. **LIMIT/OFFSET swap pin** — `LIMIT 5, 10` produces
   `limit = Some(IntLit(10)), offset = Some(IntLit(5))`. This
   matches SQLite semantics exactly. `LIMIT 5 OFFSET 10` produces
   `limit = Some(IntLit(5)), offset = Some(IntLit(10))`.
10. **Statement terminator** — `parse_select` stops BEFORE the
    terminating `;` or Eof; `SelectParseOk.next` points at whichever
    terminator was reached. The caller checks/consumes.
11. **Owned strings** — every `string` field in the AST (table
    names, aliases) is owned (copied from token's borrowed slice).
12. **Deferred construct errors are informative** — each deferred
    form produces a ParseError whose `message` names the construct
    (`"deferred: JOIN"`, `"deferred: GROUP BY"`, etc.). The parser
    does not silently accept-then-ignore.
13. **No inline tests, no invented helpers** — the file exports
    only `parse_select` plus the locally-necessary sub-parsers
    (projection, from, where, order-by, limit). No cross-part
    state, no tokenizer re-invocation.
14. **Recursive integration** — every embedded expression is parsed
    through the imported `parse_expr`, not a local re-implementation.

## Regeneration envelope

- Line budget: **~300-450 lines** of Rust. The AST types are modest
  (~8 declarations); most of the volume is the parse-*_opt helpers
  and their error messages.
- No dependencies beyond std.
- Public items: `ProjectionItem`, `TableRef`, `OrderByItem`,
  `SelectStmt`, `SelectParseOk`, `parse_select`.

## Smoke probe

`src-rust/examples/select_smoke.rs` (hand-written, NOT regenerated)
tokenizes + parses eight SELECT statements and asserts the resulting
AST shape against a hand-built `SelectStmt` literal:

```text
1. SELECT 1                           → no FROM, projection=[IntLit(1)]
2. SELECT * FROM t                    → projection=[Star], from=Named("t")
3. SELECT a, b FROM t                 → projection=[Col(a), Col(b)]
4. SELECT DISTINCT x FROM t           → distinct=true
5. SELECT * FROM t WHERE x = 1        → where=Binary(Eq, Col(x), IntLit(1))
6. SELECT * FROM t ORDER BY a DESC, b → order_by has two items
7. SELECT * FROM t LIMIT 10           → limit=Some(IntLit(10)), offset=None
8. SELECT * FROM t LIMIT 5, 10        → limit=Some(10), offset=Some(5)  [swap]
```

Runner prints `OK: all N statements parse to expected shape` on
success.
