# Phase 6s test harness — language-neutral spec

Same pipeline as phase 6q. Phase 6s adds `Scalar2 { kind, arg1_reg, arg2_reg, dest }` opcode and `Scalar2Kind::Ifnull`, plus widens `function-call` grammar to variadic and adds COALESCE (desugared to nested IFNULL). New invariant `28`. `max_invariant = 28`.

## Invocation

```
<harness-binary> <path-to-phase6s.json>
```

Generated into `src-{lang}/bin/phase6s-test`.

## Output

```
SUMMARY phase=6s target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
