---
name: vdbe/opcodes-window
---

# Part: vdbe/opcodes-window

Window-function execution. Row-number counter, rank/dense-rank,
and aggregate-as-window output. Thin shell over `VdbeState`'s
`window_*` methods; the per-kind logic (counter advancement, tie
detection, partition-key storage, inner aggregate forwarding) lives
inside state.

## Semantic contract

All opcodes return `OpcodeOutcome::Continue` on success. No jumps,
no halts. None emit rows directly — window output flows through
`WindowValue → regs[dest_reg] → projection`.

### `WindowOpen { slot, kind, n_partition_keys, n_order_keys }`

Call `state.window_open(slot, kind, n_partition_keys,
n_order_keys)`. `Continue`.

Kind is pinned to this slot for its lifetime:
- `RowNumber` — integer counter, 1-based, reset per partition.
- `Rank` — integer counter with gap-after-tie (1, 2, 2, 4, ...).
- `DenseRank` — gapless tie counter (1, 2, 2, 3, ...).
- `Aggregate(k)` — allocate an inner accumulator of kind `k`; act
  as a "running aggregate" emitted per row.

Partition management is external: the compiler emits
`WindowClose(slot); WindowOpen(slot, ...)` across partition
boundaries based on `WindowPartitionKey` comparisons.

### `WindowStep { slot, arg_reg }`

Call `state.window_step(slot, arg_reg)`. `Continue`.

State reads regs[arg_reg] internally when `Some` — the opcode
forwards the index, not a borrow. Per-kind behavior inside state:

- rank-style (`arg_reg == None`): counter advance per-kind —
  RowNumber always +1; Rank/DenseRank compares current ORDER BY
  tuple to previous.
- Aggregate kinds (`arg_reg == Some(r)`): the value at `regs[r]`
  feeds the inner aggregate step.

The compiler-enforced shape rule: for rank kinds, `arg_reg` is
always `None`; for Aggregate kinds, `arg_reg` is `Some` (except
where the aggregate takes no argument, e.g. `COUNT(*) OVER (...)`,
where the compiler may emit `None` and state's aggregate
implementation accepts it as a CountStar increment).

### `WindowValue { slot, dest_reg }`

1. `v = state.window_value(slot)` — owned `Value`.
2. `state.set_register(dest_reg, v)`.
3. `Continue`.

Read-only on the window session — further Step calls still
advance.

### `WindowPartitionKey { slot, key_idx, dest_reg }`

1. `v = state.window_partition_key(slot, key_idx)` — owned
   `Value` (clone from session-stored key tuple).
2. `state.set_register(dest_reg, v)`.
3. `Continue`.

Used by the outer scan: at each row, compare the incoming
partition-key tuple against the session's stored tuple; on
inequality, close + reopen.

### `WindowClose { slot }`

Call `state.window_close(slot)`. `Continue`. Idempotent.

## Frame clauses

`ROWS BETWEEN ...`, `RANGE BETWEEN ...`, `GROUPS BETWEEN ...` are
out of scope for v2. The compiler rejects frame specs at compile
time; this runtime family never sees one. Adding frame support
extends `WindowKind` and `state.window_open`'s signature without
changing this opcode shape.

## Invariants

- `slot` is in `[0, state.num_windows)` (compiler guarantee).
- `key_idx < n_order_keys` + `n_partition_keys` stored in the
  session at `WindowOpen`.
- `arg_reg`, `dest_reg` in `[0, state.num_registers)`.
- Protocol: `Open → (Step* [Value | PartitionKey]*)* → Close`.

## Correctness pins

Load-bearing rules the emission MUST satisfy.

1. Every opcode is a thin shell over `state.window_*`. Do NOT
   replicate rank counter logic, tie detection, or aggregate
   forwarding in the opcode body.
2. `WindowStep`: forward `arg_reg: option<Register>` directly to
   `state.window_step` — the opcode MUST NOT call
   `state.get_register(r)` to produce a `&Value`. State reads the
   register internally. (Rationale: passing `&Value` into a
   mut-receiver method collides with the register file's live
   borrow in strict-borrow targets; index-forwarding is
   target-neutral. Same rule as `AggStep`.)
3. `WindowValue` and `WindowPartitionKey`: the returned `Value` is
   OWNED. Install directly via `state.set_register(dest_reg, v)`.
4. No kind-branching on the opcode side. `WindowKind` is passed
   opaquely to `state.window_open`. State does the internal
   match. Adding a window-function kind = extending `WindowKind` +
   state, not patching this family.
5. `WindowStep` with `arg_reg == None` and `arg_reg == Some(_)`
   MUST both route through `state.window_step(slot, arg_reg:
   option<Register>)` — do NOT emit two separate state methods.
   The option parameter carries the "no-argument" signal; state
   dereferences the register internally when `Some`.
6. `WindowClose` is idempotent. Do not guard it with
   `state.is_open(slot)` — state internally tracks the
   empty-slot state.
7. All five opcodes return `Continue` unconditionally on the
   happy path. No `Jump` or `Halt` emitted by this family.

## Storage interaction surface

None.

## Regeneration envelope

- Spec (this file): < 200 lines.
- `shapes.json`: < 70 lines.
- Each target emission: 100-200 lines.
