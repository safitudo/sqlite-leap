# Phase 6ae test harness — language-neutral spec

Phase 6ae adds EXISTS / NOT EXISTS predicates. Builds on Phase 6ag's scope stack. No new VDBE opcodes. `max_invariant=43` unchanged. Algorithm per `spec/sql-grammar.spec.md` § "Phase 6ae".

## Invocation

```
<harness-binary> <path-to-phase6ae.json>
```

Generated into `src-{lang}/bin/phase6ae-test`.

## Output

```
SUMMARY phase=6ae target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`.

## Gate

10 cases green on both C and Rust. All prior phases regression-green. Byte-identical cross-build on result rows.

Corpus win: upstream `select1..3` must gain another wave of passes (EXISTS count: 117 in select1, 100 in select2, 492 in select3 — but many are already counted against 6ag since they're correlated).

## Implementation notes

- Tokenizer: add `KEYWORD_EXISTS`.
- Parser: `[NOT] EXISTS LPAREN select-statement RPAREN` at primary-expression level. `NOT EXISTS` is a two-token phrase.
- Compile: emit subquery body with a first-row-exit jump. Store `1` on hit, `0` on fall-through. `NOT EXISTS` wraps with `Not` opcode.
- **Critically NO NULL propagation**: EXISTS is row-presence, not value-test. `EXISTS (SELECT NULL)` yields `1` because a row existed.
- Correlated EXISTS: reuses Phase 6ag scope stack — inner references to outer columns are cursor-reads in the inner subquery's compile.

## Cross-build risks

- Optimization: some generators might hoist EXISTS to OR-chain-of-equalities for uncorrelated small-list cases. Don't. Keep canonical lowering for byte-identical opcode streams where possible.
- EXISTS subquery with LIMIT or ORDER BY in inner: should short-circuit at first row regardless (canonical lowering ignores ORDER BY/LIMIT inside EXISTS body — it exits at first row).
