# Phase 6j test harness — language-neutral spec

Same pipeline as phase 6i. Phase 6j adds no new opcodes (extends `ScalarKind` enum with `Length` and `Abs`), no new invariants. `max_invariant = 25` (unchanged from 6i).

## Invocation

```
<harness-binary> <path-to-phase6j.json>
```

Generated into `src-{lang}/bin/phase6j-test`.

## Output

```
SUMMARY phase=6j target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
