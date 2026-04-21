# Phase 6c test harness — language-neutral spec

Identical to `phase6b-harness.md`. Phase 6c adds 2 new VDBE opcodes (`AggStep`, `AggFinal`), a new AST alternative (`AggregateCall`), new compile-time error names, and no new runtime error names.

## Invocation

```
<harness-binary> <path-to-phase6c.json>
```

Generated into `src-{lang}/bin/phase6c-test` (or the target's equivalent).

## Pipeline per step

Unchanged: tokenize → parse → compile → vdbe.run against an in-memory storage handle.

## Well-formedness invariants

Invariants 1–22 per the phases so far. The harness enforces them at step run-time.

## Equality rules

Match phase 6b. Aggregate results return in a single row; comparison is positional.

## Output

```
SUMMARY phase=6c target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
