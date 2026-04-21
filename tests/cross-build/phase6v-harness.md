# Phase 6v test harness — language-neutral spec

Phase 6v adds `IN (expr-list)` and `NOT IN (expr-list)` predicates. No new VDBE opcodes; `max_invariant=42` unchanged. `KEYWORD_IN` added to reserved keyword table if not already present.

## Invocation

```
<harness-binary> <path-to-phase6v.json>
```

Generated into `src-{lang}/bin/phase6v-test`.

## Output

```
SUMMARY phase=6v target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.

## Gate

All 16 cases green on both C and Rust. Every prior phase (1..9g, 4a, 6u) regression-green. Byte-identical cross-build on result rows.

## Implementation notes (either generator may choose)

- **(a) Parse-time desugar to OR-chain:** `x IN (a, b, c)` → `(x = a) OR (x = b) OR (x = c)`. NOT IN wraps in NOT. Leverages existing 3VL machinery. Simplest.
- **(b) Dedicated AST node + compile-time loop expansion.** Cleaner but more code.

Either is spec-permitted. The `in-list-empty-parens-rejected` fixture pins the empty-list case to `PARSE_UNEXPECTED_TOKEN { kind: RPAREN }`; implementations MUST reject at parse time, NOT at compile or run time.

The `NULL IN (...)` and `x IN (..., NULL, ...)` 3VL cases rely on the `=` operator already yielding `Null` on Null operands AND `OR` preserving Null per existing 3VL. Both desugar-to-OR and dedicated-loop implementations should get these right as long as they use existing machinery.
