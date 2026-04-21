# Phase 6ba test harness — language-neutral spec

Phase 6ba un-defers `ORDER BY <integer-literal>` (positional projection reference). Compile-time rewrite of bare `IntLiteral` order-by-term to point at the Nth projection column (1-indexed). No new VDBE opcodes. `max_invariant=43` unchanged. Algorithm per `spec/sql-grammar.spec.md` § "Phase 6ba".

## Invocation

```
<harness-binary> <path-to-phase6ba.json>
```

Generated into `src-{lang}/bin/phase6ba-test`.

## Output

```
SUMMARY phase=6ba target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`.

## Gate

13 cases green on both C and Rust. All prior phases regression-green. Byte-identical cross-build on result rows.

Corpus win — this is the largest single correctness unlock in the project so far:
- `select1.test` uses `ORDER BY <integer>` exclusively (1000 occurrences, 0 uses of `ORDER BY <identifier>`), and all 1031 of its queries are in `nosort` mode — so our current no-op treatment of positional ORDER BY invalidates the entire file.
- Projected jump: `select1` from 680/1031 (66%) to ~1020/1031 (99%). Overall select1..3 to ~99%.

## Implementation notes

- Do NOT change the grammar. An integer literal is already a valid expression in an order-by-term. The change is in the compile step.
- Intercept at the point where the compiler lowers an `order-by-term` into sort-key emission. If the term's expression AST node is exactly `IntLiteral(N)`:
    - `1 <= N <= projection_count`: substitute `projection[N-1].expression` as the sort key expression. Preserve the term's direction (ASC/DESC).
    - Otherwise: raise `COMPILE_ORDER_BY_POSITION_OUT_OF_RANGE { position: N, projection_count: P }`.
- The check must be **syntactic** — key off the AST node kind (`IntLiteral`), not the semantic value. `Paren(IntLiteral(1))`, `BinaryOp(Int(1), +, Int(0))`, `UnaryOp(Neg, Int(1))`, `RealLiteral(1.0)` are all NOT positional.
- For aggregate projections, the sort key should be the *value* of the projection, not a re-evaluation of the underlying expression. Each generator may choose (a) re-reference the materialised projection register or (b) emit the same expression a second time into the sort key. Either is acceptable — both produce identical row ordering and byte-identical result rows.

## Cross-build risks

- **Syntactic matching, not semantic.** If one generator is overly clever and treats `1+0` or `(1)` as positional-after-constant-fold, it will diverge from the other. Match the AST node shape only.
- **Projection register reuse.** If one generator reads the projection register and another re-emits the projection expression, both sort keys must be identical for the same row. The spec allows either choice — verify by running the corpus, not by spot-check of a single fixture.
- **Test authority fixtures include:** `not-positional-expression-stays-expression` (ORDER BY 1+0) and `not-positional-negative-stays-expression` (ORDER BY -1) — both expect insertion order preserved (no-op sort by constant). If these fail, one of the generators is doing semantic-value inference; back it out.

## Corpus validation post-landing

After both C and Rust 6ba are green on the fixture, immediately run:

```
./src-c/bin/sqllogictest tests/sqllogictest/upstream/test/select1.test | tail -1
./src-rust/target/release/sqllogictest tests/sqllogictest/upstream/test/select1.test | tail -1
```

Expect both: `passed=~1020 failed=~10 skipped=0 total=1031`, byte-identical summaries.
