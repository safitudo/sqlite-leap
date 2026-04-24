---
name: parser/clauses
kind: leaf
inherits:
  - /schema/ast.schema.json
  - /parts/parser/parts/expressions/master.md
emits:
  c: { path: src-c/parser/clauses.c, headers: [src-c/parser/clauses.h] }
  rust: { path: src-rust/src/parser/clauses.rs }
---

# Part: parser/clauses

Shared sub-statement clauses: WHERE, GROUP BY, HAVING, ORDER BY,
LIMIT/OFFSET, FROM source list, JOIN tails, USING/NATURAL join
variants.

## Public interface

```
fn parse_where_clause(tokens) -> Result<Option<Expression<'src>>>
fn parse_group_by_clause(tokens) -> Result<Option<GroupBy<'src>>>
fn parse_having_clause(tokens) -> Result<Option<Expression<'src>>>
fn parse_order_by_clause(tokens) -> Result<Option<Vec<OrderByTerm<'src>>>>
fn parse_limit_offset(tokens) -> Result<(Option<Expression>, Option<Expression>)>
fn parse_from_list(tokens) -> Result<Vec<FromSource<'src>>>
fn parse_join_tail(tokens, left) -> Result<FromSource<'src>>
```

## Clause legality

Each clause is optional; presence is signaled by the matching
keyword (`WHERE`, `GROUP BY`, `HAVING`, `ORDER BY`, `LIMIT`). The
statement parsers pick which clauses they accept.

## ORDER BY terms

Each term is `<expression> [ASC | DESC] [NULLS FIRST | NULLS LAST]`.
Positional terms (`ORDER BY 1`) are accepted; the compiler
interprets small-integer literals as 1-based column positions in
the projection (Phase 6ba).

## FROM source forms

- `table [AS alias]`
- `(subquery) [AS alias]` — derived table (Phase 6br).
- `(from_source JOIN from_source ON ...)` — parenthesized
  (Phase 6bq).
- `from_source JOIN from_source ON / USING / NATURAL`.

## Phase pins

- **Phase 6ba** — positional ORDER BY.
- **Phase 6bq** — parenthesized FROM expressions.
- **Phase 6br** — subquery-in-FROM (derived tables).

## Regeneration envelope

- Target leaf size: 300–500 lines per target.
- Spec < 120 lines.
