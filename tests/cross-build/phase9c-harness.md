# Phase 9c test harness — language-neutral spec

Same pipeline as phase 9be. Phase 9c wires DML to keep indexes live. Three new VDBE opcodes: `IdxOpenWrite`, `IdxInsert`, `IdxDelete`. New invariants 34–36. `max_invariant = 36`.

## Invocation

```
<harness-binary> <path-to-phase9c.json>
```

Generated into `src-{lang}/bin/phase9c-test`.

## Output

```
SUMMARY phase=9c target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
