# Phase 9d test harness — language-neutral spec

Same pipeline as phase 9c. Phase 9d adds range predicates + ORDER BY via index + index splits. Four new VDBE opcodes: `IdxRewind`, `IdxSeekGE`, `IdxSeekGT`, `IdxAdvance`. New invariants 38–41. `max_invariant = 41`.

## Invocation

```
<harness-binary> <path-to-phase9d.json>
```

Generated into `src-{lang}/bin/phase9d-test`.

## Output

```
SUMMARY phase=9d target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
