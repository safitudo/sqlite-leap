# Phase 6k test harness — language-neutral spec

Same pipeline as phase 6j. Phase 6k extends `ScalarKind` with `Upper` and `Lower`. No new opcodes, no new invariants. `max_invariant = 25` (unchanged).

## Invocation

```
<harness-binary> <path-to-phase6k.json>
```

Generated into `src-{lang}/bin/phase6k-test`.

## Output

```
SUMMARY phase=6k target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
