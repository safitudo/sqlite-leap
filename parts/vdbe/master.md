---
name: vdbe
kind: inner
inherits:
  - /spec/type-system.spec.md
  - /spec/memory-discipline.spec.md
  - /parts/core/master.md
shapes: ./shapes.json
emits:
  rust: { path: src-rust/vdbe/mod.rs }
  c:    { path: src-c/vdbe/mod.c, headers: [src-c/vdbe/mod.h] }
---

# Part: vdbe

The Virtual Database Engine. Consumes a compiled `Program` and a
mutable `Database` handle, executes opcodes in order driven by a
program counter, and emits rows to the caller's row sink.

This file describes the **shared execution state** and the
composition contract for opcode families. The shape of
`VdbeState` and its method surface live in `shapes.json`; this
prose carries semantics and invariants only.

## Execution loop

Canonical pseudo-code (language-neutral):

```
pc = 0
while pc < program.opcode_count:
  op = program.opcodes[pc]
  outcome = execute(op, state)
  match outcome:
    Continue            -> pc += 1
    Jump(target)        -> pc  = target
    Halt(status)        -> return status
    EmitRow{start,cnt}  -> emit_row(state, start, cnt); pc += 1
```

`execute` dispatches on opcode kind and calls the matching
opcode-family sub-part. The union-of-families opcode type is
composed by this part's generator from the set of children.

## Sub-part map

Opcodes group into seven families. Each is a leaf sub-part; the
outer `vdbe` part composes their dispatch.

- `parts/opcodes-core/` — basic: Halt, LoadConst, Move, OpenRead,
  OpenWrite, Close, Copy, ResultRow.
- `parts/opcodes-rows/` — row-level: InsertRow, UpdateRow,
  DeleteRow, Rewind, Next, Prev, SeekRowid, Column.
- `parts/opcodes-scan/` — index/table scan: sequential scan,
  SeekGE/GT/LE/LT, IdxNext, IdxRowid.
- `parts/opcodes-expr/` — expression evaluation: arithmetic,
  comparison, logical, cast, string ops, scalar functions.
- `parts/opcodes-agg/` — aggregate lifecycle: AggStep, AggFinal,
  AggReset for all aggregate functions.
- `parts/opcodes-window/` — window functions: row numbering, rank,
  aggregate-as-window.
- `parts/opcodes-control/` — control flow: Goto, If, IfNot,
  JumpIfNull, Gosub, Return.

Each family declares its own `OpcodeXxx` variant in its own
`shapes.json`. This part's generator composes a union
`Opcode` variant with one case per family, plus a free
`execute` function that dispatches to the matching family's
`execute`.

## Well-formedness invariants

The VDBE assumes every Program it receives is well-formed. If an
invariant is violated (out-of-range register, unknown opcode kind,
return-stack overflow), the VDBE raises
`RuntimeCondition::OpcodeIllegal` without attempting recovery. The
compiler is the well-formedness authority; the VDBE is the executor.

## Execution state

`VdbeState` is the shared mutable interface every opcode family
operates on. Sub-parts access it through the methods declared in
`shapes.json`; direct field access is forbidden.

Core fields (abstract — target mappings materialize):

- **Register file** — flat array sized to `program.num_registers`.
  Each slot holds a typed `Value`. Assignment to a slot releases
  any prior owned payload.
- **Cursor slots** — flat array sized to `program.num_cursors`.
  Each slot either holds an open cursor handle or is empty.
- **Program counter** — current opcode index.
- **Return stack** — bounded-depth stack of return addresses for
  `Gosub` / `Return`. Depth bounded by
  `RETURN_STACK_MAX_DEPTH` (64). Overflow raises
  `RuntimeCondition::OpcodeIllegal`.

Additional fields owned by specific opcode families
(aggregate accumulators in `opcodes-agg`, window sessions in
`opcodes-window`) are declared in their sub-part's `shapes.json`
and composed into `VdbeState` by this part's generator.

## Cross-opcode invariants

- Every opcode advances the program counter by 1 unless it returns
  `Jump` or `Halt`. `EmitRow` both emits and advances.
- Opcodes that fault abort execution immediately; no partial row
  emission.
- Cursor ops only touch cursors in `[0, num_cursors)`. Compiler
  validates; VDBE asserts.
- `ResultRow` emits exactly the registers named in its operand
  list; no implicit trailing registers.

## Composition

The root generator, after all sub-parts emit, produces a
`vdbe/mod.rs` (or `vdbe/mod.c` + `vdbe/mod.h`) containing:

1. The union `Opcode` variant over all family sub-enums.
2. A `dispatch` table mapping opcode kinds to family execute
   functions.
3. The outer execution loop described above.

Sub-parts never see this composition; they declare only their own
variant and execute function.

## Regeneration envelope

- Spec: < 300 lines.
- `shapes.json`: < 100 lines.
- Composed `mod.*` per target: ~150 lines (almost entirely
  glue — the real work lives in sub-parts).
