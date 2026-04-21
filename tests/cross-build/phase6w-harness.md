# Phase 6w test harness — language-neutral spec

Phase 6w widens INSERT's VALUES clause to accept multiple `(…)` tuples separated by commas. No new tokens; no new VDBE opcodes; `max_invariant=42` unchanged.

## Invocation

```
<harness-binary> <path-to-phase6w.json>
```

Generated into `src-{lang}/bin/phase6w-test`.

## Output

```
SUMMARY phase=6w target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`.

## Gate

12 cases green on both. All prior phases (1..9g, 4a, 6u, 6v) regression-green. Byte-identical cross-build on result rows.

## Implementation notes

- Parser: extend the VALUES production to loop `(tuple (COMMA tuple)*)`.
- Compiler: repeat the single-tuple codegen per tuple. Concretely: for each tuple, evaluate its expressions into registers and emit one `InsertRow` opcode. The entire sequence is a flat opcode stream — no new control flow.
- No new AST variant required if the existing AST's tuple field becomes `Vec<Tuple>` instead of `Tuple`; adjust walkers accordingly (small N-visitor tax in Rust, none in C if the AST is struct-of-vectors).
- Non-atomicity: mid-sequence failure (UNIQUE violation on tuple K) leaves tuples 1..K-1 inserted. Pre-WAL semantics per Phase 9g caveat; documented, not a bug.
