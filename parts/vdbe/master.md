---
name: vdbe
kind: inner
inherits:
  - /spec/memory-discipline.spec.md
  - /schema/program.schema.json
  - /schema/opcode.schema.json
  - /schema/value.schema.json
  - /parts/storage/master.md
emits:
  c:
    path: src-c/vdbe/mod.h
  rust:
    path: src-rust/src/vdbe/mod.rs
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
