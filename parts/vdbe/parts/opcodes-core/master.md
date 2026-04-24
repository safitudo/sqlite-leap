---
name: vdbe/opcodes-core
---

# Part: vdbe/opcodes-core

The foundational VDBE opcode family: program termination, constant
load, register moves and copies, cursor lifecycle, and row
emission. Every other opcode family assumes these work. Shape
declarations live in `shapes.json`; this file carries only
semantic intent.

## Semantic contract

Each handler returns an `OpcodeOutcome`. The handler does not touch
the program counter directly — it yields `Continue`, `Halt`, or
`EmitRow`, and the outer VDBE loop interprets.

### `Halt`

Unconditional termination with normal status. Return
`Halt(HaltStatus::Ok)`.

### `LoadConst { dest_reg, value }`

Write a (cloned) copy of `value` into register `dest_reg`,
releasing any prior payload at that slot. Return `Continue`.

Ownership: the `value` carried by the opcode is owned. The register
receives an owned clone. Text/Blob payloads cross a real allocation
boundary.

### `Move { src_reg, dest_reg }`

Move the value out of `src_reg` into `dest_reg`. After execution
`src_reg` holds `Value::Null`. Return `Continue`.

Implementation must use the `take_register` primitive (declared on
`VdbeState`) so Text/Blob payloads transfer without cloning:

```
if src_reg == dest_reg:
    state.set_register(src_reg, Value::Null)
else:
    let v = state.take_register(src_reg)   # src becomes Null
    state.set_register(dest_reg, v)        # dest receives the moved payload
```

The `src_reg == dest_reg` branch is load-bearing — without it,
`take_register` would write Null into the slot and `set_register`
would immediately overwrite with the taken value, leaving the slot
non-Null and violating the "becomes Null" invariant.

### `Copy { src_reg, dest_reg }`

Clone the value from `src_reg` into `dest_reg`. `src_reg` unchanged.
Return `Continue`.

Edge case: if `src_reg == dest_reg`, no-op — skip the clone.

### `OpenRead { cursor, table }` / `OpenWrite { cursor, table }`

Ask the storage subsystem to open a (read-only | writable) cursor
on the named `table`. On success, install the returned cursor
handle at slot `cursor`, releasing any prior handle at that slot
("replace silently" — the compiler is responsible for a prior
`Close` when replacement is undesirable). Return `Continue`.

On failure:
- `TableNotFound` propagates as
  `Halt(HaltStatus::Error(RuntimeCondition::TableNotFound))`.
- Any other storage condition propagates as
  `Halt(HaltStatus::Error(RuntimeCondition::IoError))` — v2 does not
  pass finer-grained storage diagnostics through the VDBE boundary.

The `table` field is a borrowed string slice over the compiled
Program's source buffer. It does not outlive the Program.

### `Close { cursor }`

Release the cursor handle at slot `cursor`. Implemented as:

```
if let Some(handle) = state.take_cursor(cursor):
    storage.close_cursor(handle)     # consume, release backing resources
# else: slot already empty — no-op (idempotent)
```

Return `Continue`. Each target must route the taken handle into the
`close_cursor` free function declared in `parts/storage/shapes.json`;
this gives C/Zig a deterministic release point and is a no-op body
for GC'd targets.

### `ResultRow { start_reg, count }`

Signal row emission: return
`OpcodeOutcome::EmitRow { start: start_reg, count }`. The outer
loop reads registers `[start_reg .. start_reg + count)`, pushes
them to the caller's row sink, and advances the program counter.

Ill-formedness: `count == 0` is invalid (no rows are emitted
intentionally via `ResultRow`). Return
`Halt(HaltStatus::Error(RuntimeCondition::OpcodeIllegal))`.

## Invariants

- `dest_reg` / `src_reg` / `start_reg` must be in
  `[0, state.num_registers)`. Violation raises
  `RuntimeCondition::OpcodeIllegal`. Should be unreachable in a
  well-formed program.
- `cursor` must be in `[0, state.num_cursors)`. Same enforcement.
- `start_reg + count <= state.num_registers` for `ResultRow`.

## Memory discipline

- `LoadConst` with `Value::Text` or `Value::Blob` embeds an owned
  byte buffer inside the opcode at compile time. Writing into the
  register clones that buffer so the register owns its copy. This
  mirrors the neutral `owned<T>` rule: every crossing of a
  mutation boundary transfers or clones ownership.
- `Move` transfers ownership without clone; the source slot becomes
  `Null`. Use this when the compiler knows the source value is
  consumed exactly once.
- `Copy` clones; both slots end up holding independent owned
  payloads.
- Cursor slots: `OpenRead`/`OpenWrite` install an owned
  `CursorHandle`; the prior handle (if any) is released by the
  `set_cursor` method, matching the replace-on-write rule.

## Well-formedness hooks

The compiler guarantees, and the VDBE assumes:

- Exactly one `Halt` opcode, at the final position of the Program.
- No opcode executes after `Halt` (unreachable code is invalid).
- `ResultRow` reads only initialized registers — a register must
  have been `LoadConst`'d, `Copy`'d, `Move`'d into, or written by a
  row-read opcode (`parts/opcodes-rows/`) before being read.

Violations surface as `RuntimeCondition::OpcodeIllegal`; they
should never occur in code produced by the compiler.

## Regeneration envelope

- Spec (this file): < 200 lines.
- `shapes.json`: < 100 lines.
- Each target emission: ~250–450 lines depending on idiom
  (cursor/storage calls add surface in C relative to Rust).
