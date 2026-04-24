---
name: vdbe
kind: inner
inherits:
  - /spec/memory-discipline.spec.md
  - /schema/program.schema.json
  - /schema/opcode.schema.json
  - /schema/value.schema.json
  - /parts/core/master.md
  - /parts/storage/master.md
emits:
  c:
    path: src-c-v2/vdbe/mod.h
  rust:
    path: src-rust-v2/vdbe/mod.rs
---

# Part: vdbe

The Virtual Database Engine. Consumes a well-formed `Program` and a
mutable `Database` handle. Executes opcodes in order, driven by
program-counter control flow. Emits rows to the caller's row sink.

## Public interface

- **Input:** `program: &Program<'src>`, `database: &mut Database`.
- **Output on success:** stream of rows (each a vector of values
  conformant to `/schema/value.schema.json`) + final status
  (`VDBE_HALTED_OK`, `VDBE_HALTED_NO_ROWS`, etc.).
- **Output on failure:** named runtime error condition. Categories
  (each a separate condition):
  - `RUNTIME_TYPE_MISMATCH` — operand type invalid for opcode.
  - `RUNTIME_ARITH_OVERFLOW` — integer overflow on arithmetic.
  - `RUNTIME_DIV_ZERO` — division by zero (yields NULL per SQLite,
    not an error, BUT the condition exists for diagnostics).
  - `RUNTIME_CONSTRAINT_*` — constraint violation (NOT NULL, UNIQUE,
    CHECK, FK).
  - `RUNTIME_CURSOR_CLOSED` — opcode touched a closed cursor.
  - `RUNTIME_RECURSIVE_CTE_LIMIT` — recursive CTE exceeded iteration
    limit.
  - `RUNTIME_OPCODE_ILLEGAL` — an ill-formed Program slipped past
    the compiler validator (should be unreachable in practice).

## Execution loop (canonical pseudo-code)

```
pc = 0
while pc < len(program.opcodes):
  op = program.opcodes[pc]
  next_pc = execute(op, state) ? pc + 1
  pc = next_pc
```

`execute(op, state)` is a switch on opcode kind that dispatches to
the appropriate opcode-family sub-part.

## Sub-part map

Opcodes group into seven families. Each is a leaf sub-part; the
outer `vdbe` part composes their dispatch.

- `parts/opcodes-core/` — `Halt`, `LoadConst`, `Move`, `OpenRead`,
  `OpenWrite`, `Close`, `Copy`, `ResultRow`.
- `parts/opcodes-rows/` — `InsertRow`, `UpdateRow`, `DeleteRow`,
  `Rewind`, `Next`, `Prev`, `SeekRowid`, `Column`.
- `parts/opcodes-scan/` — sequential scan, index scan (`SeekGE`,
  `SeekGT`, `SeekLE`, `SeekLT`, `IdxNext`).
- `parts/opcodes-expr/` — arithmetic (`Add`, `Subtract`, `Multiply`,
  `Divide`, `Modulo`), comparison (`Eq`, `Ne`, `Lt`, `Le`, `Gt`,
  `Ge`), logical (`And`, `Or`, `Not`), type (`Cast`, `IsNull`,
  `NotNull`), string (`Concat`, `Like`, `Glob`, `Substr`, `Replace`,
  `Instr`), scalar function dispatch.
- `parts/opcodes-agg/` — `AggStep`, `AggFinal`, `AggReset` for all
  aggregate functions (`COUNT`, `SUM`, `TOTAL`, `AVG`, `MIN`, `MAX`,
  `GROUP_CONCAT`).
- `parts/opcodes-window/` — window frame ops (`WindowStep`,
  `WindowValue`, frame boundary management, `ROW_NUMBER`).
- `parts/opcodes-control/` — `Goto`, `If`, `IfNot`, `Jump`,
  `JumpIfNull`, subroutine-like `Gosub`/`Return` if used.

## Well-formedness invariants (inherited from compiler)

The VDBE assumes every Program it receives is well-formed. If it
receives a Program that fails any invariant (declared in
`parts/compiler/master.md` § "Well-formedness"), it raises
`RUNTIME_OPCODE_ILLEGAL` without attempting recovery. The compiler
is the well-formedness authority; the VDBE is the executor.

## Register and cursor state

- Registers: flat array sized to `program.num_registers`. Each cell
  holds a typed Value (NULL, integer, real, text, blob). Assignment
  copies by value (for integer/real) or by move-of-borrow (for text
  — sub-parts carry the source lifetime).
- Cursors: array sized to `program.num_cursors`. Each holds a
  table/index handle, current position, and a "dirty" hint for
  write-path pass-through.

## `VdbeState<'src>` — canonical shape (owned by this part)

The execution state is the shared mutable interface every opcode
family operates on. Owned here; sub-parts use it through its
methods.

### Rust

```rust
use crate::core::{Value, Register, CursorId, RuntimeCondition, HaltStatus};
use crate::storage::CursorHandle;

pub struct VdbeState<'src> {
    regs:    Vec<Value<'src>>,
    cursors: Vec<Option<CursorHandle>>,
    pc:      usize,
}

impl<'src> VdbeState<'src> {
    pub fn new(num_registers: usize, num_cursors: usize) -> Self { /* ... */ }
    pub fn num_registers(&self) -> usize { self.regs.len() }
    pub fn num_cursors(&self) -> usize { self.cursors.len() }

    pub fn get_register(&self, r: Register) -> &Value<'src>;
    pub fn set_register(&mut self, r: Register, v: Value<'src>);
    pub fn take_register(&mut self, r: Register) -> Value<'src>;  // Move: leaves Null

    pub fn set_cursor(&mut self, c: CursorId, h: CursorHandle);
    pub fn take_cursor(&mut self, c: CursorId) -> Option<CursorHandle>;
    pub fn cursor_mut(&mut self, c: CursorId) -> Result<&mut CursorHandle, RuntimeCondition>;
    pub fn cursor_is_open(&self, c: CursorId) -> bool;

    pub fn pc(&self) -> usize;
    pub fn set_pc(&mut self, pc: usize);
}
```

### C

```c
typedef struct LeapVdbeState {
    LeapValue*    regs;       size_t num_regs;
    LeapCursor**  cursors;    size_t num_cursors;
    size_t        pc;
} LeapVdbeState;

// API surface mirrors the Rust methods above, with out-parameters
// for fallible operations that return LeapRuntimeCondition.
```

Sub-parts MUST use these method names. Field access is forbidden.

## `Opcode<'src>` — canonical aggregation pattern (owned by this part)

Each opcode-family leaf declares its own sub-enum. This part's
generator composes a union:

```rust
pub enum Opcode<'src> {
    Core(OpcodeCore<'src>),        // from parts/opcodes-core/
    Rows(OpcodeRows<'src>),        // from parts/opcodes-rows/
    Scan(OpcodeScan),               // from parts/opcodes-scan/
    Expr(OpcodeExpr<'src>),         // from parts/opcodes-expr/
    Agg(OpcodeAgg),                 // from parts/opcodes-agg/
    Window(OpcodeWindow),           // from parts/opcodes-window/
    Control(OpcodeControl),         // from parts/opcodes-control/
}
```

Dispatch:

```rust
pub fn execute(op: &Opcode<'src>, state: &mut VdbeState<'src>) -> OpcodeOutcome {
    match op {
        Opcode::Core(o)    => opcodes_core::execute(o, state),
        Opcode::Rows(o)    => opcodes_rows::execute(o, state),
        Opcode::Scan(o)    => opcodes_scan::execute(o, state),
        Opcode::Expr(o)    => opcodes_expr::execute(o, state),
        Opcode::Agg(o)     => opcodes_agg::execute(o, state),
        Opcode::Window(o)  => opcodes_window::execute(o, state),
        Opcode::Control(o) => opcodes_control::execute(o, state),
    }
}
```

Each family's `execute` function is the public entry point its
leaf master.md declares. The vdbe/ generator emits this composition
file automatically from the list of children.

## Cross-opcode invariants

- Every opcode advances pc by 1 unless it jumps. `OpHalt` exits the
  loop.
- Opcodes that fault ( `RUNTIME_*` ) abort execution immediately;
  no partial row emission.
- Cursor ops only touch cursors in `[0, num_cursors)`; compiler
  validates, VDBE asserts.
- `ResultRow` emits exactly the registers named in its operand
  list; no implicit trailing registers.

## Composition

Each opcode-family sub-part emits a dispatch function keyed by
opcode kind. The `vdbe` part's generator produces a single
`execute` function that switches on opcode kind and calls the
matching family. A static table maps opcode kind → family — this
table is generated from the union of each sub-part's declared
opcode list.
