---
name: core
---

# Part: core

Shared primitive types every other part depends on. This part has
no outbound dependencies beyond the neutral type system. Shape
declarations live entirely in `shapes.json`; this file carries
**only semantic intent** — no code in any target language.

## What this part owns

Six types, documented by role rather than structure (see
`shapes.json` for canonical shape):

### `Register` / `CursorId`

Opaque integer handles naming a slot in the VDBE's register file or
cursor array. They are nominally distinct: the compiler must not
pass a `Register` where a `CursorId` is expected. Targets may
represent both as a machine integer of identical width; the
nominal distinction is enforced by the type name, not a tag.

Range: any valid value is in `[0, num_registers)` or
`[0, num_cursors)` respectively, for a given compiled Program.
Bounds are validated by the compiler and asserted by the VDBE.

### `Value`

The runtime value that flows through registers, cursor reads, and
row emission. Five cases — SQL's native type spread plus NULL:

- `Null` — SQL NULL. Propagates through most binary operators.
- `Integer` — 64-bit signed integer.
- `Real` — IEEE-754 double-precision float.
- `Text` — owned UTF-8 string.
- `Blob` — owned byte sequence.

Text and Blob are **owned** at this level: when a Value crosses a
row-emission boundary or is stored in a register for later use, it
must carry its own buffer. Sub-parts that briefly borrow a payload
for a single call (e.g., to pass it into a scalar function) may do
so, but the borrow must not outlive the enclosing function.

### `OpcodeOutcome`

The result of executing a single opcode. Four cases:

- `Continue` — advance the program counter by 1 and execute the
  next opcode.
- `Jump(target)` — set the program counter to `target` and continue.
- `Halt(HaltStatus)` — stop execution with the given status. The
  VDBE loop exits after this.
- `EmitRow { start, count }` — tell the outer VDBE loop to
  materialize a row from registers `[start .. start+count)`. Also
  advances the program counter by 1 (same as `Continue` except for
  the row emission side effect).

Every opcode handler returns an `OpcodeOutcome`. The outer loop is
thin: it dispatches on the opcode, inspects the outcome, and either
advances, jumps, halts, or yields a row.

### `HaltStatus`

Why execution stopped:

- `Ok` — normal completion. The final "Halt" opcode reached, or
  the program naturally fell off its end.
- `Error(RuntimeCondition)` — a runtime fault. The condition
  identifies which category of fault occurred.

### `RuntimeCondition`

The closed set of runtime faults. Every target must enumerate these
in the same order so error diagnostics are comparable. The set is
deliberately small — fine-grained storage diagnostics do not reach
the VDBE-facing surface in v2.

Meaning of each condition (authoritative):

- `OpcodeIllegal` — a Program violated a well-formedness invariant
  (bad register index, unknown opcode kind, return-stack overflow,
  etc.). Should be unreachable if the compiler validated the Program.
- `CursorClosed` — an opcode touched a cursor slot that was not
  open, or that was exhausted (past-end).
- `CursorNotWritable` — a write-path opcode targeted a read-only
  cursor.
- `TableNotFound` — `OpenRead` / `OpenWrite` named a missing table
  or index.
- `TypeMismatch` — operand type invalid for the opcode (e.g., a
  non-numeric value reached integer arithmetic without affinity
  coercion).
- `ArithOverflow` — integer arithmetic overflowed beyond what
  promotion to Real can cover.
- `DivZero` — division by zero. NOTE: SQLite's default semantics
  coerce this to `Value::Null` at the expression level; this
  condition exists for diagnostic paths that prefer error.
- `ConstraintNotNull` / `ConstraintUnique` / `ConstraintCheck` —
  table constraint violations surfaced during row mutation.
- `ConstraintType` — STRICT-table affinity violation.
- `RecursiveCteLimit` — a recursive CTE exceeded its iteration
  bound.
- `SubqueryMoreThanOneRow` — a scalar subquery returned more than
  one row where at most one was expected.
- `IoError` — any storage / pager / WAL / allocator failure. In v2
  this is the catch-all for resource-level faults; OOM is reported
  here rather than as a distinct condition.

## Cross-target semantic rules

### Ownership

`Value::Text` and `Value::Blob` carry owned payloads. When the
caller **moves** a Value into another place, the receiver takes
ownership. When the caller **borrows** a Value (read-only access
for the duration of a call), the owner retains responsibility.

The target mappings render this mechanically:

- In a language with ownership in the type system, `owned` is the
  default and move/borrow are tracked automatically.
- In a language without ownership in the type system, the mapping
  introduces explicit clone and release functions and requires
  their discipline.

No sub-part author writes clone/release calls in `shapes.json`
directly; they live in per-target emission rules.

### Replace-on-write

Any operation that overwrites a `Value` slot must first release
whatever payload was there. Target mappings handle this — Rust via
the move-assign drop, C via an explicit release call before
assignment. Sub-part authors never handle it explicitly.

### OOM

Allocator failures surface as `RuntimeCondition::IoError` where a
`Result`-returning function is available. Where no such channel
exists (e.g., a small constant allocation during opcode dispatch),
the target mapping may abort; OOM on trivial paths is not a
recovery scenario.

## Regeneration envelope

- Spec (this file): < 300 lines.
- `shapes.json`: < 100 lines.
- Each target emission (core.rs, core.h + core.c): ~100–200 lines.
