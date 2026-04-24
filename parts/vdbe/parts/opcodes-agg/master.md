---
name: vdbe/opcodes-agg
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /schema/opcode.schema.json
  - /parts/core/master.md
  - /parts/vdbe/master.md
emits:
  c: { path: src-c-v2/vdbe/opcodes_agg.c, headers: [src-c-v2/vdbe/opcodes_agg.h] }
  rust: { path: src-rust-v2/vdbe/opcodes_agg.rs }
---

# Part: vdbe/opcodes-agg

Aggregate lifecycle opcodes. Per-aggregate accumulators and the
Step/Final/Reset protocol.

## Canonical enum shape

### Rust

```rust
use crate::core::Register;

pub type AccumulatorSlot = u32;  // index into VdbeState::aggregates

pub enum AggFuncKind {
    CountStar,
    Count,       // COUNT(expr) — non-null count
    CountDistinct,
    Sum,
    Total,
    Avg,
    Min,
    Max,
    GroupConcat,
}

pub enum OpcodeAgg {
    AggReset { acc_slot: AccumulatorSlot, kind: AggFuncKind },
    AggStep  { acc_slot: AccumulatorSlot, kind: AggFuncKind, arg_reg: Register, separator_reg: Option<Register> },
    AggFinal { acc_slot: AccumulatorSlot, kind: AggFuncKind, dest_reg: Register },
    AggValue { acc_slot: AccumulatorSlot, kind: AggFuncKind, dest_reg: Register },
}
```

### C

Discriminator enum + union with operand structs — same pattern as
opcodes-core.

## Per-opcode semantics

| Name | Semantics |
|---|---|
| `AggReset` | Reset accumulator at `acc_slot` to its per-kind initial state. Uses `VdbeState::aggregate_reset(slot, kind)`. Always returns `Continue`. |
| `AggStep` | Apply `regs[arg_reg]` to the accumulator. NULL arguments generally SKIP accumulation (exceptions per kind — see below). GROUP_CONCAT uses `separator_reg` (None → default `','`). Returns `Continue`. |
| `AggFinal` | Read final value via `VdbeState::aggregate_final(slot, kind)` into `regs[dest_reg]`. Per-kind finalization rules (see below). Returns `Continue`. |
| `AggValue` | Read current value without finalizing. Used by WINDOW (read-as-you-go) and HAVING (post-group-close). Returns `Continue`. |

## Per-kind accumulator shapes & finalization

Owned by `VdbeState::aggregates` (Vec of typed accumulators, one
per `acc_slot`). Owner is `parts/vdbe/master.md` — adding this
state:

```rust
pub enum Accumulator {
    CountStar     { n: i64 },
    Count         { n: i64 },
    CountDistinct { n: i64, seen: HashSet<Value<'static>> },
    Sum           { total: f64, any_seen: bool, int_only: bool, int_total: i64 },
    Total         { total: f64 },
    Avg           { sum: f64, count: i64 },
    Min           { best: Option<Value<'static>> },
    Max           { best: Option<Value<'static>> },
    GroupConcat   { buffer: String, first: bool, sep: String },
}
```

Finalization:
- `COUNT(*)` / `COUNT(expr)`: `Value::Integer(n)`.
- `COUNT(DISTINCT expr)`: `Value::Integer(n)`.
- `SUM(expr)`: empty group → `Value::Null`; else Integer if `int_only`, else Real.
- `TOTAL(expr)`: empty group → `Value::Real(0.0)`; else Real.
- `AVG(expr)`: empty group → `Value::Null`; else `Value::Real(sum/count)`.
- `MIN(expr)` / `MAX(expr)`: empty group → `Value::Null`; else the best value seen.
- `GROUP_CONCAT(expr[, sep])`: empty group → `Value::Null`; else `Value::Text(Owned(buffer))`.

NULL handling: all aggregates except `CountStar` skip NULL
arguments.

## Phase pins owned here

- **Phase 6ai** — COUNT(DISTINCT) + MIN/MAX on strings.
- **Phase 6ap** — GROUP_CONCAT + TOTAL.
- **Phase 6bo** — bare-column-in-GROUP-BY (compiler responsibility).
- **#81** — CountStar accumulator reset determinism.
- **#106** — SUM(DISTINCT x) per-group hash-set allocation.

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
