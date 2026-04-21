# Phase 6bo harness — post-6bn parser/compiler gaps from random corpus

After Phase 6bn closed 90%+ of random PARSE failures, the residual parser errors concentrated in two shapes, plus one compiler-level strictness that SQLite relaxes. Bucketing sample:

- `random/select/slt_good_7.test`: 203/203 remaining fails = `CROSS JOIN`.
- `random/aggregates/slt_good_7.test`: 107 CROSS JOIN + 161 `AGG(ALL expr)` = 100% of parse fails.
- `random/groupby/slt_good_7.test`: 1983 `COMPILE_COLUMN_NOT_IN_GROUP_BY` + 395 CROSS JOIN.

Three gaps, each a small targeted fix. No new opcodes. No new reserved keywords (CROSS and ALL are already tokens). `max_invariant` unchanged. Gate: 11 fixtures green both targets.

## Gap 1 — CROSS JOIN

SQLite permits `FROM t1 CROSS JOIN t2` as a syntactic variant of `FROM t1, t2` (cartesian product, no ON/USING clause). Our parser accepts `INNER JOIN`, `LEFT JOIN`, `FULL JOIN`, `RIGHT JOIN` but rejects `CROSS`.

Grammar:
```
join-op := COMMA
         | KEYWORD_CROSS KEYWORD_JOIN
         | KEYWORD_INNER? KEYWORD_JOIN ( KEYWORD_ON expr | KEYWORD_USING LPAREN column-list RPAREN )?
         | ( KEYWORD_LEFT | KEYWORD_RIGHT | KEYWORD_FULL ) KEYWORD_OUTER? KEYWORD_JOIN …
```

Semantics: `t1 CROSS JOIN t2` is identical to `t1, t2`. **No ON/USING clause is permitted** after `CROSS JOIN` (per SQL standard); the parser must not accept one. Composes normally with further JOIN/comma operators.

## Gap 2 — ALL quantifier inside aggregate function arguments

SQL allows `AGG_FUNC([ALL | DISTINCT] expr)`. `ALL` is the default and a no-op. We already accept `DISTINCT`; add `ALL` alongside it.

Grammar:
```
aggregate-call := IDENTIFIER LPAREN [ KEYWORD_ALL | KEYWORD_DISTINCT ] expression RPAREN
                | IDENTIFIER LPAREN STAR RPAREN                                  (* COUNT(*) *)
```

Semantics: `ALL` consumes the token and produces an AST identical to the one without any quantifier. Applies uniformly across SUM / AVG / MIN / MAX / COUNT / TOTAL / GROUP_CONCAT.

## Gap 3 — Bare column references with GROUP BY (relax strictness)

Per SQL-92, `SELECT bare_col FROM t GROUP BY other_col` is an error: `bare_col` is neither aggregated nor grouped. SQLite relaxes this: when a GROUP BY is present, any bare column reference is accepted and returns **some value from the group** (implementation-defined which row). Our compiler currently raises `COMPILE_COLUMN_NOT_IN_GROUP_BY` in this case.

Semantics change:
- With GROUP BY present: a bare column reference (not in the GROUP BY key set, not inside an aggregate) is accepted. The emitted value is the column's value from the **last row** written into that group's accumulator (the row whose cursor value wins a non-deterministic tie is acceptable — random corpus uses `rowsort` so it doesn't pin a row).
- Without GROUP BY: unchanged (bare column with an aggregate elsewhere still triggers `COMPILE_BARE_COLUMN_IN_AGGREGATE` as today).
- HAVING / ORDER BY may reference bare columns under the same relaxation.

Error changes:
- `COMPILE_COLUMN_NOT_IN_GROUP_BY` is **no longer raised** when a GROUP BY is present. Remove the check entirely for that case; generators may keep the error kind defined but unreached (or delete if unused post-regen).

### Implementation

- Parser — join grammar: add `CROSS JOIN` as a distinct join-op that accepts neither ON nor USING.
- Parser — aggregate-call: accept `KEYWORD_ALL` alongside the existing `KEYWORD_DISTINCT` branch; discard the token (AST identical to no-quantifier form).
- Compiler — group-by validation: when `group_by.is_some()`, do not emit `COMPILE_COLUMN_NOT_IN_GROUP_BY` for bare column refs. Instead, compile them as direct column loads from the current accumulator row (same code path as a column in the GROUP BY key).
- Runtime — no change. The existing "emit current row's column value at end of group" behavior is what we want; the compiler just stops gatekeeping.

### Non-goals

- Tracking functional-dependency inference (SQLite implements it partially; we'll keep the relaxation total for v1).
- NATURAL CROSS JOIN — v1 keeps CROSS as its own branch with no ON/USING; if a test needs NATURAL CROSS JOIN we'll revisit.
- `CROSS JOIN ON …` — per standard, disallow; parser must reject (no new error kind needed; falls through to existing PARSE_UNEXPECTED_TOKEN).
