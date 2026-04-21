# Phase 6q test harness — language-neutral spec

Same pipeline as phase 6p. Phase 6q adds `Concat { left_reg, right_reg, dest }` opcode and `BinOp::"||"`, plus new token `CONCAT`. New invariant `27`. `max_invariant = 27`.

## Invocation

```
<harness-binary> <path-to-phase6q.json>
```

Generated into `src-{lang}/bin/phase6q-test`.

## Output

```
SUMMARY phase=6q target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
