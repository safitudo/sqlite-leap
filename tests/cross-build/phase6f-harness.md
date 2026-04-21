# Phase 6f test harness — language-neutral spec

Same as `phase6e-harness.md`. Phase 6f adds no new opcodes. Invariants 1–23 unchanged; `max_invariant = 23` on the harness binary.

## Invocation

```
<harness-binary> <path-to-phase6f.json>
```

Generated into `src-{lang}/bin/phase6f-test`.

## Output

```
SUMMARY phase=6f target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.

## Equality rules

Row order matters when ORDER BY is explicit. Without ORDER BY, DISTINCT output is in sorted-ASC order per projection (a necessary consequence of the sorter-based dedup). Tests pin row order accordingly.
