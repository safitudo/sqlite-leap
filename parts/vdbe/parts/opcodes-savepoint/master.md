---
name: vdbe/opcodes-savepoint
shapes: ./shapes.json
---

# Part: vdbe/opcodes-savepoint

Three opcodes for nested-transaction control: `Savepoint`,
`ReleaseSavepoint`, `RollbackToSavepoint`. Each delegates to the
storage layer's savepoint stack (see
`/parts/storage/parts/savepoints`); the VDBE itself holds no
savepoint state. Shape declarations live in `shapes.json`; this
file describes only the semantic contract of each opcode.

## Semantic contract

Each opcode below returns an `OpcodeOutcome`. None of these
opcodes mutates registers or cursors; they all act on the storage
layer's savepoint stack and the underlying transaction context.

### `Savepoint { name }`

Push a new savepoint frame named `name` onto the storage
savepoint stack.

- If no transaction is currently open, the storage layer
  IMPLICITLY begins one before pushing the frame (storage pin
  S2).
- If the savepoint stack is at `SAVEPOINT_STACK_MAX_DEPTH`,
  return `Halt(Error(RuntimeCondition::SavepointStackOverflow))`.
- Otherwise return `Continue`.

`name` MAY duplicate an existing entry on the stack; both entries
coexist (LIFO scan resolves to the innermost matching one — see
storage pin S5).

### `ReleaseSavepoint { name }`

Find the OUTERMOST savepoint frame matching `name` (innermost-of-
duplicates by the LIFO rule, but `RELEASE` is the matching scan
that pops "this frame and everything above it" — see storage pin
S5b). Discard that frame and every frame above it. Changes made
under the discarded frames are MERGED into the next-outer frame
(or, if the released frame was the outermost, committed to the
outer transaction; if there is no enclosing explicit transaction,
the implicitly-begun outer transaction commits — storage pin S4).

- If no frame matches `name`, return
  `Halt(Error(RuntimeCondition::SavepointNotFound))`.
- Otherwise return `Continue`.

### `RollbackToSavepoint { name }`

Find the innermost savepoint frame matching `name`. Revert all
storage state (page deltas + schema deltas, storage pin S6) made
since that frame was declared. The frame ITSELF stays on the
stack — a subsequent `RELEASE` or another `ROLLBACK TO` with the
same name still resolves. Any frames DEEPER than the matched one
are discarded (the changes they captured are also reverted as
part of the same revert — they have nowhere to live now).

- If no frame matches `name`, return
  `Halt(Error(RuntimeCondition::SavepointNotFound))`.
- Otherwise return `Continue`.

## Names and case sensitivity

Comparisons are byte-for-byte. The compiler delivers the name as
the parser delivered it; the runtime does not fold case. Two
savepoints whose names differ only in case are distinct frames.

## Stack-depth bound

The savepoint stack has a fixed maximum depth declared by the
storage layer as `SAVEPOINT_STACK_MAX_DEPTH` (storage pin S7).
Exceeding it raises `RuntimeCondition::SavepointStackOverflow`.
The bound exists to keep recovery / replay deterministic and to
cap memory growth from unbalanced `SAVEPOINT` without matching
`RELEASE`.

## Interaction with WAL / pager

Page-level revert is not the opcode's concern; the storage
savepoint layer (`/parts/storage/parts/savepoints`) owns the
journal-frame discipline. The opcode handler simply calls into
that layer's `push_savepoint` / `release_savepoint` /
`rollback_to_savepoint` operations and translates their result
into an `OpcodeOutcome`.

## Correctness pins

**O1. Three opcodes, no more.** This part declares exactly
`Savepoint`, `ReleaseSavepoint`, `RollbackToSavepoint`. Bare
`BEGIN` / `COMMIT` / `ROLLBACK` belong to a separate
`opcodes-transaction` part (out of scope here).

**O2. Names are owned strings.** Each opcode payload owns its
`name` (no borrow into the source program). Programs may be
serialized; borrows would dangle.

**O3. Implicit-begin on Savepoint.** If the VDBE state is in
"no transaction" when `Savepoint` runs, the storage layer
silently begins a transaction. The opcode does not return any
indication that this happened — the caller is unaware.

**O4. Release-by-name pops a contiguous suffix.** `ReleaseSavepoint`
pops the matched frame AND every frame above it. The popped
frames' changes merge upward (into the next-outer frame, or to
the transaction floor if the released frame was outermost).

**O5. RollbackTo keeps the matched frame.** `RollbackToSavepoint`
reverts work done since the matched frame, but leaves the frame
itself on the stack. Frames deeper than the matched one are
discarded as part of the revert.

**O6. SavepointNotFound is the only name error.** If `name`
isn't on the stack, return
`Halt(Error(RuntimeCondition::SavepointNotFound))`. The opcode
does not silently no-op.

**O7. Stack overflow is the only push error.**
`Halt(Error(RuntimeCondition::SavepointStackOverflow))` when
push would exceed `SAVEPOINT_STACK_MAX_DEPTH`.

**O8. No register / cursor side effects.** None of the three
opcodes touches a register or a cursor. They are pure
transaction-control opcodes.

**O9. Outcome is Continue or Halt(Error(...)).** None of these
opcodes returns `Jump` — they're not branchy. The outer VDBE
loop advances `pc` by 1 on `Continue`.

**O10. No invented helpers.** Per `/spec/part-conventions.spec.md`
§Generation scope. Targets emit only what `shapes.json`
declares plus what this spec explicitly requires.

## Regeneration envelope

- Line budget: **~120-180 lines** per target. Three opcode
  arms in the executor's match, plus the variant declaration.
- No state held in the VDBE for savepoints — pure delegation to
  storage.
