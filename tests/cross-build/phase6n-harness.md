# Phase 6n test harness — language-neutral spec

Same pipeline as phase 6m. Phase 6n adds one new opcode `SubqueryEmit`, one new invariant (26). `max_invariant = 26`.

## Invocation

```
<harness-binary> <path-to-phase6n.json>
```

Generated into `src-{lang}/bin/phase6n-test`.

## Output

```
SUMMARY phase=6n target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
