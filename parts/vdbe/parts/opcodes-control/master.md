---
name: vdbe/opcodes-control
kind: leaf
inherits:
  - /schema/opcode.schema.json
  - /parts/vdbe/parts/opcodes-core/master.md
emits:
  c: { path: src-c/vdbe/opcodes_control.c, headers: [src-c/vdbe/opcodes_control.h] }
  rust: { path: src-rust/src/vdbe/opcodes_control.rs }
---

# Part: vdbe/opcodes-control

Control-flow opcodes. Unconditional and conditional jumps.

## Opcodes owned here

| Name | Semantics |
|---|---|
| `Goto(target_pc)` | Unconditional jump. |
| `If(cond_reg, target_pc)` | Jump if `regs[cond_reg]` is truthy. Truthy = not-NULL and not integer 0. |
| `IfNot(cond_reg, target_pc)` | Jump if `regs[cond_reg]` is NULL or 0. |
| `JumpIfNull(reg, target_pc)` | Jump if `regs[reg]` is NULL. |
| `Gosub(target_pc)` | Push return pc, jump to target. Used by some subquery patterns. |
| `Return` | Pop return pc, jump to it. |

## Jump target invariants

- All targets must be in `[0, len(program.opcodes))`. Compiler
  validates.
- Jumps into the middle of a contiguous block (e.g., jumping past
  `Gosub` to a `Return`) are legal if all targets are well-formed
  opcode positions.

## Phase pins

None owned here — control flow is baseline infrastructure.

## Regeneration envelope

- Target leaf size: 150–300 lines per target.
- Spec < 80 lines.
