---
name: vdbe/opcodes-core
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /schema/opcode.schema.json
  - /schema/value.schema.json
  - /parts/core/master.md
  - /parts/storage/master.md
emits:
  c:
    path: src-c-v2/vdbe/opcodes_core.c
    headers: [src-c-v2/vdbe/opcodes_core.h]
  rust:
    path: src-rust-v2/vdbe/opcodes_core.rs
---

# Part: vdbe/opcodes-core

The foundational VDBE opcode family: program control, constant
loading, register moves, cursor lifecycle, row emission. Every
other opcode family assumes these work.

## Opcodes owned here — canonical enum shape

Emit EXACTLY this enum (variant names and field names verbatim;
target syntax per language):

### Rust

```rust
use crate::core::{Value, Register, CursorId};

pub enum OpcodeCore<'src> {
    Halt,
    LoadConst  { dest_reg: Register, value: Value<'src> },
    Move       { src_reg: Register,  dest_reg: Register },
    Copy       { src_reg: Register,  dest_reg: Register },
    OpenRead   { cursor: CursorId,   table: &'src str },
    OpenWrite  { cursor: CursorId,   table: &'src str },
    Close      { cursor: CursorId },
    ResultRow  { start_reg: Register, count: u32 },
}
```

### C

```c
typedef enum LeapOpcodeCoreKind {
    LEAP_OPC_HALT = 0,
    LEAP_OPC_LOAD_CONST,
    LEAP_OPC_MOVE,
    LEAP_OPC_COPY,
    LEAP_OPC_OPEN_READ,
    LEAP_OPC_OPEN_WRITE,
    LEAP_OPC_CLOSE,
    LEAP_OPC_RESULT_ROW,
} LeapOpcodeCoreKind;

typedef struct LeapOpcodeCore {
    LeapOpcodeCoreKind kind;
    union {
        struct { LeapRegister dest_reg; LeapValue value; } load_const;
        struct { LeapRegister src_reg; LeapRegister dest_reg; } move_;
        struct { LeapRegister src_reg; LeapRegister dest_reg; } copy;
        struct { LeapCursorId cursor; const char* table; size_t table_len; } open_read;
        struct { LeapCursorId cursor; const char* table; size_t table_len; } open_write;
        struct { LeapCursorId cursor; } close;
        struct { LeapRegister start_reg; uint32_t count; } result_row;
    } as;
} LeapOpcodeCore;
```

## Per-opcode semantics

| Name | Semantics |
|---|---|
| `Halt` | Terminates execution. Returns `OpcodeOutcome::Halt(HaltStatus::Ok)`. The outer loop sets pc beyond end. |
| `LoadConst { dest_reg, value }` | `state.set_register(dest_reg, value.clone())`. Returns `Continue`. |
| `Move { src_reg, dest_reg }` | `let v = state.take_register(src_reg); state.set_register(dest_reg, v);`. After Move, `regs[src_reg]` is `Value::Null`. If `src == dest`: register becomes Null (net effect of take-then-set to same slot). Returns `Continue`. |
| `Copy { src_reg, dest_reg }` | `let v = state.get_register(src_reg).clone(); state.set_register(dest_reg, v);`. `regs[src_reg]` unchanged. If `src == dest`: no-op, skip clone. Returns `Continue`. |
| `OpenRead { cursor, table }` | Ask `storage` to open a read cursor on `table`; on success, `state.set_cursor(cursor, handle)`. If the table doesn't exist: `Halt(HaltStatus::Error(RuntimeCondition::TableNotFound))`. If the cursor slot is already open: **replace silently** (compiler is responsible for Close first). Returns `Continue` on success. |
| `OpenWrite { cursor, table }` | Same as `OpenRead` but opens a writable cursor. |
| `Close { cursor }` | `state.take_cursor(cursor)` — releases the handle. If the slot was already empty: no-op (idempotent). Returns `Continue`. |
| `ResultRow { start_reg, count }` | Returns `OpcodeOutcome::EmitRow { start: start_reg, count }`. Outer loop reads `[start .. start+count)` and pushes to caller's row sink, then advances pc. `count == 0` is ill-formed: `Halt(HaltStatus::Error(RuntimeCondition::OpcodeIllegal))`. |

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
