# Phase 6i test harness — language-neutral spec

Same pipeline as phase 6h. Phase 6i adds two new reserved keywords (CAST, AS), one new VDBE opcode (Scalar), three new ScalarKind variants (CastInteger, CastReal, CastText), and invariant 25 (Scalar arg/dest in-range). `max_invariant = 25`.

## Invocation

```
<harness-binary> <path-to-phase6i.json>
```

Generated into `src-{lang}/bin/phase6i-test`.

## Output

```
SUMMARY phase=6i target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
