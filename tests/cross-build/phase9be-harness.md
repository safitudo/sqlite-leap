# Phase 9be test harness — language-neutral spec

Same pipeline as phase 9a. Phase 9be fuses backfill + equality planner. Five new VDBE opcodes: `IdxOpenRead`, `IdxSeek`, `IdxNext`, `IdxRowid`, `TableSeekRowid`. New invariants 29–33. `max_invariant = 33`.

## Invocation

```
<harness-binary> <path-to-phase9be.json>
```

Generated into `src-{lang}/bin/phase9be-test`.

## Output

```
SUMMARY phase=9be target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
