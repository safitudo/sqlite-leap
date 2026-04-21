# Phase 6bl harness — WITH RECURSIVE (recursive CTE)

Extends Phase 6aa (non-recursive CTEs) to permit the `RECURSIVE` keyword after `WITH`. A recursive CTE is a `UNION ALL` (or `UNION`) of an anchor-select and a recursive-select that references the CTE by name. Evaluation is iterative fixed-point: anchor produces the initial batch; recursive-select reads from the CTE's accumulated rows and appends the new batch until a batch is empty.

One new reserved keyword `KEYWORD_RECURSIVE`. No new VDBE opcodes — sorter + ResultRow + existing SELECT compile path. Gate: 8 fixtures green both targets.

### Grammar extension

```
with-clause := KEYWORD_WITH [ KEYWORD_RECURSIVE ] cte-decl ( COMMA cte-decl )*
cte-decl    := IDENTIFIER [ LPAREN column-name ( COMMA column-name )* RPAREN ] KEYWORD_AS LPAREN select-stmt RPAREN
```

The optional column-list after the CTE name (new in 6bl) lets the recursive-select's projection expose explicit column names; when absent, names flow from the anchor-select.

A CTE is **recursive** iff the select-stmt inside its parentheses is a compound SELECT whose body references the CTE's own name inside any branch. Simple (non-self-referential) CTEs remain non-recursive regardless of whether `RECURSIVE` was typed. `RECURSIVE` is an optimization hint at parse time, not a semantic gate — parser accepts it, compiler decides recursive vs non-recursive by scanning for self-references.

### Semantics

Execution model for a recursive CTE `WITH RECURSIVE r AS (anchor UNION ALL rec)` referenced by an outer query:

1. Materialize the anchor-select into an accumulator table `ACC` and a working-set `WS`.
2. Loop: run the recursive-select with `r` bound to `WS` (NOT `ACC`); append results to `ACC`; replace `WS` with the new results; if `WS` is empty, exit.
3. The outer query reads `r` as `ACC`.

Semantics notes:

- **UNION ALL vs UNION**: `UNION ALL` keeps all iterated rows; `UNION` applies affinity-equality dedup across ACC at each step (rows already in ACC are not re-appended to WS).
- **Recursion depth cap**: v1 caps at 1000 iterations. Exceeding → `RUNTIME_RECURSIVE_CTE_LIMIT { cte }`.
- **Non-self-referential CTEs** in a `WITH RECURSIVE` block are evaluated normally (one-shot materialization), so `RECURSIVE` is cheap to leave on for mixed CTE lists.
- **Column-name binding**: if the CTE declaration includes a `(col, col, …)` list, that list pins the column names. Otherwise names come from the anchor-select's projection. Column count must match across anchor and recursive branches.

### Errors

- `RUNTIME_RECURSIVE_CTE_LIMIT { cte }` — exceeded iteration cap (1000 in v1).
- `COMPILE_RECURSIVE_CTE_ARITY_MISMATCH { cte, anchor_cols, rec_cols }` — anchor and recursive branches have different column counts.
- `COMPILE_RECURSIVE_CTE_MISSING_ANCHOR { cte }` — a self-referential CTE body has no non-self-referential branch (infinite loop without base case).

### Implementation hints

- Parser: accept the optional `KEYWORD_RECURSIVE` after `KEYWORD_WITH`. Parse the column-list after CTE-name. Body is `select-stmt` (unchanged).
- Compile: after parsing, walk the CTE body looking for table-refs matching the CTE's own name. If found, the CTE is recursive; split the body at its outermost compound-SELECT UNION into (anchor, recursive) branches. If no `UNION ALL` or `UNION` delimiter is found on a self-referential CTE → `COMPILE_RECURSIVE_CTE_MISSING_ANCHOR`.
- Runtime: use two sorters — one for ACC (accumulated) and one for WS (current working-set). After each iteration, swap: the new WS becomes what the recursive-select produced this round; merge new rows into ACC (dedup-aware if UNION). Guard with iteration counter.
- CTE self-reference resolution: when the recursive-select's compile encounters a `FROM r`, emit a `SorterRewind`/`SorterRead`/`SorterNext` over WS, not ACC. This is the key asymmetry.

### Non-goals (v1)

- Mutually recursive CTEs (`WITH RECURSIVE a AS (… b …), b AS (… a …)`) — defer.
- Recursive CTE inside a subquery (`SELECT * FROM (WITH RECURSIVE …)`) — defer; fixtures keep recursion at top level.
- `EXCEPT` or `INTERSECT` as the compound operator in a recursive CTE — v1 supports only UNION / UNION ALL.
- Fast-path materialization (CTE body depends only on constants) — defer.
