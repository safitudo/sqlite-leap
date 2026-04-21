# Phase 6h test harness — language-neutral spec

Same pipeline as phase 6g. Phase 6h adds no new tokens, no new opcodes — only extends `AggregateKind` with `Avg` and adds invariant 24 (paired-register reservation). `max_invariant = 24`.

## Invocation

```
<harness-binary> <path-to-phase6h.json>
```

Generated into `src-{lang}/bin/phase6h-test`.

## Output

```
SUMMARY phase=6h target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
