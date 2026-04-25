---
name: vdbe/opcodes-rows
---

# Part: vdbe/opcodes-rows

Row-level table-cursor opcodes: positional walk, column read, and
row mutation. Non-index scan lives here (`Rewind`/`Next`/`Prev` on a
table cursor); index-driven scan lives in `parts/opcodes-scan/`.
Shape declarations live in `shapes.json`; this file carries only
semantic intent.

## Semantic contract

Each handler returns an `OpcodeOutcome`. Possible outcomes: `Continue`,
`Jump(target)`, `Halt(status)`. Handlers never touch the program
counter directly. All opcodes require the named cursor slot to be
open; empty-slot is ill-formed and returns
`Halt(Error(CursorClosed))`.

### `Rewind { cursor, jump_if_empty }`

Call `storage.cursor_rewind(cursor)`. On `Ok(true)` (at least one
row): `Continue` with the cursor on row 1. On `Ok(false)` (empty
table): `Jump(jump_if_empty)` — skip the scan loop body.
`Err(cond)` → `Halt(Error(cond))`.

### `Next { cursor, jump_if_more }`

Call `storage.cursor_next(cursor)`. `Ok(true)` → `Jump(jump_if_more)`
(re-enter the loop body). `Ok(false)` → `Continue` (fall through
past-end). `Err(cond)` → `Halt(Error(cond))`. Jump-on-has-next
convention; mirrors `IdxNext` in opcodes-scan.

### `Prev { cursor, jump_if_more }`

Mirror of `Next` via `storage.cursor_prev`. Same Jump/Continue rules.

### `SeekRowid { cursor, rowid_reg, jump_if_miss }`

Read `regs[rowid_reg]`; it MUST be `Value::Integer`. If it is any
other type: `Halt(Error(TypeMismatch))`. Otherwise call
`storage.cursor_seek_rowid(cursor, rowid)`. `Ok(true)` → `Continue`
(cursor is on the row). `Ok(false)` → `Jump(jump_if_miss)` (row not
found). `Err(cond)` → `Halt(Error(cond))`.

### `Column { cursor, col_idx, dest_reg }`

Call `storage.cursor_column(cursor, col_idx)`. On `Ok(value)` —
`value` is OWNED per the storage column-ownership rule — install
via `state.set_register(dest_reg, value)`. Return `Continue`.
`Err(cond)` → `Halt(Error(cond))` (Covers EOF/BOF as
`Err(CursorClosed)`).

### `InsertRow { cursor, column_names, start_reg, count }`

Collect the values from `regs[start_reg .. start_reg + count]` as a
list of borrows (`&Value`). Call
`storage.cursor_insert_row(cursor, column_names.as_deref(), &values)`.
On `Ok(_rowid)` → `Continue` (rowid is discarded here; if the caller
wants it they request a `RETURNING`-flavored opcode, out of scope
for this family). `Err(cond)` → `Halt(Error(cond))` — constraint
violations, `CursorNotWritable`, etc.

### `UpdateRow { cursor, column_names, start_reg, count }`

Same pattern as `InsertRow` but through
`storage.cursor_update_row`. `column_names` is a borrowed slice of
borrowed column-name strings (already deduplicated by the compiler).

### `DeleteRow { cursor }`

Call `storage.cursor_delete_row(cursor)`. On `Ok(())` → `Continue`.
`Err(cond)` → `Halt(Error(cond))`. The cursor is left positioned so
the next `Next` returns the row that followed the deleted one.

### Row buffer ops (ORDER BY / DISTINCT support)

Row buffers are an in-memory list-of-rows resource managed by
`VdbeState` and addressed by `buffer_slot: u32`. Each slot stores
homogeneous rows (every row has the same `num_cols`) plus an internal
read cursor used by `BufferRewind` / `BufferRead` / `BufferNext`.

State exposes the following methods (declared in `parts/vdbe/shapes.json`
under `VdbeState`):

- `state.buffer_open(slot, num_cols)` — open or reset the slot to an
  empty buffer of the given width.
- `state.buffer_append(slot, &[Value])` — push one row.
- `state.buffer_sort(slot, key_indices, key_desc)` — in-place sort.
- `state.buffer_dedup(slot)` — collapse adjacent duplicates.
- `state.buffer_rewind(slot) -> bool` — `true` if the buffer has at
  least one row (cursor at row 0); `false` if empty.
- `state.buffer_read(slot, dest_first_reg, num_cols)` — copy the
  current row into the register window.
- `state.buffer_next(slot) -> bool` — advance; `true` if another row
  is now positioned; `false` if past end.

### `BufferOpen { buffer_slot, num_cols }`

`state.buffer_open(buffer_slot, num_cols)`. `Continue`. Idempotent —
a re-open clears any prior content.

### `BufferAppend { buffer_slot, first_reg, num_cols }`

Read `regs[first_reg .. first_reg + num_cols]`, snapshot each value,
hand the row vector to `state.buffer_append(buffer_slot, &snapshot)`.
`Continue`. Borrow-ordering note: take owned snapshots before any
state mutation, identical to the `InsertRow` discipline (pin #6).

### `BufferSort { buffer_slot, key_indices, key_desc }`

`state.buffer_sort(buffer_slot, key_indices, key_desc)`. The SQLite
canonical total order applies (rank: Null=0, Integer/Real=1,
Text=2, Blob=3; within ranks numeric / memcmp). Stable sort
preserves equal-key insertion order. `Continue`.

### `BufferDedup { buffer_slot }`

`state.buffer_dedup(buffer_slot)` collapses adjacent rows that compare
equal under the total order. Caller (the SELECT compiler) sorts before
dedup when a full-buffer dedup is required. `Continue`.

### `BufferRewind { buffer_slot, end_pc }`

`state.buffer_rewind(buffer_slot)` returns `true` for non-empty (cursor
at row 0 → `Continue`) or `false` for empty (`Jump(end_pc)`). Mirrors
table `Rewind`'s "jump on EMPTY" convention.

### `BufferRead { buffer_slot, dest_first_reg, num_cols }`

Copy the current row's values via `state.buffer_read(buffer_slot,
dest_first_reg, num_cols)` — each cell is set with `set_register`,
clones owned. `Continue`. Pre: `BufferRewind` succeeded and `BufferNext`
has not yet returned past-end.

### `BufferNext { buffer_slot, body_pc }`

`state.buffer_next(buffer_slot)` advances; `true` → `Jump(body_pc)`;
`false` → `Continue` (past-end). Matches table `Next`'s jump-on-HAS-NEXT
convention.

## Invariants

- `cursor` is in `[0, state.num_cursors)` and points to an open
  table cursor (compiler guarantee).
- `start_reg + count <= state.num_registers` for Insert/Update.
- `col_idx` is within the current row's column count (storage
  layer enforces).
- Writable vs read-only: compiler MUST have opened the cursor with
  `OpenWrite` before emitting Insert/Update/Delete. Violation
  surfaces from storage as `Err(CursorNotWritable)`.

## Correctness pins

Load-bearing rules the emission MUST satisfy.

1. All opcodes use `state.cursor_mut(c)` for mutating storage
   calls (`cursor_rewind`, `cursor_next`, `cursor_prev`,
   `cursor_seek_rowid`, `cursor_insert_row`, `cursor_update_row`,
   `cursor_delete_row`). `Column` uses `state.cursor_borrow(c)`
   for the read-only `cursor_column` call.
2. Empty-slot guard at entry of every opcode:
   `if !state.cursor_is_open(c) return Halt(Error(CursorClosed))`.
3. `SeekRowid`: read `state.get_register(rowid_reg)`; if it is not
   `Value::Integer` → `Halt(Error(TypeMismatch))`. Capture the i64
   into a local BEFORE calling `state.cursor_mut` (strict-borrow
   targets need the register borrow released first). The integer
   payload is 8 bytes; copy is free.
4. Jump convention:
   - `Rewind`: `Ok(true)` → `Continue`; `Ok(false)` → `Jump(jump_if_empty)`.
   - `Next` / `Prev`: `Ok(true)` → `Jump(jump_if_more)`; `Ok(false)` → `Continue`.
   (Rewind is "jump on EMPTY"; Next/Prev are "jump on HAS-NEXT".
   Asymmetry is intentional — scan-loop codegen relies on it.)
5. `Column`: the storage-returned Value is OWNED. Hand it directly
   to `state.set_register(dest_reg, v)`; no intermediate clone.
6. `InsertRow` / `UpdateRow`: assemble `values` as a list of borrows
   over the register range `[start_reg, start_reg + count)`. In
   strict-borrow targets (Rust), hold the borrows in a `Vec<&Value>`
   built via `(start_reg..start_reg+count).map(|r| state.get_register(r)).collect()`
   BEFORE acquiring `state.cursor_mut(cursor)`. The register
   borrows must expire before the mut-state borrow begins — a
   borrow-ordering constraint, not an ownership constraint.
   (Python/Go/Zig/C have no borrow-checker; they still follow the
   same ordering for source parallelism.)
7. `InsertRow` returns `Ok(rowid)` from storage; the rowid is
   discarded in this opcode. RETURNING-flavored variants live in a
   future family.
8. Storage error propagation: every `Err(cond)` collapses to
   `Halt(Error(cond))` verbatim. No VDBE-boundary remapping; the
   storage layer is responsible for emitting conditions the VDBE
   accepts (`Constraint*`, `CursorNotWritable`, `CursorClosed`,
   `TypeMismatch`, `IoError`).
9. This family does NOT emit rows (`ResultRow` lives in
   opcodes-core). It also does NOT open or close cursors (those
   live in opcodes-core as `OpenRead`/`OpenWrite`/`Close`).

## Regeneration envelope

- Spec (this file): < 250 lines.
- `shapes.json`: < 130 lines.
- Each target emission: 250-450 lines. Insert/Update share the
  value-assembly shape; idiomatic emissions may factor that into a
  small helper.
