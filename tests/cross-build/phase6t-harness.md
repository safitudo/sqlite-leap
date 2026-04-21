# Phase 6t test harness — language-neutral spec

Same pipeline as phase 6s. Phase 6t adds four reserved keywords (BEGIN, COMMIT, ROLLBACK, END), three new top-level AST kinds (BeginStatement, CommitStatement, RollbackStatement — END parses to CommitStatement), and one new VDBE opcode `TxnRollback` (always raises `VDBE_ROLLBACK_NOT_SUPPORTED`). BEGIN / COMMIT / END compile to empty-body programs (`[Init, Halt]`), semantic no-ops. No new invariants. `max_invariant = 28` (unchanged).

## Invocation

```
<harness-binary> <path-to-phase6t.json>
```

Generated into `src-{lang}/bin/phase6t-test`.

## Output

```
SUMMARY phase=6t target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
