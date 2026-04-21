# Phase 6y test harness — language-neutral spec

Phase 6y adds SQL `CASE` expressions in simple and searched forms. No new VDBE opcodes. `max_invariant=43` unchanged. Algorithm per `spec/sql-grammar.spec.md` § "Phase 6y".

## Invocation

```
<harness-binary> <path-to-phase6y.json>
```

Generated into `src-{lang}/bin/phase6y-test`.

## Output

```
SUMMARY phase=6y target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`.

## Gate

22 cases green on both C and Rust. All prior phases (1..9g, 4a, 6u..6x) regression-green. Byte-identical cross-build on result rows.

## Implementation notes

- **Tokenizer**: add `KEYWORD_CASE`, `KEYWORD_WHEN`, `KEYWORD_THEN`. `ELSE` and `END` may already be reserved from transactions (Phase 6t) and Phase 2c-3; reuse same tokens.
- **Parser**: accept `CASE` at `primary` precedence (same level as parenthesized-expr and function-call). Two forms distinguished by presence of expression between `CASE` and first `WHEN`.
- **Compiler options**:
  - **(a)** Desugar simple-CASE → searched-CASE at parse time (`CASE x WHEN v1 THEN r1 ... END` → `CASE WHEN x=v1 THEN r1 ... END`), caching `x` into a dedicated register first. Then one codegen path for searched-CASE.
  - **(b)** Keep simple-CASE as a distinct AST node; compile directly with cache-register.
- **Codegen for searched-CASE**: sequential `evaluate cond_i into reg`, `JumpIfFalse reg -> L_next_i`, `evaluate r_i into reg_result`, `Jump -> L_done`. Final fall-through emits ELSE (or `LoadConst Null` if absent). Exit label `L_done`.
- **3VL honored by existing `JumpIfFalse`**: Null condition skips the arm (takes the false branch), exactly matching SQL 3VL. No new opcode needed.
- **Simple-CASE Null scrutinee**: `NULL = v_i` is Null for any v_i, so `JumpIfFalse` takes false branch for every WHEN; fall-through to ELSE (or Null).
- **Existing `OP_EQ` semantics** apply inside simple-CASE: cross-type `x = v_i` on non-Null operands raises `EVAL_TYPE_ERROR` per prior phases. Fixtures do not exercise cross-type; if a future regression surfaces, handle per phase-6v precedent (IN-equality's error-suppressing compare is NOT used here — simple-CASE's `=` is regular `=`).

## Spec-leak watch

- Neither generator may use language-native switch/match constructs to implement CASE at the SQL level — it MUST lower to the same `JumpIfFalse`-chain shape so cross-build opcode streams remain compatible.
