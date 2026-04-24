---
name: parser/expressions
kind: leaf
inherits:
  - /schema/tokens.schema.json
  - /schema/ast.schema.json
emits:
  c: { path: src-c/parser/expressions.c, headers: [src-c/parser/expressions.h] }
  rust: { path: src-rust/src/parser/expressions.rs }
---

# Part: parser/expressions

The expression grammar. Precedence climbing over the token stream;
produces `Expression` AST nodes. Shared by every statement parser.

## Public interface

```
fn parse_expression(tokens) -> Result<Expression<'src>, ParseError>
fn parse_expression_list(tokens) -> Result<Vec<Expression<'src>>, ParseError>
```

## Precedence table (lowest to highest binding)

1. `OR`
2. `AND`
3. `NOT` (unary)
4. `=` `!=` `<>` `IS` `IS NOT` `IN` `NOT IN` `LIKE` `NOT LIKE`
   `GLOB` `NOT GLOB` `BETWEEN` `NOT BETWEEN`
5. `<` `<=` `>` `>=`
6. `&` `|` `<<` `>>`
7. `+` `-` (binary)
8. `*` `/` `%`
9. `||` (concat)
10. unary `+` `-` `~` `NOT`
11. `COLLATE`
12. function calls, `CAST`, `CASE`, parenthesized expressions,
    subqueries, literals, identifiers.

## Desugaring applied at parse time

- `NOT BETWEEN` (Phase 6az) — parsed as `NotBetween(e, lo, hi)`
  AST; compiler desugars to `NOT (e BETWEEN lo AND hi)`.
- `NOT IN` — parsed as `NotIn(...)` AST; compiler negates `In`.
- `IS DISTINCT FROM` / `IS NOT DISTINCT FROM` (if accepted in v2)
  — emitted as `IsDistinctFrom` nodes.

## Phase pins

- **Phase 6y** — CASE expression.
- **Phase 6u** — IS NULL / IS NOT NULL.
- **Phase 6v** — IN (expr-list).
- **Phase 6x** — LIKE with % and _.
- **Phase 6ad** — GLOB.
- **Phase 6af** — VARCHAR(N) and friends — accept parenthesized
  type params in CAST.
- **Phase 6az** — NOT BETWEEN desugar.
- **Phase 6bc** — empty `IN ()`.

## Regeneration envelope

- Target leaf size: 600–1000 lines per target.
- Spec < 150 lines.
