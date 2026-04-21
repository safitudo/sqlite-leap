# Phase 9g test harness — language-neutral spec

Same pipeline as phase 9f. Phase 9g adds UNIQUE enforcement (no new opcodes; semantic extension of `IdxInsert` and `CreateIndex` on UNIQUE-flagged indexes). `max_invariant = 42` unchanged.

## Invocation

```
<harness-binary> <path-to-phase9g.json>
```

Generated into `src-{lang}/bin/phase9g-test`.

## Output

```
SUMMARY phase=9g target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
