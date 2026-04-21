# Phase 6az test harness — language-neutral spec

Phase 6az adds `NOT BETWEEN` as a parse-time desugar to `NOT (x BETWEEN lo AND hi)`. No new VDBE opcodes. `max_invariant=43` unchanged. Algorithm per `spec/sql-grammar.spec.md` § "Phase 6az".

## Invocation

```
<harness-binary> <path-to-phase6az.json>
```

Generated into `src-{lang}/bin/phase6az-test`.

## Output

```
SUMMARY phase=6az target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`.

## Gate

7 cases green on both C and Rust. All prior phases regression-green. Byte-identical cross-build on result rows.

Corpus win: upstream `select1..3` gains ~771 records (114 in select1, 101 in select2, 556 in select3) — `NOT BETWEEN` is the single biggest remaining parse-error blocker.

## Implementation notes

- Tokenizer: no new keywords. `NOT` and `BETWEEN` already tokenized.
- Parser: at the point where a comparison/predicate is being parsed, after the left operand, if the lookahead is `NOT BETWEEN`, desugar to `UnaryOp(Not, Between(lhs, lo, hi))`. Canonical AST: reuse existing `Between` node wrapped by `Not`.
- Precedence: `NOT BETWEEN` binds at the same level as `BETWEEN` (which is at the comparison level per SQL). The two-token phrase is consumed together — do NOT re-enter the prefix-`NOT` rule.
- NULL semantics (3VL): identical to `NOT (x BETWEEN lo AND hi)`. If any operand is Null, the `BETWEEN` yields Null and `NOT Null = Null`. In WHERE, Null is filtered out → row excluded.
- Compile: zero new codegen — the desugared AST reuses existing `Between` and `Not` compilers.

## Cross-build risks

- **Do NOT implement as a separate opcode.** Must desugar at parse time for byte-identical opcode stream vs. explicit `NOT (x BETWEEN ...)`.
- Lookahead: must be two-token (NOT then BETWEEN). Don't greedily consume `NOT` alone and fail back — that would produce a different AST.
- Precedence preservation: `a = 1 AND b NOT BETWEEN 2 AND 3` must parse as `(a = 1) AND (NOT (b BETWEEN 2 AND 3))`, not `a = 1 AND (NOT b) BETWEEN 2 AND 3`.
