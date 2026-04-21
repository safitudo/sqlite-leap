# Phase 6p test harness — language-neutral spec

Same pipeline as phase 6o. Phase 6p adds `CompoundOp::Intersect` and `CompoundOp::Except` plus new tokens KEYWORD_INTERSECT / KEYWORD_EXCEPT. No new VDBE opcodes. No new invariants. `max_invariant = 26`.

## Invocation

```
<harness-binary> <path-to-phase6p.json>
```

Generated into `src-{lang}/bin/phase6p-test`.

## Output

```
SUMMARY phase=6p target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
