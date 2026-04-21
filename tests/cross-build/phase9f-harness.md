# Phase 9f test harness — language-neutral spec

Same pipeline as phase 9d. Phase 9f adds PRIMARY KEY auto-index + DROP INDEX. One new VDBE opcode: `DropIndex`. New invariant 42. `max_invariant = 42`.

## Invocation

```
<harness-binary> <path-to-phase9f.json>
```

Generated into `src-{lang}/bin/phase9f-test`.

## Output

```
SUMMARY phase=9f target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
