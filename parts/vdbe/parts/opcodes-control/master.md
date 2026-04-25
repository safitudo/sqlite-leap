---
name: vdbe/opcodes-control
---

# Part: vdbe/opcodes-control

Control-flow opcodes: unconditional jump, boolean-guarded jumps,
null-guarded jump, bounded-depth subroutine calls. Shape
declarations live in `shapes.json`; this file describes only
the semantic contract of each opcode.

## Semantic contract

Each opcode below returns an `OpcodeOutcome`. The outer VDBE loop
consumes the outcome — the opcode handler itself never touches the
program counter directly (that's the loop's job).

### `Goto { target }`

Unconditional jump. Returns `Jump(target)`.

### `If { cond_reg, target }`

Read register `cond_reg`. If the value is **truthy**, return
`Jump(target)`; else return `Continue`.

### `IfNot { cond_reg, target }`

Read register `cond_reg`. If the value is **falsy**, return
`Jump(target)`; else return `Continue`.

### `JumpIfNull { reg, target }`

Read register `reg`. If the value is `Value::Null`, return
`Jump(target)`; else return `Continue`.

### `Gosub { target }`

Push the address `pc + 1` onto the return stack, then return
`Jump(target)`. If the return stack is already at
`RETURN_STACK_MAX_DEPTH`, return
`Halt(Error(RuntimeCondition::OpcodeIllegal))` instead — this is a
well-formedness violation (the compiler should have prevented
unbounded recursion).

### `Return`

Pop the top of the return stack. Return `Jump(popped_pc)`. If the
stack is empty, return `Halt(Error(RuntimeCondition::OpcodeIllegal))`.

### `HaltError { condition }`

Return `Halt(Error(condition))` unconditionally. Used by INSERT
OR ABORT/FAIL/ROLLBACK on conflict (condition =
`ConstraintUnique`) and any compile-emitted abort path. Distinct
from a clean Halt(Ok): the runtime condition surfaces to the
caller so the embedding layer can map it to its native error
shape.

## Truthiness rule

`If` / `IfNot` interpret register values as follows:

| Value     | Truthy? |
|-----------|---------|
| `Null`    | false   |
| `Integer(0)` | false |
| `Integer(n != 0)` | true |
| `Real(0.0)` | false (positive and negative zero both falsy) |
| `Real(non-zero, non-NaN)` | true |
| `Real(NaN)` | false |
| `Text(_)` | true (regardless of content — empty strings are still truthy here; SQL's own truthiness differs at higher layers) |
| `Blob(_)` | true (regardless of content) |

This is the **VDBE-internal** truthiness. The SQL-level truth value
for `WHERE x` comes from a prior `Cast` / comparison that reduces
to an Integer or Null before `If` sees it; the compiler is
responsible for that lowering.

## Return-stack bound

`RETURN_STACK_MAX_DEPTH = 64`. This prevents pathological
programs (or compiler bugs) from causing unbounded memory growth
via runaway `Gosub`. The bound is observable in diagnostics as
`RuntimeCondition::OpcodeIllegal` at the offending `Gosub`.

## Memory discipline

All opcodes in this family are pure with respect to register and
cursor state: none allocate, none free, none clone a `Value`. The
only state mutation is `pc` (implicit via the returned outcome) and
the return stack (for `Gosub` / `Return`). Cross-target emissions
should reflect this: no `clone` / `release` calls anywhere in this
file's implementations.

## Phase pins

- **Phase 2** — initial VDBE control-flow opcodes; stable since the
  first v1 green run.
- **#78** — closed-cursor fault surface consistency (fixed upstream
  in `opcodes-rows`, not here; listed because the return-stack
  fault path reuses the same `OpcodeIllegal` condition).

## Regeneration envelope

- Spec (this file): < 150 lines.
- `shapes.json`: < 60 lines.
- Each target emission: ~150–250 lines (Rust), ~200–300 lines (C).
