---
name: vdbe/opcodes-agg
---

# Part: vdbe/opcodes-agg

Aggregate lifecycle opcodes. Per-aggregate accumulators and the
Reset/Step/Final/Value protocol. This family is a thin shell over
`VdbeState`'s aggregate methods; the per-kind logic (NULL skip,
running totals, distinct sets, finalization shape) lives inside
`state.aggregate_*` per `/parts/vdbe/shapes.json`. Declarations
live in `shapes.json`; this file carries only semantic intent.

## Semantic contract

Every opcode returns `OpcodeOutcome::Continue` on the happy path.
No jumps, no halts. The only fault mode is a well-formedness
violation (out-of-range register), which is unreachable in a
compiler-vetted Program; targets surface it as
`Halt(Error(OpcodeIllegal))` only via their bounds-check layer.

### `AggReset { acc_slot, kind }`

Call `state.aggregate_reset(acc_slot, kind)`. `Continue`.

Pin the kind to this slot until the next Reset. Reset is
idempotent — resetting an active slot discards in-flight state
(intended: outer scan re-enters a subquery aggregate).

### `AggStep { acc_slot, kind, arg_reg, separator_reg }`

1. `arg = state.get_register(arg_reg)` (borrow).
2. `sep = separator_reg.map(|r| state.get_register(r))` (borrow or
   None).
3. `state.aggregate_step(acc_slot, kind, arg, sep)`.
4. `Continue`.

The NULL-skip rule lives in `state.aggregate_step`: for any kind
except `CountStar`, a `Value::Null` argument is ignored. The
opcode does not branch on value kind.

For non-`GroupConcat` kinds, `separator_reg` is structurally
always `None` (compiler never emits it); the handler still passes
it through. Forwarding `Some` for non-GroupConcat is a compiler
bug, not a runtime fault — state ignores it.

### `AggFinal { acc_slot, kind, dest_reg }`

1. `v = state.aggregate_final(acc_slot, kind)` — owned `Value`.
2. `state.set_register(dest_reg, v)`.
3. `Continue`.

After Final, the slot is semantically consumed. A Step on this
slot before the next Reset is a compiler bug; state's behavior is
implementation-defined (panic or undefined value). The spec does
not rely on it.

### `AggValue { acc_slot, kind, dest_reg }`

1. `v = state.aggregate_value(acc_slot, kind)` — owned `Value`,
   read-only on the accumulator.
2. `state.set_register(dest_reg, v)`.
3. `Continue`.

Value is non-destructive — further Step calls on this slot
continue to accumulate. Used by `opcodes-window` for per-row reads
of `SUM() OVER (...)` etc. and by HAVING after group close.

## Invariants

- `acc_slot` is in `[0, state.num_aggregates)` (compiler
  guarantee; not re-checked here).
- `arg_reg`, `dest_reg`, `separator_reg` are in
  `[0, state.num_registers)`.
- Protocol ordering: `Reset → Step* → (Final | Value* → Final)`.
  The compiler enforces; the opcode does not verify.

## Correctness pins

Load-bearing rules the emission MUST satisfy.

1. Every opcode is a thin shell over `state.aggregate_*`. Do NOT
   replicate per-kind accumulator logic in the opcode body. NULL
   skip, running-total updates, distinct-set maintenance, and
   finalization shape live inside `state.aggregate_step` and
   `state.aggregate_final`.
2. `AggStep`: capture the register borrow(s) for `arg_reg` (and
   `separator_reg` if `Some`) BEFORE calling a mut-receiver on
   state. The live-borrow + mut-receiver conflict is a strict-
   borrow-target (Rust) constraint; non-borrow-checked targets
   follow the same ordering for source parallelism. In Rust
   specifically, `state.get_register(r)` returns `&Value`; that
   borrow is incompatible with `&mut state.aggregate_step(...)`,
   so bind `let arg = state.get_register(arg_reg);` and then
   call `state.aggregate_step(slot, kind, arg, sep)` — the
   borrow ends at the call's argument evaluation boundary,
   which the borrow checker accepts.
3. `AggFinal` and `AggValue`: the returned `Value` is OWNED. Pass
   directly to `state.set_register(dest_reg, v)` — no clone, no
   temporary.
4. No kind-branching in opcode: the kind is forwarded to state.
   State does the `match kind { ... }` internally. This keeps the
   opcode body constant-size in the number of aggregate kinds; adding
   a new aggregate = extending `AggFuncKind` + state, not patching
   the opcode family.
5. No direct access to the accumulator store. `Accumulator` is
   VdbeState's internal shape and is not exported; targets must
   NOT attempt to introspect it.
6. `separator_reg` handling:
   - `None` → pass `None` to `state.aggregate_step`.
   - `Some(r)` → pass `Some(state.get_register(r))`.
   Never synthesize a default ',' in the opcode — the default is
   GroupConcat's responsibility inside state.
7. All four opcodes return `Continue` unconditionally. If a target
   has structural bounds-check macros, they may surface
   `OpcodeIllegal`; otherwise the signature contract is
   `Continue`.

## Storage interaction surface

None. This family does not call storage. All state mutation is
through `VdbeState` methods declared in `/parts/vdbe/shapes.json`.

## Regeneration envelope

- Spec (this file): < 200 lines.
- `shapes.json`: < 70 lines.
- Each target emission: 100-220 lines. The shell-over-state-methods
  pattern keeps each opcode to ~10-20 lines plus dispatch.
