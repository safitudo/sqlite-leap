# Phase 6m test harness — language-neutral spec

Same pipeline as phase 6l. Phase 6m introduces compound SELECT with UNION ALL. Two new reserved keywords (UNION, ALL). No new VDBE opcodes (reuses ResultRow + sorter). No new invariants. `max_invariant = 25` (unchanged).

## Invocation

```
<harness-binary> <path-to-phase6m.json>
```

Generated into `src-{lang}/bin/phase6m-test`.

## Output

```
SUMMARY phase=6m target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
