# Phase 6o test harness — language-neutral spec

Same pipeline as phase 6n. Phase 6o extends `CompoundOp` with `Union` (no-ALL variant). No new opcodes. No new invariants. `max_invariant = 26` (unchanged from 6n).

## Invocation

```
<harness-binary> <path-to-phase6o.json>
```

Generated into `src-{lang}/bin/phase6o-test`.

## Output

```
SUMMARY phase=6o target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
