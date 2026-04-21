# Phase 6aa test harness — language-neutral spec

Phase 6aa adds non-recursive CTEs via `WITH name AS (select) outer-stmt`. No new VDBE opcodes expected. `max_invariant=43` unchanged. Algorithm per `spec/sql-grammar.spec.md` § "Phase 6aa".

## Invocation

```
<harness-binary> <path-to-phase6aa.json>
```

Generated into `src-{lang}/bin/phase6aa-test`.

## Output

```
SUMMARY phase=6aa target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`.

## Gate

15 cases green on both C and Rust. All prior phases (1..9g, 4a, 6u..6y) regression-green. Byte-identical cross-build on result rows.

## Implementation notes

- **Tokenizer**: add `KEYWORD_WITH`. `AS` already reserved.
- **Parser**: `WITH` at statement start, followed by one-or-more `name AS (select)` bindings separated by commas, then exactly one outer statement (SELECT / INSERT / UPDATE / DELETE). Empty binding list → parse error. Missing outer statement → parse error.
- **Recommended lowering** (reuses maximum existing machinery): at resolve-time during outer-statement compile, any `FROM name` or `JOIN name` matching a CTE binding is rewritten in-place to `FROM (<binding's select>) AS name`. This turns CTEs into subqueries-in-FROM, which all v1 engines already handle.
- **Name resolution**: CTE names shadow real tables. If outer statement has `FROM foo` and there's a CTE named `foo`, the CTE wins.
- **Duplicate detection**: within a single WITH-prefix, duplicate binding identifiers must raise `PARSE_DUPLICATE_CTE_NAME { name: "<dup>" }` at parse time.
- **No forward-visibility**: v1 CTE bindings cannot reference each other. Each binding's select is compiled in the scope of real tables + schema only; sibling CTEs are NOT visible.
- **Re-evaluation semantics**: if the outer statement references a CTE twice, option-(a) substitution re-evaluates the select each time. Correctness-preserving; perf gap acceptable for v1.

## Cross-build risks

- If a generator opts for option (b) — materialize-once into ephemeral table — opcode streams will differ from option (a) generators. Row output must still match on all fixtures. Not a spec leak.
- Parser's statement-start dispatch must accept `KEYWORD_WITH` as a new statement-start token (same treatment as `CREATE`, `SELECT`, `INSERT`, etc.).
