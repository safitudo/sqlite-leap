# Phase 6d test harness — language-neutral spec

Identical to `phase6c-harness.md`. Phase 6d adds 1 new VDBE opcode (`SorterReadKey`), new AST fields (`group_by`, `having` on Select), new compile-time errors, and no new runtime error names.

## Invocation

```
<harness-binary> <path-to-phase6d.json>
```

Generated into `src-{lang}/bin/phase6d-test` (or the target's equivalent).

## Pipeline per step

Unchanged: tokenize → parse → compile → vdbe.run.

## Well-formedness invariants

Invariants 1–23. Harness enforces them at step run-time.

## Equality rules

Match phase 6b/6c. For grouped SELECT with ORDER BY, row order matters. Without ORDER BY, row order is "group-sort order" (an implementation detail — tests either include an ORDER BY to pin order, or use single-group queries where row order is trivially one row).

## Output

```
SUMMARY phase=6d target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
