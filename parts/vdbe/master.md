---
name: vdbe
kind: inner
shapes: ./shapes.json
emits:
  rust:   { path: src-rust/vdbe/mod.rs }
  c:      { path: src-c/vdbe/mod.c, headers: [src-c/vdbe/mod.h] }
  zig:    { path: src-zig/vdbe/mod.zig }
  go:     { path: src-go/vdbe/vdbe.go }
  python: { path: src-python/leap_sqlite/vdbe/__init__.py }
---

# Part: vdbe

The Virtual Database Engine. Consumes a compiled `Program` and a
mutable `Database` handle, executes opcodes in order driven by a
program counter, and emits rows to the caller's row sink.

This file is the **inner-part composition spec**. It defines:
1. The concrete `VdbeState` implementation (materializing the
   opaque type declared in `shapes.json`).
2. The union `Opcode` variant over the seven sub-part opcode
   families.
3. The outer dispatch + execution loop.
4. The entry point `execute_program`.

Sub-parts (the seven opcode families) are already emitted as
individual leaves — each with its own `OpcodeXxx` variant and
`execute(&op, &mut state)` function. This inner emission composes
them.

## Sub-part map

Opcodes group into seven families:

- `opcodes-core/` — basic: Halt, LoadConst, Move, OpenRead,
  OpenWrite, Close, Copy, ResultRow.
- `opcodes-rows/` — row-level: InsertRow, UpdateRow, DeleteRow,
  Rewind, Next, Prev, SeekRowid, Column.
- `opcodes-scan/` — index/table scan: OpenIdxRead, SeekGE/GT/LE/LT,
  IdxNext, IdxRowid.
- `opcodes-expr/` — expression evaluation: arithmetic, comparison,
  logical, cast, string ops, scalar functions.
- `opcodes-agg/` — aggregate lifecycle: AggReset, AggStep,
  AggFinal, AggValue.
- `opcodes-window/` — window functions: row numbering, rank,
  aggregate-as-window.
- `opcodes-control/` — control flow: Goto, If, IfNot, JumpIfNull,
  Gosub, Return.

Each family declares its own `OpcodeXxx` variant + `execute`
function in its `shapes.json`. This composition emits a union
`Opcode` with one case per family, plus a dispatcher.

## The `Opcode` union

Shape (language-neutral):

```
Opcode {
  Core(OpcodeCore)
  Rows(OpcodeRows)
  Scan(OpcodeScan)
  Expr(OpcodeExpr)
  Agg(OpcodeAgg)
  Window(OpcodeWindow)
  Control(OpcodeControl)
}
```

Each case carries a single value — the family's own opcode variant.
No per-case fields; the family's variant carries them.

## Execution loop

Canonical pseudo-code:

```
fn execute_program(program: &Program, state: &mut VdbeState) -> HaltStatus:
  loop:
    pc = state.pc()
    if pc >= program.opcode_count:
      return HaltStatus::Ok  # falling past end is a clean stop
    op = program.opcodes[pc]
    outcome = dispatch(op, state)
    match outcome:
      Continue           -> state.set_pc(pc + 1)
      Jump(target)       -> state.set_pc(target)
      Halt(status)       -> return status
      EmitRow{start,cnt} -> program.row_sink(state, start, cnt)
                            state.set_pc(pc + 1)
```

`dispatch` is the family selector:

```
fn dispatch(op: &Opcode, state: &mut VdbeState) -> OpcodeOutcome:
  match op:
    Opcode::Core(op)    -> opcodes_core::execute(op, state)
    Opcode::Rows(op)    -> opcodes_rows::execute(op, state)
    Opcode::Scan(op)    -> opcodes_scan::execute(op, state)
    Opcode::Expr(op)    -> opcodes_expr::execute(op, state)
    Opcode::Agg(op)     -> opcodes_agg::execute(op, state)
    Opcode::Window(op)  -> opcodes_window::execute(op, state)
    Opcode::Control(op) -> opcodes_control::execute(op, state)
```

## Composition surface

`Opcode`, `Program`, `RowSink`, and `execute_program` are emitted as
part of this composition. They are not declared in `shapes.json`
because the current shape grammar cannot express function types
(RowSink is a callback); promoting them awaits a shape-schema
extension. Until then, the canonical shapes below are authoritative
and all targets MUST converge on them.

`Opcode` — flat tagged union, one case per family. Cases:

```
Opcode =
  Core(OpcodeCore)       Rows(OpcodeRows)       Scan(OpcodeScan)
  Expr(OpcodeExpr)       Agg(OpcodeAgg)         Window(OpcodeWindow)
  Control(OpcodeControl)
```

Each payload type is owned by the corresponding sub-part; this
composition only wires the outer tag and the dispatch switch.

`Program` — record with these fields (names are canonical; each
target may rename per its convention, but the roles are fixed):

- `opcodes: list<Opcode>` — the bytecode.
- `opcode_count: u32` — `len(opcodes)`; some targets store it
  separately to avoid recomputing at every PC check.
- `num_registers: u32` — sizes the register file at state init.
- `num_cursors: u32` — sizes the cursor slot table.
- `num_aggregates: u32` — sizes the aggregate accumulator table.
- `num_windows: u32` — sizes the window session table.
- `row_sink: RowSink` — user-supplied callback invoked for each
  `EmitRow` outcome.

`RowSink` — callable with signature
`(state: &VdbeState, start_reg: Register, count: u32) -> unit`.
The callback reads `state.get_register(start_reg + i)` for
`i in [0, count)` to observe the emitted row. Must not mutate
`state`. Each target picks the idiomatic callback representation:
bare function pointer, closure trait object, function value,
callable object. Capture/lifetime are the caller's responsibility.

`execute_program` — free function, signature
`(program: &Program, state: &mut VdbeState) -> HaltStatus`.
Loop logic is the pseudo-code in §Execution loop above.

## `VdbeState` implementation

`VdbeState` is declared opaque in `shapes.json`. This emission
materializes it with idiomatic target internals; the method surface
declared in `shapes.json` is the public contract.

Required internal state (all target-private):

- **Register file** — array of `Value`, length `program.num_registers`.
  Assignment releases prior owned payloads. `take_register` moves
  out and installs `Value::Null` in place.
- **Cursor slots** — array of optional `CursorHandle`, length
  `program.num_cursors`. Each slot holds a handle or is empty.
- **Program counter** — `u32` / `PC`.
- **Return stack** — bounded stack of `PC` (depth `RETURN_STACK_MAX_DEPTH`).
  Overflow → `Err(OpcodeIllegal)`.
- **Aggregate slots** — array of accumulator state, length
  `program.num_aggregates`. Per-kind shape:
  - `CountStar`, `Count` — integer counter.
  - `CountDistinct` — integer counter + set of seen values.
  - `Sum`, `Total` — running total (f64) + int-only flag + int running
    total.
  - `Avg` — sum + count.
  - `Min`, `Max` — `Option<Value>` (best seen).
  - `GroupConcat` — string buffer + separator + first-flag.
  - NULL-skip rule: `aggregate_step` ignores `Null` arguments for
    every kind except `CountStar`.
  - Finalization rules per `shapes.json` method doc.
- **Window slots** — array of window-session state, length
  `program.num_windows`. Per-kind:
  - `RowNumber` — integer counter.
  - `Rank` — counter + tied-count tracker.
  - `DenseRank` — gapless counter + previous ORDER BY tuple.
  - `Aggregate(k)` — an inner accumulator of kind `k` (same shapes
    as aggregate slots).
  - Plus a per-session partition-key tuple and order-key tuple.
- **`Database` handle** — borrow held for the duration of the program;
  exposed via `state.db()`.

Internal state is opaque to sub-parts. The declared method surface is
the only interface.

## Entry points (public API from this emission)

- `execute_program(program, db, row_sink) -> HaltStatus` — opens a
  fresh `VdbeState` over `program` + `db`, runs the loop to
  completion or halt, returns the final status.
- `VdbeState` constructor (private to this module but exposed for
  tests in the outer harness) — takes `program` sizing + `db`
  borrow, initializes all slots.

## Well-formedness invariants

The VDBE assumes every Program it receives is well-formed. Violations
(out-of-range register, unknown opcode, return-stack overflow,
bad cursor slot) surface as `Halt(Error(OpcodeIllegal))` without
attempting recovery. The compiler is the well-formedness authority.

## Correctness pins

Load-bearing rules this emission MUST satisfy.

1. **`Opcode` is a flat union** with one case per family. Do NOT
   nest additional classification layers. Dispatch is one `match`
   over the outer tag.

2. **`VdbeState` methods implement the declared `shapes.json`
   surface exactly** — signatures match, semantic contracts
   satisfied. No public methods beyond those declared. Internal
   helpers are private to the emission.

3. **`take_register` leaves `Value::Null`** in the slot; never an
   undefined / sentinel value. This is the Move-without-clone
   primitive that opcodes-core depends on.

4. **`cursor_borrow` / `cursor_mut` panic on empty slot** in
   strict-borrow targets (Rust); non-borrow-checked targets surface
   the equivalent via `assert` or explicit null check that still
   produces a panic / unreachable — because well-formed code never
   triggers it.

5. **`aggregate_step` NULL-skip rule** lives in state, not in the
   opcode: for every kind except `CountStar`, a `Value::Null`
   argument is ignored. Pin Phase 6ai / Phase 6bo.

6. **`aggregate_final` empty-group rules** per `shapes.json`:
   Count* → Integer(0); Sum → Null; Total → Real(0.0); Avg → Null;
   Min/Max → Null; GroupConcat → Null. Pin Phase 6ap / #106.

7. **`window_step` for rank kinds uses ORDER-BY-tuple comparison**
   stored in the session. Rank: tie → same rank + tied-count
   tracker for the next gap. DenseRank: tie → same rank + no gap.
   RowNumber: always +1 regardless of ties.

8. **Execution loop termination**: falling past `program.opcode_count`
   returns `HaltStatus::Ok` (clean end-of-program). `Halt(status)`
   from any opcode returns that status verbatim. No retry, no
   recovery.

9. **`EmitRow` calls the Program's row sink** synchronously, then
   advances the PC. The row sink is a callback closure / function
   pointer supplied by the outer caller.

10. **Ownership of register payloads** is strictly the state's.
    `get_register` returns a borrow; `set_register` takes ownership
    of a `Value`; `take_register` transfers ownership out.

11. **Sub-part emission files are NOT modified** by this emission.
    This composition consumes them unchanged. If a sub-part's
    declared method or opcode shape does not match, it's a spec bug
    and must be fixed at the source, not here.

12. **`RETURN_STACK_MAX_DEPTH = 64`**. Use the declared constant;
    do not invent a different depth.

## Storage dependency

This emission calls `storage.close_cursor` from the `Close` opcode's
backing path (via `state.take_cursor` + handoff), but the actual
`close_cursor` call lives in `opcodes-core`, not here. This
composition does NOT call storage directly; it only owns the state
that cursors live in.

## Regeneration envelope

- Spec (this file): < 350 lines.
- Composed `mod.*` per target: 400-800 lines (VdbeState impl is the
  bulk; ~25 methods × 10-20 lines each, plus Opcode union + dispatch
  ~80 lines + execution loop ~30 lines + constructor ~40 lines).
