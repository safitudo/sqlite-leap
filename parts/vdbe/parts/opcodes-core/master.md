---
name: vdbe/opcodes-core
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /schema/opcode.schema.json
  - /schema/value.schema.json
  - /parts/storage/master.md
emits:
  c:
    path: src-c/vdbe/opcodes_core.c
    headers: [src-c/vdbe/opcodes_core.h]
  rust:
    path: src-rust/src/vdbe/opcodes_core.rs
---

# Part: vdbe/opcodes-core

The foundational VDBE opcode family: program control, constant
loading, register moves, cursor lifecycle, row emission. Every
other opcode family assumes these work.

## Opcodes owned here

| Name | Operands | Semantics |
|---|---|---|
| `Halt` | — | Terminates execution. `pc = len(opcodes)` on completion. No further opcodes execute. |
| `LoadConst` | `dest_reg`, `value` | Write `value` into `regs[dest_reg]`. `value` is a Value (null/integer/real/text/blob). Text/blob values are owned (outlive the program source buffer). |
| `Move` | `src_reg`, `dest_reg` | Move `regs[src_reg]` into `regs[dest_reg]`. After Move, `regs[src_reg]` is NULL (move semantics). |
| `Copy` | `src_reg`, `dest_reg` | Copy `regs[src_reg]` to `regs[dest_reg]`. `regs[src_reg]` unchanged. |
| `OpenRead` | `cursor`, `table_name` | Open a read cursor on `table_name`. If the table doesn't exist: raise `RUNTIME_TABLE_NOT_FOUND` (this should be unreachable — compiler validates). |
| `OpenWrite` | `cursor`, `table_name` | Open a write cursor. Mutually exclusive with `OpenRead` on the same cursor slot. |
| `Close` | `cursor` | Release the cursor. After Close, any read/write through `cursor` raises `RUNTIME_CURSOR_CLOSED`. |
| `ResultRow` | `start_reg`, `count` | Emit a row containing `[regs[start_reg], regs[start_reg + 1], ..., regs[start_reg + count - 1]]` to the caller's row sink. |

## Execution protocol

Each opcode function signature (language-neutral):

```
fn execute_opcode_core(
    op:     &OpcodeCore,
    state:  &mut VdbeState,
) -> OpcodeOutcome
```

`OpcodeOutcome` is one of:

- `Continue` — advance pc by 1.
- `Jump(target_pc)` — set pc to `target_pc`. NOT used by this
  family; declared here for uniformity across all opcode-family
  dispatch.
- `Halt(status)` — end execution; status is `HaltedOk` |
  `HaltedError(cond)`.
- `EmitRow(start, count)` — signal to the outer execution loop
  that it should read `count` values starting at `regs[start]`
  and push them to the caller.

`Halt` opcode returns `Halt(HaltedOk)`. Other opcodes return
`Continue` on success, `Halt(HaltedError(cond))` on runtime fault.

## Invariants

- `dest_reg` and `src_reg` must be in `[0, state.num_registers)`.
  Violation → `RUNTIME_OPCODE_ILLEGAL`. (Should be unreachable;
  compiler validates at emit time.)
- `cursor` in `OpenRead` / `OpenWrite` / `Close` must be in
  `[0, state.num_cursors)`. Same enforcement as above.
- `count` in `ResultRow` satisfies `start_reg + count ≤
  num_registers`. Same enforcement.

## Memory discipline (per /spec/memory-discipline.spec.md)

- `LoadConst` with `Value::Text` or `Value::Blob` embeds an **owned**
  byte buffer in the opcode payload — written once at compile time,
  cloned into register only when the register's holder needs
  ownership (e.g., when the register value crosses a ResultRow
  boundary where the caller consumes it).
- `Copy` preserves ownership semantics: owned values are cloned;
  borrowed values share the borrow.
- `Move` transfers ownership and leaves the source register NULL.
  This is the primitive used by compilers to avoid redundant clones
  when a value is consumed once.

## Well-formedness hooks

The compiler assumes:

- Exactly one `Halt` opcode, at the final position, per Program.
- No opcode executes after `Halt` (unreachable code is invalid).
- `ResultRow` reads only initialized registers — a register may
  have been `LoadConst`'d, `Copy`'d, `Move`'d into, or written by
  a row-read opcode (`parts/opcodes-rows/`) but never read without
  a prior write.

## Regeneration envelope

- Target leaf size: 300–500 lines per target.
- Spec < 200 lines.
- Test ownership: `tests/opcodes_core.json` with one fixture per
  opcode covering the Continue / Halt / EmitRow outcomes.
