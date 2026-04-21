# Phase 6as harness — UNION ALL / UNION / EXCEPT / INTERSECT with heterogeneous column types

Relaxation of the existing compound-SELECT phases (6m, 6o, 6p) to permit the per-column result types to differ across branches. SQLite permits this without coercion: a column that is INTEGER in branch 1 and TEXT in branch 2 simply yields rows of mixed type. Dedup (UNION / EXCEPT / INTERSECT) uses **affinity equality** — the same rules as the `=` operator and Phase 6g numeric coercion. Concretely: `1 == 1.0` (both numeric, equal magnitude → dedup), `1 != '1'` (TEXT vs numeric → distinct), `NULL` compared to `NULL` → treated as equal for dedup purposes (IS NOT DISTINCT FROM). This is NOT the stricter 6bc IN-list rule; UNION mirrors SQLite's comparison-operator semantics, which use affinity.

No new VDBE opcodes, no grammar change, no keyword change. This is a **compile/runtime relaxation** — removing or relaxing an arity/type check that was previously overly-strict.

Gate: 7 fixtures green both targets. `SUMMARY phase=6as target=<c|rust> passed=7 failed=0 total=7`.

Notes:

- If the compiler was previously rejecting mixed-type compound branches (unlikely in our current codebase — 6m never pinned type equality), this phase formalizes acceptance. If it was already accepting: this phase is a test-only ratification.
- The 6bc IN-list strict-equality rule does NOT carry to UNION/EXCEPT/INTERSECT dedup. The compound-SELECT dedup path uses SortValueEq with **affinity coercion**: integers and reals of equal magnitude are duplicates; numeric vs text are distinct. This matches SQLite's `=` operator semantics. First-seen value is retained when dedup collapses (e.g., `SELECT 1 UNION SELECT 1.0` returns `[[1]]` because the integer arrives first).
- Branch-arity MUST still match (same number of columns per branch); only types may differ. Arity mismatch → existing `COMPILE_COMPOUND_ARITY_MISMATCH` from 6m.
- Output-row typestring: use `?` or generic for columns that are heterogeneous across branches (runner-level only — the runner must not hard-assert column type from branch 1). If the runner has a pinned typestring-per-compound check, relax it.
- NULL behavior unchanged: NULL in any branch's result stays NULL in the output.

### Implementation hints

- Search the compile path for `UNION` / `EXCEPT` / `INTERSECT` handling. If any code path asserts `branch[i].columns[j].type == branch[0].columns[j].type`, either (a) remove that check, or (b) relax to `union-type := GENERIC` for divergent columns.
- Runtime: ResultRow emission already handles heterogeneous-value rows (different rows, same query, different types — fine). The dedup comparison uses the existing affinity-aware SortValueEq path — **do NOT introduce a strict type-aware equality** (e.g., a new SCALAR2_STRICT_EQ sub-kind is NOT needed and would break 6o's cross-type dedup fixture). Keep using the existing numeric-coercing equality infrastructure.
