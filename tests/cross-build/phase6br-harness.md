# Phase 6br harness — subquery-in-FROM (derived tables)

SQLite allows a parenthesized SELECT as a FROM source: `SELECT * FROM (SELECT a, b FROM t WHERE a > 0) AS sub`. The inner SELECT materializes to a virtual table that the outer query reads from.

Corpus evidence: sqllogictest's hand-written suites (select1–5, index/, evidence/) rely on this. Several random/ subtrees use it too. No more reliable path to 99%+ on the full upstream corpus without it.

Pending task #61 tracks this. Harness closes it.

No new reserved keywords. Gate: 10 fixtures green both targets.

## Grammar extension

Extend from-source to accept a parenthesized SELECT as a derived table:

```
from-source := table-reference
             | LPAREN join-tree RPAREN
             | LPAREN select-stmt RPAREN [ KEYWORD_AS ] IDENTIFIER
```

Disambiguation at parse time: after LPAREN, if the next token is SELECT / WITH / VALUES, take the derived-table branch. Otherwise take the join-group branch (Phase 6bq). Derived-table form **requires** a trailing alias; join-group form forbids one (enforced by parser).

```
table-reference := IDENTIFIER [ [ KEYWORD_AS ] IDENTIFIER ]
select-stmt     := (existing)                            -- may itself include a WITH, UNION, ORDER BY, LIMIT
```

## Semantics

The inner select-stmt is executed as a self-contained query and its result-set is materialized into a temporary sorter or equivalent. The outer query reads from that sorter as if it were a regular cursor. Column names from the inner SELECT (either explicit aliases or its projection item names) become the columns of the derived table; the outer alias provides a qualifier (`sub.colname`).

Column resolution:
- Inside the derived table: uses the inner SELECT's own scope.
- Outside the derived table: the outer query sees only the derived table's alias-qualified columns. It cannot reach into the inner FROM/WHERE/GROUP-BY scope.
- Column names are taken from the inner SELECT's projection items in order. If a projection item has no explicit alias and is not a plain column reference, its name is the SQL text of the expression (SQLite-compat; we can simplify to `column_<index>` if text-preservation isn't easy).

Correlated derived tables (inner SELECT references outer columns) are **deferred** to a follow-up phase — v1 treats the inner body as self-contained.

## Errors

- `COMPILE_DERIVED_TABLE_ARITY_MISMATCH { declared_cols, projected_cols }` — only if the future column-list-on-alias syntax (`AS sub(c1, c2)`) is implemented; not in v1.
- `COMPILE_DERIVED_TABLE_MISSING_ALIAS` — if parser accepts a derived-table form without a trailing alias, compiler raises this. Preferably enforced at parse time so this error stays unreached.

No new opcodes — materialization reuses the existing sorter-based CTE machinery (see Phase 6aa lowering).

## Implementation

- **Parser**: in `parse_from_source`, when LPAREN is followed by SELECT/WITH/VALUES, recursively parse the select-stmt, consume RPAREN, then require and parse the trailing alias. Emit a new AST node (`FromSource::Derived { select, alias }` or language-equivalent) or reuse the existing CTE-binding AST by synthesizing a unique CTE name per derived table.
- **Compiler**: lower a derived table as if the body were an anonymous CTE — materialize into a sorter before the outer query opens its main scan, then treat it as a regular table reference keyed by the alias.
- **Runtime**: no change. The sorter-read path is the same as 6aa CTEs.

## Non-goals (v1)

- Correlated derived tables (`FROM (SELECT * FROM t WHERE t.k = outer.k)`) — defer.
- Column-list-on-alias (`AS sub(c1, c2)`) — defer.
- Derived tables inside `WITH RECURSIVE` — defer.
- `VALUES (…)` as a derived table — defer (separate 6bs).

## Fixtures

`tests/cross-build/phase6br.json` — 10 cases:
1. Simple passthrough: `SELECT * FROM (SELECT 1) AS x`
2. Projection inside, alias outside
3. WHERE inside derived table
4. ORDER BY + LIMIT inside
5. Aggregate inside derived table, simple outer projection
6. Column reference from derived table in outer WHERE
7. Two derived tables joined
8. Derived table joined with a regular table
9. Column resolution — outer query uses alias.col
10. Missing alias raises PARSE_UNEXPECTED_TOKEN
