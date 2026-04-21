# Phase 6bc test harness — language-neutral spec

Phase 6bc allows the empty form `x IN ()` and `x NOT IN ()`. `x IN ()` is always Int(0) for non-Null x, Null for Null x. `x NOT IN ()` is always Int(1) / Null symmetrically. Algorithm per `spec/sql-grammar.spec.md` § "Phase 6bc".

## Invocation

```
<harness-binary> <path-to-phase6bc.json>
```

Generated into `src-{lang}/bin/phase6bc-test`.

## Output

```
SUMMARY phase=6bc target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`.

## Gate

8 cases green on both C and Rust. All prior phases regression-green. Byte-identical cross-build.

Corpus win: unblocks `evidence/in2.test` (9 records); pattern appears in other corpus files too.

## Implementation notes

- Tokenizer: no changes.
- Parser: in the `in-list` production (Phase 6v), allow zero expressions between LPAREN and RPAREN.
- Compile: detect empty `in-list` at compile time. Emit: evaluate x; if Null → Null; else → Int(0) (for IN) or Int(1) (for NOT IN). No comparison loop.
- 3VL consistency: Null in x still propagates through empty-IN.

## Cross-build risks

- Do not treat empty IN as "always false" unconditionally — Null still propagates. 3VL is pinned.
- Malformed `IN (,)` with stray comma remains PARSE_UNEXPECTED_TOKEN. Empty parens ONLY means zero expressions total.
