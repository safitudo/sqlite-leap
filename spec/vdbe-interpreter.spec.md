# VDBE interpreter — language-neutral execution model

Defines how a VDBE Program (per `spec/vdbe-opcodes.spec.md`) executes against storage to produce a Result.

## Interpreter state

On invocation, the VDBE interpreter receives:

- `program` — the Program to execute (read-only)
- `storage_handle` — a mutable reference to a Database

It initialises:

- `pc` (program counter): `0`
- `registers`: an array of length `program.num_registers`, each cell initialised to NULL
- `cursors`: an array of length `program.num_cursors`, each slot initially **closed**
- `result_rows`: an empty ordered list

## Main loop

The interpreter repeats:

1. Let `op := program.opcodes[pc]`.
2. Execute `op` according to its operational semantics in `spec/vdbe-opcodes.spec.md`.
3. If the execution of `op` raised a `STORAGE_*` error, terminate the interpreter and return that error verbatim (same `name`, same `fields`).
4. If `op.op == "Halt"`, terminate successfully and return `{"rows": result_rows}`.
5. Otherwise, the opcode's semantics has already updated `pc` (either advanced by 1 or assigned to a jump target); go to step 1.

A well-formed program (per `spec/vdbe-opcodes.spec.md` § "Well-formedness") is guaranteed to reach `Halt` because:

- `Halt` is the last opcode and is reachable by falling off any non-looping instruction.
- The only backward jumps are `Next.jump_if_more`, which fires iff the cursor was able to advance to a valid row. A cursor over a finite table will eventually stop advancing and fall through.

## Cursor lifecycle

Each cursor slot transitions between three states:

- **closed** — initial state; no associated table. Using the slot with anything other than `OpenRead` / `OpenWrite` is undefined (compiler bug).
- **open, unpositioned** — after `OpenRead` / `OpenWrite` succeeded, before `Rewind`, or after `Rewind` jumped (table was empty). Using the slot with `Column` / `Next` is undefined (compiler bug).
- **open, positioned on row i** — after `Rewind` (then i=0) or after `Next` set `jump_if_more` (then i incremented).
- **open, past-end** — after `Next` fell through. Using `Column` on past-end is undefined (compiler bug).

`Close` returns any open state to closed. After `Halt`, all cursors are closed by implicit cleanup (target-defined; not observable to tests).

## Register lifecycle

Registers are initialised to NULL at interpreter start. `LoadConst` and `Column` write values into registers. `ResultRow` and `InsertRow` read consecutive registers. Out-of-bounds register access is a compiler bug caught by well-formedness.

## Result emission

`ResultRow` appends one Row (a list of Values, in register order) to `result_rows`. On `Halt`, the interpreter returns `{"rows": result_rows}` — a Result conforming to `schema/result.schema.json`.

A program with no `ResultRow` opcodes on its taken path (e.g. a CREATE TABLE program, an INSERT program, or a SELECT of an empty table with the Rewind short-circuiting past the body) yields `{"rows": []}`. This matches the Phase 2a semantic "CREATE/INSERT return `{rows: []}`; empty-table SELECT returns `{rows: []}`".

## Error propagation

Any `STORAGE_*` error raised by an opcode (via a call into the storage part) terminates the interpreter. The error's `name` and `fields` are returned verbatim; the VDBE does NOT wrap, tag, or annotate them. This preserves Phase 2a's test guarantees.

## Implementation freedom

Dispatch strategy is target-defined — a switch / match statement over the `op` field, a function-pointer or trait-object table, a computed-goto implementation, or threaded dispatch. All are valid; Phase 2b does not benchmark dispatch. Phase 3's benchmark harness will.

The interpreter's internal state representation is target-defined. Registers MAY be boxed or unboxed, cursor slots MAY be a stack-allocated array or a heap vector, `result_rows` MAY accumulate into a list or a chunked buffer. None of this is observable to tests.

## Target-defined conditions

Allocator failure, stack overflow, or any other host-OS condition is target-defined and is NOT assigned a `STORAGE_*` name. Phase 2b tests do not exercise these.

## Test authority

The interpreter's observable behaviour is pinned by:

- `tests/cross-build/phase2a.json` (via the updated executor part; full behavioural regression)
- `tests/cross-build/phase2b.json` (direct compiler + vdbe invocation; VDBE-specific smoke tests and structural invariants)

If this document and those tests disagree, the tests win.
