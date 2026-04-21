# Phase 6u test harness — language-neutral spec

Phase 6u adds `IS NULL` / `IS NOT NULL` postfix operators. No new tokens (reuses existing `KEYWORD_IS`, `KEYWORD_NOT`, `KEYWORD_NULL`); no new VDBE opcodes; `max_invariant=42` unchanged.

## Invocation

```
<harness-binary> <path-to-phase6u.json>
```

Generated into `src-{lang}/bin/phase6u-test`.

## Output

```
SUMMARY phase=6u target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.

## Gate

All 15 cases green on both C and Rust. Every prior phase (1..9g plus 4a) regression-green.

## Notes for implementers

- `KEYWORD_IS` may be new. Check before adding; if new, add as reserved keyword at tokenizer level + update parser reserved-word lookup.
- Parser: extend `comparison` to accept the optional `null-test` production per spec. Postfix on `additive`.
- Compiler: one of the two implementation choices per spec § "Phase 6u compile" is acceptable. Generator chooses whatever is idiomatic.
- The sanity fixture `null-equality-still-yields-null-not-boolean` confirms 3VL equality is unchanged: `a = NULL` remains `Null` (filtered by WHERE), while `a IS NULL` yields `1` (retained by WHERE).
