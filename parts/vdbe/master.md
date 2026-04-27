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

`Opcode`, `Program`, `RowSink`, `VdbeState.new`, and `execute_program`
are **declared in `shapes.json`** (the `compose`, `record`, `alias`
(with `fn`), `constructors`, and `functions` sections respectively).
The declarations there are authoritative; the notes below summarize
the role of each for readers who stop at the prose.

- **`Opcode`** — `compose` over the seven sibling opcode-family
  types (`OpcodeCore`, `OpcodeRows`, `OpcodeScan`, `OpcodeExpr`,
  `OpcodeAgg`, `OpcodeWindow`, `OpcodeControl`). Flat union, one case
  per family. Dispatch is a single match on the outer tag.

- **`Program`** — `record` carrying the compiled opcode list,
  sizing (registers / cursors / aggregates / windows), and a
  `row_sink` field of type `RowSink`.

- **`RowSink`** — alias to the function type
  `fn(borrow<VdbeState>, Register, u32) -> unit`. Callback invoked
  on each `EmitRow` outcome; it reads `state.get_register(start + i)`
  for `i in [0, count)` to observe the emitted row and MUST NOT
  mutate `state`. Each target picks the idiomatic callable form:
  bare function pointer (Rust/C/Zig), function value (Go), callable
  object (Python). Capture / lifetime are the caller's concern.

- **`VdbeState.new(num_registers, num_cursors, num_aggregates,
  num_windows, db)`** — constructor declared under `constructors` in
  `shapes.json`. The only legal way for an external caller to
  materialize a `VdbeState`. Internal state is initialized per
  §"VdbeState implementation".

- **`execute_program(program: &Program, state: &mut VdbeState)
  -> HaltStatus`** — canonical signature, pinned in `shapes.json`.
  Caller constructs `state` first; `execute_program` does NOT own
  the `Database` or the state. This is what lets the cross-target
  equivalence harness warm-replay programs and keeps state
  lifetime in the caller. Loop body is the pseudo-code in
  §Execution loop above.

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

- `VdbeState.new(num_registers, num_cursors, num_aggregates,
  num_windows, db)` — constructor declared in `shapes.json` under
  `constructors.VdbeState`. Initializes all slots per §"VdbeState
  implementation". `row_sink` is NOT passed here; it lives on
  `Program`.
- `execute_program(program: &Program, state: &mut VdbeState)
  -> HaltStatus` — declared in `shapes.json` under `functions`.
  Runs the loop in §"Execution loop" to completion or halt,
  returns the final status. Caller owns the `VdbeState` lifetime.

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

13. **Canonical `execute_program` signature**
    `(program: &Program, state: &mut VdbeState) -> HaltStatus`.
    The caller constructs the `VdbeState` via `VdbeState.new` and
    passes it in. This emission MUST NOT construct the state
    internally nor accept a `Database` in place of a state —
    doing so breaks the cross-target equivalence harness (which
    warm-reuses state across replays) and forks the signature per
    target. Declared in `shapes.json`.

14. **Canonical `VdbeState.new` signature**
    `(num_registers: u32, num_cursors: u32, num_aggregates: u32,
    num_windows: u32, db: &Database) -> VdbeState`. Row sink is
    NOT a constructor arg — it travels on `Program`. Declared in
    `shapes.json`.

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

## Pin 18.1c — VdbeState carries `&mut Database`

Pin 18.1c (cross-leaf with `/parts/storage/parts/mem-store`) promotes
`VdbeState`'s database borrow from `&Database` to `&mut Database` so
opcode handlers can reach the Pager via
`Database::split_pager_mut` and pass `&mut Pager` into the now-pin-18.1c
cursor functions (`cursor_rewind`, `cursor_next`, `cursor_column`,
`cursor_insert_row`, `cursor_delete_row`, `cursor_update_row`,
`cursor_seek_rowid`, etc.).

### What changes

- `VdbeState::new` constructor: the `db` parameter changes from
  `borrow Database` to `borrow_mut Database`.
- `VdbeState::db` method: returns `borrow_mut Database` (was `borrow`).
  A read-only `db_ref` companion method is added that returns
  `borrow Database` for opcode handlers (OpenRead/OpenWrite,
  schema lookup) that genuinely don't need mutation.
- `execute_program` function: the `state` parameter is unchanged
  (still `&mut VdbeState`); the borrow inside state propagates the
  upgrade.
- New `VdbeState::cursor_and_pager_mut(c: CursorId)` method: returns
  the disjoint `(&mut CursorHandle, &mut Pager)` pair so opcode
  handlers can hold both borrows simultaneously. Implemented via
  field-destructuring at the VdbeState level (cursor table + db are
  disjoint fields).
- New `VdbeState::pager_mut()` method: returns `&mut Pager` directly
  for opcode handlers that need only the pager (e.g. transaction
  control opcodes that route through `pager_commit_transaction`).

### Why borrow_mut everywhere

Cursor reads (rewind/next/column/seek_rowid) take `&mut Pager` per
the wal-bridge contract — page-cache pin 3 makes LRU touch a mutation,
and the wal-bridge `pager_get_page` signature is `borrow_mut`. There
is no spec-clean path that lets cursor reads hold `&Pager` while the
underlying cache operation is mutable. So VdbeState must hold
`&mut Database` to produce `&mut Pager` for any cursor call.

### VDBE handler call pattern

```
// Read or write a cursor in pin 18.1c style:
let (handle, pager) = state.cursor_and_pager_mut(cursor_id);
let result = cursor_rewind(handle, pager);
```

For cursor_insert_row / cursor_update_row / cursor_delete_row the
shape is identical — pin 18.1c keeps the in-memory row-mutation path
flowing through `MemTable.rows`'s interior mutability (Rc<RefCell<>>
in Rust; equivalent in other targets). The Pager param is structural;
no I/O happens for in-memory mode.

### Numbered Correctness pins (vdbe-side, continued)

**Pin V18c-1.** `VdbeState` holds `db: &mut Database`. Targets that
cannot express borrow-mut as a stored reference (Python, Go) carry
a target-equivalent mutable handle — the contract is that
`state.db().split_pager_mut()` is reachable from any opcode handler.

**Pin V18c-2.** `state.cursor_and_pager_mut(c)` returns disjoint
mutable references to the cursor at slot `c` and the pager. Targets
emit this via field-destructuring (Rust), pointer-pair (C/Zig),
struct-field-access (Go/Python).

**Pin V18c-3.** `state.db()` returns `&mut Database`. A read-only
`state.db_ref()` is provided for opcode handlers that don't need
mutation (cleaner borrow scopes; not required to use, but available).

**Pin V18c-4.** `execute_program(program, state)` is unchanged at the
function-signature level; the upgrade is internal to `VdbeState`.
