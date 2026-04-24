---
name: vdbe/opcodes-agg
kind: leaf
inherits:
  - /schema/opcode.schema.json
  - /parts/vdbe/parts/opcodes-expr/master.md
  - /parts/compiler/parts/aggregates/master.md
emits:
  c: { path: src-c/vdbe/opcodes_agg.c, headers: [src-c/vdbe/opcodes_agg.h] }
  rust: { path: src-rust/src/vdbe/opcodes_agg.rs }
---

# Part: vdbe/opcodes-agg

Aggregate lifecycle opcodes. Per-aggregate accumulators and the
Step/Final/Reset protocol.

## Opcodes owned here

| Name | Semantics |
|---|---|
| `AggReset(acc_slot)` | Reset accumulator `acc_slot` to its per-function initial state. |
| `AggStep(acc_slot, func_id, arg_regs)` | Apply one row's contribution to the accumulator. |
| `AggFinal(acc_slot, dest_reg)` | Compute the final value and store in `regs[dest_reg]`. |
| `AggValue(acc_slot, dest_reg)` | Read the current accumulator value without finalizing (used for WINDOW and HAVING). |

## Accumulator state per function

- `COUNT(*)`: `{n: integer}`.
- `COUNT(expr)`: `{n: integer}`.
- `COUNT(DISTINCT expr)`: `{n: integer, seen: HashSet<Value>}`.
- `SUM(expr)`: `{total: numeric, any_seen: bool}`. Empty → NULL.
- `TOTAL(expr)`: `{total: real}`. Empty → 0.0.
- `AVG(expr)`: `{sum: numeric, count: integer}`. Empty → NULL.
- `MIN(expr)` / `MAX(expr)`: `{best: Value or None}`.
- `GROUP_CONCAT(expr [, sep])`: `{buffer: String, first: bool}`.

## Phase pins

- **Phase 6ai** — COUNT(DISTINCT) + MIN/MAX on strings.
- **Phase 6ap** — GROUP_CONCAT + TOTAL.
- **Phase 6bo** — bare-column-in-GROUP-BY (compiler responsibility;
  runtime is transparent).
- **#81** — CountStar accumulator correlated+uncorrelated+ORDER BY
  panic fixed; accumulator cleanup on group close is now
  deterministic.
- **#106** — SUM(DISTINCT x) with multi-table FROM no longer
  panics; DISTINCT hash-set is allocated per-group, not per-row.

## Regeneration envelope

- Target leaf size: 400–600 lines per target.
- Spec < 150 lines.
