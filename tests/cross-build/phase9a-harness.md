# Phase 9a test harness — language-neutral spec

Same pipeline as phase 6t. Phase 9a adds CREATE INDEX statement + empty-index storage scaffold. New opcode `CreateIndex`. No new invariants (max_invariant=28 unchanged). New page type 0x0a (empty index-leaf) becomes writeable + readable. `sqlite_schema.type` widens from `{'table'}` to `{'table', 'index'}`.

## Invocation

```
<harness-binary> <path-to-phase9a.json>
```

Generated into `src-{lang}/bin/phase9a-test`.

## Output

```
SUMMARY phase=9a target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
