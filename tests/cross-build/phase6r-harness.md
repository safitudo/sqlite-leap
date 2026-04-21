# Phase 6r test harness — language-neutral spec

Phase 6r adds Real→Text coercion via fixed 17-digit scientific notation. No new VDBE opcodes. Lifts the `VDBE_UNSUPPORTED_CAST { from_kind: "Real", to_kind: "Text" }` restriction from Phase 6i for Real→Text. `max_invariant = 42` unchanged.

## Invocation

```
<harness-binary> <path-to-phase6r.json>
```

Generated into `src-{lang}/bin/phase6r-test`.

## Output

```
SUMMARY phase=6r target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
