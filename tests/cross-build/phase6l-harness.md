# Phase 6l test harness — language-neutral spec

Same pipeline as phase 6k. Phase 6l extends `ScalarKind` with `Trim`, `Ltrim`, `Rtrim`. No new opcodes, no new invariants. `max_invariant = 25` (unchanged).

## Invocation

```
<harness-binary> <path-to-phase6l.json>
```

Generated into `src-{lang}/bin/phase6l-test`.

## Output

```
SUMMARY phase=6l target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
