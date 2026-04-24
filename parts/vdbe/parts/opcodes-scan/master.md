---
name: vdbe/opcodes-scan
---

# Part: vdbe/opcodes-scan

Index-driven scan opcodes. The non-index scan is just
`Rewind`+`Next` on a table cursor (lives in
`parts/opcodes-rows/`). This sub-part owns the index-cursor
primitives: open, four-way seek, next-walk, and rowid read. Shape
declarations live in `shapes.json`; this file carries only semantic
intent.

## Semantic contract

Each handler returns an `OpcodeOutcome`. Possible outcomes in this
family: `Continue`, `Jump(target)`, or `Halt(status)`. The handler
does not touch the program counter directly.

### `OpenIdxRead { cursor, index_name }`

Ask the storage subsystem to open a read-only cursor on the named
index via `storage.open_index_cursor(db, index_name)`. On success,
install the returned handle at slot `cursor` (replace silently — the
compiler is responsible for a prior `Close` when replacement is
undesirable). Return `Continue`.

On failure:
- `TableNotFound` propagates as
  `Halt(HaltStatus::Error(RuntimeCondition::TableNotFound))`.
- Any other storage condition collapses to
  `Halt(HaltStatus::Error(RuntimeCondition::IoError))`, matching the
  VDBE-boundary rule established by `OpenRead`/`OpenWrite` in
  `parts/opcodes-core/`.

The `index_name` field is a borrowed string slice over the compiled
Program's source buffer. It does not outlive the Program.

### `SeekGE { cursor, key_reg, jump_if_miss }`

Read the probe key from `regs[key_reg]` (borrow, not take) and call
`storage.cursor_seek_ge(cursor, key)`. Outcomes:

- `Ok(true)` — entry found; cursor is now positioned at the smallest
  key ≥ the probe → `Continue`.
- `Ok(false)` — no such entry (all keys are strictly less) →
  `Jump(jump_if_miss)`.
- `Err(cond)` — collapse to `Halt(HaltStatus::Error(cond))`; the
  storage layer is responsible for mapping its internal conditions
  to the VDBE-facing set.

Register-bounds violation (`key_reg >= state.num_registers`) is
unreachable in a well-formed Program and surfaces as
`Halt(Error(OpcodeIllegal))`.

### `SeekGT { cursor, key_reg, jump_if_miss }`

Same as `SeekGE` with a strict `>` comparator
(`storage.cursor_seek_gt`).

### `SeekLE { cursor, key_reg, jump_if_miss }`

Mirror of `SeekGE` below the probe — `storage.cursor_seek_le`
positions at the largest key `≤ probe`. `Ok(false)` means all keys
are strictly greater → `Jump(jump_if_miss)`.

### `SeekLT { cursor, key_reg, jump_if_miss }`

Same as `SeekLE` with strict `<` comparator
(`storage.cursor_seek_lt`).

### `IdxNext { cursor, jump_if_more }`

Call `storage.cursor_idx_next(cursor)` to advance one index entry.

- `Ok(true)` — another entry exists and the cursor has moved onto it
  → `Jump(jump_if_more)`. This "jump on HAS-NEXT" convention matches
  `Next`/`Prev` in `parts/opcodes-rows/`: the loop body lives at
  `jump_if_more` and the fall-through path is the post-loop
  continuation.
- `Ok(false)` — past-end → `Continue`.
- `Err(cond)` → `Halt(Error(cond))`.

### `IdxRowid { cursor, dest_reg }`

Call `storage.cursor_idx_rowid(cursor)` and install the returned
`i64` into `regs[dest_reg]` as `Value::Integer`.

- `Ok(rowid)` → `state.set_register(dest_reg, Value::Integer(rowid))`,
  `Continue`.
- `Err(CursorClosed)` → `Halt(Error(CursorClosed))` — the cursor is
  at EOF/BOF or has been closed.
- Any other `Err(cond)` → `Halt(Error(cond))`.

## Invariants

- `cursor` must be in `[0, state.num_cursors)` and must point to an
  open index cursor. Violation raises `OpcodeIllegal`; unreachable
  in well-formed code.
- `key_reg`, `dest_reg` must be in `[0, state.num_registers)`.
- `jump_if_miss` / `jump_if_more` must be a valid PC within the
  Program. Compiler guarantees.

## Empty-slot handling

`Seek*`, `IdxNext`, and `IdxRowid` require the cursor slot to be
populated before they run. If the slot is empty (nothing opened, or
a prior `Close` on this cursor id), the outcome is
`Halt(HaltStatus::Error(RuntimeCondition::CursorClosed))`. In
targets that use `cursor_borrow` / `cursor_mut`, this maps naturally
from their panic-on-empty-slot contract: the handler checks
`state.cursor_is_open(c)` first and returns the Halt outcome if
false. Unreachable in a well-formed Program.

## Cursor access pattern

For read-only calls into storage (`cursor_idx_rowid`), use
`state.cursor_borrow(c)`. For mutating calls (`cursor_seek_*`,
`cursor_idx_next`), use `state.cursor_mut(c)`. Do NOT use
`take_cursor` + `set_cursor` around storage calls in this family —
the accessors exist precisely so handlers don't reinstall. The
probe-key read uses `state.get_register(key_reg)` (borrow), which
may need to be captured into a local before `cursor_mut` is
invoked, since `cursor_mut` is a mutable receiver borrow that
conflicts with a live register borrow in strict-borrow targets
(Rust). A local clone of the probe key is acceptable (keys are
typically `Integer`/`Real`).

## Storage interaction surface

This family calls (all declared in `/parts/storage/shapes.json`):

- `open_index_cursor(db, index_name) -> Result<CursorHandle, RuntimeCondition>`
- `cursor_seek_ge(cursor, key: &Value) -> Result<bool, RuntimeCondition>`
- `cursor_seek_gt / cursor_seek_le / cursor_seek_lt` — same shape
- `cursor_idx_next(cursor) -> Result<bool, RuntimeCondition>`
- `cursor_idx_rowid(cursor) -> Result<i64, RuntimeCondition>`

Probe-key read uses `state.get_register(key_reg)` (borrow); the
storage function receives `&Value` — no clone, no take.

## Regeneration envelope

- Spec (this file): < 150 lines.
- `shapes.json`: < 100 lines.
- Each target emission: ~250-450 lines. Seek is four-way but share
  the same shape; idiomatic emissions collapse the four arms into a
  single dispatch.
