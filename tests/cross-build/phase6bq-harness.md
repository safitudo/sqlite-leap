# Phase 6bq harness — parenthesized FROM expressions

SQLite allows parenthesizing any join expression in the FROM clause: `SELECT * FROM (t1 CROSS JOIN t2)`. This is syntactic — the parenthesized group is treated identically to an unparenthesized join of the same shape.

Corpus evidence: 4596 queries across 130 files in `random/aggregates/` use this shape. Typical patterns:
- `FROM (tab0 AS cor0 JOIN tab0 AS cor1 ON …)`
- `FROM (tab2 AS cor0 CROSS JOIN tab2 AS cor1)`
- `FROM (tab0 cor0 CROSS JOIN tab1 cor1)`

No new opcodes. No new reserved keywords. `max_invariant` unchanged. Gate: 8 fixtures green both targets.

## Grammar

Extend the `from-source` grammar to accept parentheses around any join tree:

```
from-clause := KEYWORD_FROM from-source ( COMMA from-source )*
from-source := table-reference
             | LPAREN join-tree RPAREN [ [ KEYWORD_AS ] IDENTIFIER ]?
join-tree   := table-reference ( join-op table-reference )*
             | LPAREN join-tree RPAREN [ [ KEYWORD_AS ] IDENTIFIER ]?
```

The parenthesized group behaves identically to its unparenthesized form. No new AST node is required — the parser can "unwrap" the parens immediately, treating them as grouping tokens with no semantic effect.

Subquery-in-FROM (`(SELECT … FROM t)` as a derived table) is NOT in scope for 6bq — if after LPAREN the next token is SELECT/WITH/VALUES, parser should either defer to a future phase's derived-table path or fall through to existing PARSE_UNEXPECTED_TOKEN. V1 of 6bq keeps it simple: inside LPAREN we require a table-reference-or-join-tree, not a SELECT.

## Semantics

Identical to the unparenthesized form. Scoping, aliasing, and join-order preservation are unchanged. If the parenthesized group has an alias after RPAREN, that alias must not apply to the whole group (we don't support derived-table-aliases in 6bq); parser should reject a trailing alias-identifier after the RPAREN until derived-table support lands.

Actually, looking at corpus shapes: all seen uses have no trailing alias after RPAREN. Tables inside are individually aliased. Drop the optional trailing alias from 6bq — keep the grammar tight:

```
from-source := table-reference
             | LPAREN join-tree RPAREN
```

## Implementation

- Parser: at the start of `parse_from_source`, if the next token is LPAREN, consume it, parse a nested join-tree, consume the matching RPAREN, and return the resulting node as-is (no wrapper).
- Compiler: no change — the AST is the same as an unparenthesized join tree.
- Runtime: no change.

## Non-goals

- Derived tables (`FROM (SELECT …) AS alias`) — deferred to Phase 6br or 6bs.
- Trailing alias on a parenthesized join group — deferred.
- Parens inside the parser's existing single-table position — we only add at the start of a from-source.
