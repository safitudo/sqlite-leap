# Phase 6x test harness — language-neutral spec

Phase 6x adds LIKE / NOT LIKE pattern matching with `%` and `_` wildcards. One new opcode kind `Scalar2::Like` (invariant 43, `max_invariant=43`). Algorithm per `spec/sql-grammar.spec.md` § "Phase 6x".

## Invocation

```
<harness-binary> <path-to-phase6x.json>
```

Generated into `src-{lang}/bin/phase6x-test`.

## Output

```
SUMMARY phase=6x target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`.

## Gate

22 cases green on both C and Rust. All prior phases (1..9g, 4a, 6u, 6v, 6w) regression-green. Byte-identical cross-build on result rows.

## Implementation notes

- **Tokenizer**: `LIKE` and `NOT` already tokens. No new tokens.
- **Parser**: accept `expr [NOT] LIKE expr` at the same precedence level as comparison operators. `NOT LIKE` is a two-token sequence parsed as a single operator kind.
- **Compiler / VDBE**:
  - Introduce `Scalar2::Like` (binary: subject, pattern → Integer 0/1 or Null).
  - `NOT LIKE` desugars to `NOT (x LIKE y)` — reuses the Phase-6u `Not` opcode path. No second opcode.
- **Semantics** (byte-level, case-sensitive, no ESCAPE in v1):
  - Either operand `Null` → result `Null` (3VL).
  - Either operand not `Text` → result `Null` (per 3VL, not an error).
  - `%` in pattern matches any run of bytes including empty.
  - `_` in pattern matches exactly one byte.
  - All other pattern bytes match themselves byte-exactly (non-ASCII incl.).
  - Matching algorithm: standard backtracking / DP glob over bytes. Reference pseudo-code in the spec section.
- **Spec-leak watch**: neither generator may reference `strcmp`, Rust `str::chars`, regex libraries, or locale-aware comparison. Byte-for-byte only.
