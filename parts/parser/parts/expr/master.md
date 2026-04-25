---
name: expr
kind: leaf
emits:
  rust: { path: src-rust/parser/expr.rs }
---

# SQL expression parser (Pratt precedence probe)

Parses a single SQL expression from a token stream produced by
`/parts/parser/parts/tokenizer`. Implements Pratt operator precedence
at the full SQLite tier count. The structural unknown this probe closes:
**can the shape grammar carry a recursive AST plus a Pratt table to a
target emission without the agent inventing helpers, handwriting an
ad-hoc table, or reaching for a parser-generator crate?**

## Scope

Admitted:
- Literals: `IntLit`, `RealLit`, `StrLit`, `Null`.
- Column references (unqualified): `colname`.
- Function calls: `NAME(arg0, arg1, ...)`, including `NAME()`. Three
  call-form sugars are admitted (parser-level desugar; no AST variant):
  - `NAME(*)` — wildcard arg form, used by `count(*)`. Rewrites to
    `Call { name: <name> + "_star", args: [] }`. The select compiler
    recognizes `count_star` as `AggFuncKind::CountStar`. For names
    other than `count`, the rewrite still runs structurally;
    downstream compilation rejects unknown `<name>_star` builtins.
  - `NAME(DISTINCT arg)` — distinct-arg form, used by `count(DISTINCT
    expr)`. Rewrites to `Call { name: <name> + "_distinct", args:
    [arg] }`. The compiler maps `count_distinct` to
    `AggFuncKind::CountDistinct`; for other names, downstream
    compilation rejects.
  - `NAME(ALL arg)` — explicit-all keyword. The `ALL` keyword is
    consumed and discarded; the result is `Call { name: <name>,
    args: [arg] }` — identical to the bare form. SQL standard noise
    word for aggregates.
  Only ONE of `*` / `DISTINCT` / `ALL` may appear, and only as the
  FIRST token after `(`. `count(DISTINCT a, b)` is a parser error
  (`"DISTINCT call argument must be a single expression"`).
  `count(*)` with additional args is a parser error
  (`"'*' wildcard argument cannot be combined with other arguments"`).
- Parenthesized sub-expressions: `(expr)` — no AST node, shape only.
- Prefix unary: `-expr`, `NOT expr`.
- Binary operators at the precedence tiers in §Precedence below.
- Postfix null test: `expr IS NULL` and `expr IS NOT NULL`. Produces
  an `IsNull { arg, negated }` AST node. `IS` acts as a postfix
  operator at comparison-tier precedence (`lbp = 5`, no `rbp` — no
  right operand). See §Algorithm.
- `expr BETWEEN lo AND hi` and `expr NOT BETWEEN lo AND hi` — **parser-level
  desugar**, no AST variant. Rewrites to
  `Binary(And, Binary(Ge, expr, lo), Binary(Le, expr, hi))` for
  BETWEEN (and wraps in `Unary(Not, ...)` for NOT BETWEEN).
  `expr` is AST-duplicated (cloned) — each target renders the clone
  per its mapping (Rust: `Box::new(expr.clone())`; C: deep-copy via
  the existing expr heap-dup helper). Precedence: postfix at
  comparison tier (`lbp = 5`); the `lo AND hi` right side is parsed
  with `AND` specifically (NOT the generic AND operator).
- `expr IN (e1, e2, ...)` and `expr NOT IN (e1, e2, ...)` — **parser-level
  desugar**, no AST variant. Empty list: rewrites to `IntLit("0")`
  (always false) for IN, `IntLit("1")` (always true) for NOT IN.
  Non-empty list: rewrites to an Or-chain of `Binary(Eq, expr,
  e_i)`, wrapped in `Unary(Not, ...)` for NOT IN. `expr` is cloned
  per item. Precedence: postfix at comparison tier. Subquery form
  `IN (SELECT ...)` is deferred.
- `CAST(expr AS type)` — prefix construct on `KwCast`. After `KwCast` expect
  `LParen`, parse inner expression at bp=0, expect `KwAs`, expect an `Ident`
  (the type name), expect `RParen`. Produces `Cast { expr, type_name }` where
  `type_name` is the raw ident text (uppercased to canonicalise common forms:
  `integer` / `Integer` / `INTEGER` all become `"INTEGER"`).
- `expr LIKE pattern`, `expr NOT LIKE pattern`, `expr LIKE pattern ESCAPE esc`,
  `expr NOT LIKE pattern ESCAPE esc`, `expr GLOB pattern`, `expr NOT GLOB pattern` —
  postfix at comparison-tier precedence (`lbp = 5`). Parses pattern at bp=5
  so AND/OR don't bleed in. ESCAPE is admitted only for LIKE; parser rejects
  `GLOB ... ESCAPE ...` with a ParseError. Produces
  `Like { expr, pattern, escape, negated, kind }`.
- `expr COLLATE name` — postfix at the highest precedence tier (`lbp = 21`,
  binds tighter than Concat). After `KwCollate`, expect an `Ident` for the
  collation name. Produces `Collate { expr, name }` where `name` is the
  surface ident text uppercased.
- `CASE ... END` — searched and simple forms. Searched:
  `CASE WHEN p1 THEN r1 [WHEN p2 THEN r2 ...] [ELSE e] END` produces
  `Case { branches: [(p1, r1), (p2, r2), ...], else_: Some(e) | None }`.
  Simple: `CASE x WHEN v1 THEN r1 [WHEN v2 THEN r2 ...] [ELSE e] END`
  is **desugared at parse time** into searched form: each branch
  becomes `(Binary(Eq, clone(x), v_i), r_i)`. `x` is cloned per
  branch using the target's AST-clone operation. Downstream
  compilers only see searched-form `Case`. Must have at least one
  WHEN/THEN pair. Parsed as a prefix construct (atom-level), not
  postfix — `CASE ... END` is a self-contained expression that
  participates in binary operators like any atom.

Deferred (not parsed by this probe; parser returns ParseError if
encountered):
- Table-qualified column references (`t.col`).
- REGEXP / MATCH (LIKE / GLOB / CAST / COLLATE are now admitted — see above).
- Subqueries (`(SELECT ...)`) and `EXISTS (SELECT ...)` — these introduce a
  parser dependency on `/parts/parser/parts/select-stmt::SelectStmt`. They
  are deferred from this batch because select-stmt is being concurrently
  edited by another agent. To be added as a follow-up: `Subquery { stmt }`,
  `Exists { stmt, negated }` Expr variants.
- Blob literals, parameter placeholders.
- General `IS` operator (`a IS b`), `ISNULL` / `NOTNULL` keyword
  forms, `IS DISTINCT FROM`. Only postfix `IS NULL` / `IS NOT NULL`
  is admitted (see above).
- `IN (SELECT ...)` subquery form. Only `IN (expr, expr, ...)` with
  a literal/expression list is admitted.
- REGEXP / MATCH operators (LIKE / GLOB / COLLATE are admitted).
- Bitwise NOT `~`, unary `+`.
- Window functions, `OVER` clauses.

## Declared shapes (in `shapes.json`)

- `Expr` — recursive variant; literal cases carry owned text, `Binary`
  and `Unary` carry sub-expressions, `Call.args` is `list<Expr>`.
- `UnaryOp` — `Neg | Not`.
- `BinaryOp` — 18 cases covering the tiers below.
- `ParseError` — `{ token_index, line, column, message: string }`.
- `ParseOk` — `{ expr, next: u32 }`.
- `parse_expr(tokens: &[Token], start: u32) -> Result<ParseOk, ParseError>`.

## Precedence (low → high, all binary operators left-associative)

| Tier | Operators             | BinaryOp cases                 |
|------|-----------------------|--------------------------------|
| 1    | `OR`                  | `Or`                           |
| 2    | `AND`                 | `And`                          |
| 3    | `=` `==` `!=` `<>`    | `Eq` `NotEq`                   |
| 4    | `<` `<=` `>` `>=`     | `Lt` `Le` `Gt` `Ge`            |
| 5    | `|`                   | `BitOr`                        |
| 6    | `&` `<<` `>>`         | `BitAnd` `ShiftL` `ShiftR`     |
| 7    | `+` `-`               | `Plus` `Minus`                 |
| 8    | `*` `/` `%`           | `Mul` `Div` `Mod`              |
| 9    | `||`                  | `Concat`                       |

Prefix unary operators bind **tighter than any binary** (effective
precedence 10):
- `-` → `UnaryOp::Neg`.
- `NOT` → `UnaryOp::Not`. Despite the SQLite docs placing NOT just
  above AND, in practice SQLite treats `NOT a = b` as `NOT (a = b)`.
  For this probe we adopt the simpler "NOT binds tighter than any
  binary" rule; tests use `NOT (expr)` where grouping matters. This
  is a documented probe simplification, not a final parser decision.

Tokens `=` and `==` both map to `BinaryOp::Eq`; `!=` and `<>` both
map to `BinaryOp::NotEq`. The parser does not preserve the surface
spelling.

## Algorithm (Pratt / operator-precedence)

```
parse_expr(tokens, start):
    return parse_bp(tokens, start, min_bp=0)

parse_bp(tokens, i, min_bp):
    (lhs, i) = parse_prefix(tokens, i)          # atom or unary
    loop:
        tok = tokens[i]
        # Postfix IS NULL / IS NOT NULL at comparison tier.
        if tok.kind == KwIs and lbp_postfix_is(5) >= min_bp:
            (lhs, i) = parse_is_postfix(tokens, i, lhs)
            continue
        # Postfix BETWEEN / NOT BETWEEN at comparison tier.
        if (tok.kind == KwBetween or
            (tok.kind == KwNot and tokens[i+1].kind == KwBetween))
           and 5 >= min_bp:
            (lhs, i) = parse_between_postfix(tokens, i, lhs)
            # parse_between_postfix: consume BETWEEN, parse bp=5 for lo,
            # require KwAnd, parse bp=5 for hi, rewrite as
            # Binary(And, Binary(Ge, clone(lhs), lo), Binary(Le, clone(lhs), hi))
            # (wrapped in Unary(Not, ...) for NOT BETWEEN).
            continue
        # Postfix IN / NOT IN at comparison tier.
        if (tok.kind == KwIn or
            (tok.kind == KwNot and tokens[i+1].kind == KwIn))
           and 5 >= min_bp:
            (lhs, i) = parse_in_postfix(tokens, i, lhs)
            # parse_in_postfix: consume IN, require LParen, parse
            # comma-separated exprs (at bp=0 — full precedence), require
            # RParen. Rewrite:
            #   empty list  → IntLit("0") (or IntLit("1") for NOT IN)
            #   one item    → Binary(Eq, lhs, e) (wrapped in Not if NOT IN)
            #   n items     → left-fold as Binary(Or, Binary(Or, ...), Binary(Eq, lhs, e_n))
            continue
        # Postfix LIKE / NOT LIKE / GLOB / NOT GLOB at comparison tier (lbp=5).
        if (tok.kind == KwLike or tok.kind == KwGlob or
            (tok.kind == KwNot and (tokens[i+1].kind == KwLike or tokens[i+1].kind == KwGlob)))
           and 5 >= min_bp:
            (lhs, i) = parse_like_postfix(tokens, i, lhs)
            continue
        # Postfix COLLATE at highest precedence tier (lbp=21).
        if tok.kind == KwCollate and 21 >= min_bp:
            (lhs, i) = parse_collate_postfix(tokens, i, lhs)
            continue
        (op, lbp, rbp) = infix_lookup(tok.kind)  # None if tok is not an infix op
        if op is None or lbp < min_bp:
            break
        i += 1                                   # consume the infix op
        (rhs, i) = parse_bp(tokens, i, rbp)      # parse right side with rbp
        lhs = Binary { op, lhs, rhs }
    return (lhs, i)

parse_prefix(tokens, i):
    tok = tokens[i]
    match tok.kind:
        Minus            -> unary Neg, with operand parsed at bp 10
        KwNot            -> unary Not, with operand parsed at bp 10
        IntLit|RealLit|StrLit
                         -> literal node, i+=1
        KwNull           -> Null node, i+=1
        Ident (name)     -> look at tokens[i+1]:
                            LParen  -> Call(name, args); parse arg list:
                                       peek tokens[i+2]:
                                         Star      -> consume; expect RParen;
                                                       Call(name+"_star", [])
                                         KwDistinct-> consume; parse one expr at bp=0;
                                                       expect RParen;
                                                       Call(name+"_distinct", [arg])
                                         KwAll     -> consume; parse comma-list;
                                                       Call(name, args)
                                         else      -> parse comma-list;
                                                       Call(name, args)
                            else     -> Col(name)
        LParen           -> '(' expr ')' — parse inner expr, expect RParen
        KwCase           -> parse_case(tokens, i)
        KwCast           -> parse_cast(tokens, i)
        _                -> ParseError("expected prefix expression")

parse_cast(tokens, i):
    # i points at KwCast.
    i += 1
    require tokens[i] == LParen; i += 1
    (inner, i) = parse_bp(tokens, i, 0)
    require tokens[i] == KwAs; i += 1
    require tokens[i] is Ident; type_name = uppercase(text); i += 1
    require tokens[i] == RParen; i += 1
    return (Cast { expr: inner, type_name }, i)

parse_like_postfix(tokens, i, lhs):
    # i points at KwLike/KwGlob OR at KwNot with KwLike/KwGlob at i+1.
    negated = false
    if tokens[i] == KwNot: negated = true; i += 1
    kind = tokens[i] == KwLike ? LikeKind::Like : LikeKind::Glob
    is_glob = (kind == LikeKind::Glob)
    i += 1
    (pat, i) = parse_bp(tokens, i, 5)        # pattern at bp=5 to keep AND/OR out
    escape = None
    if tokens[i] == KwEscape:
        if is_glob: return ParseError("ESCAPE not allowed with GLOB")
        i += 1
        (esc, i) = parse_bp(tokens, i, 5)
        escape = Some(esc)
    return (Like { expr: lhs, pattern: pat, escape, negated, kind }, i)

parse_collate_postfix(tokens, i, lhs):
    # i points at KwCollate.
    i += 1
    require tokens[i] is Ident; name = uppercase(text); i += 1
    return (Collate { expr: lhs, name }, i)

parse_case(tokens, i):
    # i points at KwCase. Consume it.
    i += 1
    # Determine form by peeking: if tokens[i].kind != KwWhen, it's simple form.
    operand = None
    if tokens[i].kind != KwWhen:
        (operand_expr, i) = parse_bp(tokens, i, min_bp=0)
        operand = Some(operand_expr)
    branches = []
    # Require at least one WHEN/THEN pair.
    while tokens[i].kind == KwWhen:
        i += 1
        (when_expr, i) = parse_bp(tokens, i, min_bp=0)
        if tokens[i].kind != KwThen:
            return ParseError("expected THEN after WHEN predicate")
        i += 1
        (then_expr, i) = parse_bp(tokens, i, min_bp=0)
        # Simple-form desugar: rewrite when_expr to `Eq(clone(operand), when_expr)`.
        if operand is Some(x):
            when_expr = Binary { op: Eq, lhs: clone(x), rhs: when_expr }
        branches.push(CaseBranch { when_expr, then_expr })
    if branches is empty:
        return ParseError("CASE requires at least one WHEN branch")
    else_ = None
    if tokens[i].kind == KwElse:
        i += 1
        (else_expr, i) = parse_bp(tokens, i, min_bp=0)
        else_ = Some(else_expr)
    if tokens[i].kind != KwEnd:
        return ParseError("expected END to close CASE")
    i += 1
    return (Case { branches, else_ }, i)
```

Left-associativity is encoded by using the same `lbp` and `rbp` for
each operator (e.g. `Or` has `lbp = 1`, `rbp = 2`). Right-associativity
would use `rbp = lbp`.

Precedence table expressed as binding powers (`lbp`, `rbp`):

| Token kind   | BinaryOp  | lbp | rbp |
|--------------|-----------|-----|-----|
| `KwOr`       | Or        | 1   | 2   |
| `KwAnd`      | And       | 3   | 4   |
| `Eq`/`EqEq`  | Eq        | 5   | 6   |
| `NotEq`/`NotEqBang` | NotEq | 5 | 6   |
| `Lt`         | Lt        | 7   | 8   |
| `LtEq`       | Le        | 7   | 8   |
| `Gt`         | Gt        | 7   | 8   |
| `GtEq`       | Ge        | 7   | 8   |
| `BitOr`      | BitOr     | 9   | 10  |
| `BitAnd`     | BitAnd    | 11  | 12  |
| `ShiftL`     | ShiftL    | 11  | 12  |
| `ShiftR`     | ShiftR    | 11  | 12  |
| `Plus`       | Plus      | 13  | 14  |
| `Minus`      | Minus     | 13  | 14  |
| `Star`       | Mul       | 15  | 16  |
| `Slash`      | Div       | 15  | 16  |
| `Percent`    | Mod       | 15  | 16  |
| `Concat`     | Concat    | 17  | 18  |

Unary prefix `Minus` and `KwNot` recurse with `min_bp = 19` so they
bind tighter than every binary.

## Correctness pins

1. **Recursive AST** — `Binary.lhs`, `Binary.rhs`, `Unary.arg`, each
   `Call.args[i]` are themselves `Expr` nodes. The target emission
   renders self-referencing variant fields per the target mapping's
   convention (Rust: `Box<Expr>`; if the mapping does not declare a
   convention, STOP and surface the gap).
2. **All 18 binary operators** — every `BinaryOp` case maps from at
   least one TokenKind per the table above. `Eq` and `NotEq` are
   reached by two surface tokens each; the AST does not preserve
   which.
3. **Left-associativity by default** — `1 + 2 + 3` parses as
   `Binary(Plus, Binary(Plus, 1, 2), 3)`.
4. **Precedence respected** — `a + b * c` parses as
   `Binary(Plus, a, Binary(Mul, b, c))`; `a * b + c` parses as
   `Binary(Plus, Binary(Mul, a, b), c)`.
5. **Prefix unary binds tighter than any binary** — `-a + b` parses
   as `Binary(Plus, Unary(Neg, a), b)`; `NOT a AND b` parses as
   `Binary(And, Unary(Not, a), b)`.
6. **Parentheses override precedence** — `(a + b) * c` parses as
   `Binary(Mul, Binary(Plus, a, b), c)`. Parens do NOT produce a
   distinct AST node; the inner expression is the whole result.
7. **Function calls** — `f(a, b, c)` parses as
   `Call { name: "f", args: [a, b, c] }`. `f()` parses with empty
   args. A trailing comma before `)` is a ParseError. Nested calls
   `f(g(x), y)` produce a recursive `Call` inside `args`.
   Three sugars (parser-level desugar; no AST variant added):
   - `count(*)` parses as `Call { name: "count_star", args: [] }`.
     Wildcard with extra args (`count(*, x)`) is a ParseError
     `"'*' wildcard argument cannot be combined with other arguments"`.
   - `count(DISTINCT x)` parses as
     `Call { name: "count_distinct", args: [x] }`. The DISTINCT
     keyword is consumed; exactly one expression must follow before
     `)`. More than one yields ParseError
     `"DISTINCT call argument must be a single expression"`.
   - `agg(ALL x)` parses as `Call { name: "agg", args: [x] }` —
     identical to the bare form. ALL is a noise keyword.
   The sugar applies regardless of `<name>`; semantic rejection of
   non-aggregate uses (e.g. `lower(*)`) is a downstream compiler
   responsibility.
8. **Column vs call disambiguation** — an `Ident` token followed by
   `LParen` is always a `Call`; otherwise it's a `Col`. No lookahead
   beyond one token is required.
9. **Deferred constructs → ParseError** — encountering a token kind
   not in the admitted set (e.g. `KwCase`, `KwBetween`, `Dot` after
   ident) produces a ParseError with `message` naming the
   unsupported construct (`"deferred: CASE"`, `"deferred: qualified
   column reference"`, etc.) and pointing at the offending token.
10. **End-of-stream handling** — a successful parse returns `next`
    pointing at the first token not consumed. Running off the end
    of a sub-expression (e.g. `1 +` with no following operand)
    returns a ParseError at the Eof token with message
    `"unexpected end of expression"`.
11. **Owned strings** — every `string` field in the AST is owned
    (copied from the source slice at parse time). The Token span's
    underlying `&str` is NOT retained in the AST. Rationale: the
    AST survives independently of the source buffer.
12. **No invented helpers** — per `spec/part-conventions.spec.md`
    §"Generation scope". The parser is a single `parse_expr`
    plus the recursive helpers it directly requires (`parse_bp`,
    `parse_prefix`, `infix_lookup`, `parse_call_args`). No regex,
    no parser-generator crates, no external dependencies beyond
    std.
13. **No pre-tokenization** — the parser consumes `tokens` as
    given; it does NOT call `tokenize()` itself. A harness / runner
    is responsible for lexing first.
14. **IS NULL postfix** — `a IS NULL` parses as
    `IsNull { arg: Col("a"), negated: false }`; `a IS NOT NULL`
    parses as `IsNull { arg: Col("a"), negated: true }`. The
    postfix is checked in `parse_bp` before the infix lookup; it
    consumes 2 or 3 tokens (`IS NULL` / `IS NOT NULL`). Any other
    token sequence after `IS` (e.g. `a IS b`) yields a ParseError
    with message `"deferred: IS operator"`.
15. **IS NULL in larger expressions** — `a IS NULL AND b` parses as
    `Binary(And, IsNull(a, false), b)`. `NOT a IS NULL` parses as
    `Unary(Not, IsNull(a, false))` because unary NOT binds tighter
    than IS NULL per §Precedence (unary at bp 19, IS NULL at bp 5).
16. **BETWEEN desugar** — `a BETWEEN 1 AND 10` parses to
    `Binary(And, Binary(Ge, a, 1), Binary(Le, a, 10))`. The `a`
    node is **cloned** (deep-copied) so both comparisons own an
    independent AST subtree. `a NOT BETWEEN 1 AND 10` wraps the
    result in `Unary(Not, ...)`. Clone helper: targets must provide
    an AST-clone operation for their Expr representation; the spec
    assumes it exists. If a target cannot clone, STOP and flag.
17. **IN desugar** — `a IN (1, 2, 3)` parses to
    `Binary(Or, Binary(Or, Binary(Eq, a, 1), Binary(Eq, a, 2)), Binary(Eq, a, 3))`.
    Left-fold; `a` cloned per comparison. `a IN ()` parses to
    `IntLit("0")`. `a NOT IN (1, 2, 3)` wraps result in `Unary(Not, ...)`.
    `a NOT IN ()` parses to `IntLit("1")`. Inner expressions parsed
    at bp=0 so any expression is allowed in the list.
18. **No new Expr variants for BETWEEN / IN** — the AST has only
    the variants in `shapes.json::Expr`. Adding BETWEEN/IN is a
    PARSER-ONLY change; downstream compilers see ordinary
    Binary/Unary/IntLit trees and need zero modification. This
    deliberately avoids the Expr-enum coupling surfaced in
    feedback memory 2026-04-24.
19. **Simple-form CASE desugar at parse time** — `CASE x WHEN v1
    THEN r1 WHEN v2 THEN r2 ELSE e END` parses to
    `Case { branches: [(Binary(Eq, clone(x), v1), r1), (Binary(Eq, clone(x), v2), r2)], else_: Some(e) }`.
    Downstream compilers only ever see searched-form Case. The
    Case variant itself IS a new AST node — there is no existing
    primitive in Expr that returns one-of-N values based on
    predicates, so the variant cannot be eliminated by further
    desugar. This is the deliberate boundary: BETWEEN/IN desugar
    fully; CASE desugars simple→searched but retains one variant.
20. **Searched CASE structure** — `Case { branches, else_ }` where
    `branches` is a non-empty list of `CaseBranch { when_expr,
    then_expr }`. An empty WHEN list is a ParseError. A missing
    ELSE means `else_ = None` (runtime returns NULL). `END` is
    mandatory.
21. **CASE participates in binary operators** — `CASE WHEN a THEN
    1 ELSE 0 END + 1` parses as `Binary(Plus, Case{...}, IntLit("1"))`
    because CASE is a prefix/atom construct. `NOT CASE ... END`
    parses as `Unary(Not, Case{...})`.
22. **CAST prefix** — `CAST('123' AS INTEGER)` parses to
    `Cast { expr: StrLit("'123'"), type_name: "INTEGER" }`. type_name
    is uppercased; whitespace inside the parens follows the same
    skip rules as elsewhere. Missing `AS`, missing type ident, or
    missing closing `)` is a ParseError.
23. **LIKE / GLOB postfix** — `'abc' LIKE 'a%'` parses to
    `Like { expr: StrLit("'abc'"), pattern: StrLit("'a%'"), escape: None,
    negated: false, kind: LikeKind::Like }`. `NOT LIKE` flips negated.
    `'abc' GLOB '*c'` produces `kind: LikeKind::Glob`. ESCAPE clause
    sets `escape = Some(...)`. ESCAPE with GLOB is a ParseError.
24. **COLLATE postfix** — `a COLLATE NOCASE` parses to
    `Collate { expr: Col("a"), name: "NOCASE" }`. COLLATE binds at
    the highest tier, so `a COLLATE NOCASE = b` parses to
    `Binary(Eq, Collate{Col(a), NOCASE}, Col(b))`.

## Regeneration envelope

- Line budget: **~300–500 lines** of Rust. The 18-case `BinaryOp`
  enum + 2-case `UnaryOp` + 9-case `Expr` are ~70 lines by
  themselves; the infix lookup table is ~25 lines; `parse_bp` +
  `parse_prefix` + `parse_call_args` are ~150 lines; error/boxing
  boilerplate fills the rest.
- No dependencies beyond std.
- Public items: `UnaryOp`, `BinaryOp`, `Expr`, `ParseError`,
  `ParseOk`, `parse_expr`.

## Smoke probe

`src-rust/examples/parse_smoke.rs` (hand-written, not regenerated)
tokenizes + parses six expressions and asserts the AST shape:

```text
1. 1 + 2 * 3                     → Binary(Plus, 1, Binary(Mul, 2, 3))
2. (1 + 2) * 3                   → Binary(Mul, Binary(Plus, 1, 2), 3)
3. a AND b OR c                  → Binary(Or, Binary(And, a, b), c)
4. NOT a = b                     → Binary(Eq, Unary(Not, a), b)  [probe convention]
5. f(1, g(2, 3))                 → Call(f, [1, Call(g, [2, 3])])
6. -a || 'x'                     → Binary(Concat, Unary(Neg, a), StrLit('x'))
7. CASE WHEN a=1 THEN 'yes' ELSE 'no' END
                                 → Case(branches=[(Eq(a,1), 'yes')], else_='no')
8. CASE x WHEN 1 THEN 'a' WHEN 2 THEN 'b' END
                                 → Case(branches=[(Eq(clone(x),1),'a'),(Eq(clone(x),2),'b')], else_=None)
                                   [simple-form desugar]
```

Runner prints `OK: all N expressions parse to expected shape` on
success and exits 1 on any mismatch. Asserts go through a small
hand-rolled `expr_matches(expr, pattern)` helper in the runner itself
(not in the emission).
