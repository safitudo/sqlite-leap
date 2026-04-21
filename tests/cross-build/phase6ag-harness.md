# Phase 6ag test harness — language-neutral spec

Phase 6ag adds correlated-subquery support via a compiler-level scope stack. No new VDBE opcodes. `max_invariant=43` unchanged. Algorithm per `spec/sql-grammar.spec.md` § "Phase 6ag".

## Invocation

```
<harness-binary> <path-to-phase6ag.json>
```

Generated into `src-{lang}/bin/phase6ag-test`.

## Output

```
SUMMARY phase=6ag target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`.

## Gate

8 cases green on both C and Rust. All prior phases regression-green. Byte-identical cross-build on result rows.

Additionally (corpus): upstream `select1..3.test` pass rates must jump significantly (projected +1000 records cumulative across the three files).

## Implementation notes

- **Scope stack**: when entering an inner subquery's compile, push outer scope's `{alias → cursor_reg, column_map}` onto a stack. Inner column resolution walks the stack from innermost outward.
- **Outer-column reference in inner VDBE**: compiles as a cursor-read against the OUTER cursor (which is live — we're inside its scan loop). No new opcode needed; use whatever "read column X from cursor C" opcode already exists (likely `ColumnRead` or similar from Phase 6e join plan).
- **Correlated-subquery execution**: re-emit the inner subquery program per-outer-row (naive). Inner cursors open/scan/close on each iteration. No memoization. No constant-subquery hoisting in v1.
- **Uncorrelated subqueries remain unchanged**: detect whether an inner subquery references ANY outer column; if not, compile/hoist as before (Phase 6n scalar subquery).

## Cross-build risks

- Opcode stream for correlated subqueries diverges from uncorrelated form — emit position in the overall program changes. Byte-identical row output still required; opcode streams MAY differ.
- Scope-stack data structure is target-private; C and Rust may represent it differently (linked list vs Vec of HashMaps). Correctness is what matters.
- Cross-target failure signal: if fixture `two-level-nesting` passes on one but fails on the other, the scope walk is off-by-one. Diagnose before advancing.
