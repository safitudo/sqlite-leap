# VDBE opcodes — language-neutral ISA spec

This spec defines the VDBE (Virtual Database Engine) instruction set used in Phase 2b. The VDBE executes a linear program of opcodes against storage, accumulating a Result.

See `spec/vdbe-interpreter.spec.md` for the execution model (registers, cursors, program counter, halt conditions). This file defines the ISA itself.

## Program structure

A VDBE program is a record:

- `opcodes` — an ordered non-empty list of Opcode records
- `num_registers` — non-negative integer; the number of register cells the program declares
- `num_cursors`   — non-negative integer; the number of cursor slots the program declares

See `schema/program.schema.json` for the concrete shape.

## Opcode reference — Phase 2b (12 opcodes)

Each opcode's `op` field is a string literal matching the subsection heading (without the `Op` prefix). Operand field names are exactly as listed.

### `Init`

- **Operands:** none
- **Semantics:** no effect. Advances PC by 1. Reserved as a preamble slot for future phases (subroutines, version checks).
- **Errors:** none

### `Halt`

- **Operands:** none
- **Semantics:** execution terminates successfully. The VDBE returns `{"rows": result_rows}`, where `result_rows` is the accumulated result-rows buffer (see the interpreter spec).
- **Errors:** none

### `LoadConst`

- **Operands:**
  - `dest`   — register index (non-negative integer, `< num_registers`)
  - `value`  — a Value (integer / UTF-8 text / NULL), per `schema/value.schema.json`
- **Semantics:** `registers[dest] := value`. Advances PC by 1.
- **Errors:** none

### `ResultRow`

- **Operands:**
  - `start`  — register index
  - `count`  — positive integer (`≥ 1`), with `start + count ≤ num_registers`
- **Semantics:** append one Row to `result_rows`. The Row's i-th column (for `0 ≤ i < count`) is `registers[start + i]`. Advances PC by 1.
- **Errors:** none

### `OpenRead`

- **Operands:**
  - `cursor` — cursor slot index (`< num_cursors`)
  - `table`  — table name (identifier string)
- **Semantics:** open a read-only cursor over the named table and bind it to `cursor`. The cursor is open-but-unpositioned after this opcode. Advances PC by 1 on success.
- **Errors:** `STORAGE_TABLE_NOT_FOUND` if no table with that name (propagated from storage; halts execution).

### `OpenWrite`

- **Operands:** identical to `OpenRead`
- **Semantics:** open a write-capable cursor. Otherwise identical to `OpenRead`.
- **Errors:** same as `OpenRead`.

### `Close`

- **Operands:**
  - `cursor` — cursor slot index
- **Semantics:** close the cursor in `cursor`. Closing an already-closed slot is a no-op. Advances PC by 1.
- **Errors:** none

### `Rewind`

- **Operands:**
  - `cursor`         — cursor slot index (must have been opened)
  - `jump_if_empty`  — PC target (non-negative integer, `< opcodes.length`)
- **Semantics:**
  - If the cursor's table has zero rows: set `PC := jump_if_empty`. The cursor remains open-but-unpositioned.
  - Else: position the cursor at row 0 (the first row in insertion order) and advance PC by 1.
- **Errors:** none (table-not-found already caught at open time).

**Compiler responsibility:** the `jump_if_empty` target MUST route past every `Column` and `Next` opcode that uses this cursor. An open-but-unpositioned cursor is unusable with `Column`/`Next`; the VDBE treats such usage as undefined behaviour (see `spec/vdbe-interpreter.spec.md` § "Cursor lifecycle"). A well-formed program emitted by the compiler never exercises this path.

### `Next`

- **Operands:**
  - `cursor`        — cursor slot index (must be positioned on a row)
  - `jump_if_more`  — PC target
- **Semantics:**
  - Advance the cursor's position by 1.
  - If the new position indexes a valid row (one more exists after advancing): set `PC := jump_if_more`.
  - Else: the cursor becomes past-end; advance PC by 1 (fall through).
- **Errors:** none

### `Column`

- **Operands:**
  - `cursor` — cursor slot (must be positioned on a row)
  - `column` — column index within the table (0-based, `< table.columns.length`)
  - `dest`   — register index
- **Semantics:** `registers[dest] := cursor.current_row[column]`. Advances PC by 1.
- **Errors:** none (column index is validated at compile time by the compiler's schema resolution).

### `InsertRow`

- **Operands:**
  - `cursor`        — cursor slot (must be a write cursor)
  - `column_names`  — either the null/absent marker OR a non-empty ordered list of identifier strings
  - `start`         — register index
  - `count`         — positive integer (`≥ 1`)
- **Semantics:** read `values := registers[start .. start + count - 1]`. Call `storage.insert_row(cursor.table, column_names, values)`. On success, **the cursor is left positioned at the newly-inserted row** (retroactive pin 2026-04-18 — required so Phase 9c DML-maintenance recipes can read the new rowid via `TableRowid` without re-seeking). Advances PC by 1.
- **Errors:** any of `STORAGE_TABLE_NOT_FOUND`, `STORAGE_COLUMN_NOT_FOUND`, `STORAGE_DUPLICATE_COLUMN`, `STORAGE_ARITY_MISMATCH`, `STORAGE_TYPE_MISMATCH` — propagated from storage, halts execution.

### `CreateTable`

- **Operands:**
  - `table`   — table name
  - `columns` — non-empty ordered list of `{name, type}` records where `type ∈ {"INTEGER", "TEXT"}`
- **Semantics:** call `storage.create_table(table, columns)`. On success, advances PC by 1.
- **Errors:** `STORAGE_TABLE_EXISTS` or `STORAGE_DUPLICATE_COLUMN` — propagated, halts execution.

## Well-formedness (compile-time invariants)

A program is **well-formed** iff ALL of the following hold:

1. `opcodes` is a non-empty list.
2. `num_registers ≥ 0`, `num_cursors ≥ 0`.
3. For every `LoadConst` opcode: `dest < num_registers`.
4. For every `ResultRow` opcode: `start + count ≤ num_registers` and `count ≥ 1`.
5. For every `Column` opcode: `dest < num_registers`.
6. For every `InsertRow` opcode: `start + count ≤ num_registers` and `count ≥ 1`.
7. For every opcode with a `cursor` operand: `cursor < num_cursors`.
8. For every opcode with a `jump_if_empty` / `jump_if_more` operand: the target is in `[0, opcodes.length)`.
9. The last opcode is `Halt`. Earlier `Halt` opcodes are permitted (e.g. for early-exit on branches) but Phase 2b compilation recipes do not emit any.

Ill-formed programs cause target-defined behaviour from the VDBE and are a compiler-part bug (the compiler is the warranty). The Phase 2b test harness enforces invariants 1–9 on every compiled program as a preflight check, separately from behavioural tests.

## Semantics of field types

- Register index — non-negative integer
- Cursor index  — non-negative integer
- PC target     — non-negative integer
- Table / column / identifier strings — UTF-8; in Phase 2b, ASCII only (matches Phase 2a's grammar constraint)
- Value         — per `schema/value.schema.json`

## Test authority

`tests/cross-build/phase2b.json` is the executable specification for Phase 2b VDBE-specific behaviour. If this document and those tests disagree, the tests win.

---

## Phase 2c-1 opcodes (11 additions)

These opcodes extend the Phase 2b ISA. All of them operate on registers and follow NULL propagation (any NULL operand yields NULL in `dest`). New error conditions: `EVAL_TYPE_ERROR` and `EVAL_DIVISION_BY_ZERO` (defined in `spec/sql-grammar.spec.md` § "Phase 2c-1 new error conditions").

### Arithmetic — `Add`, `Subtract`, `Multiply`, `Divide`

- **Operands (each):**
  - `dest` — register index (`< num_registers`)
  - `lhs`  — register index
  - `rhs`  — register index
- **Semantics:**
  - If `registers[lhs]` or `registers[rhs]` is NULL: `registers[dest] := NULL`, advance PC by 1.
  - If either is TEXT: raise `EVAL_TYPE_ERROR` with `op` (see below), `left_type`, `right_type`.
  - Else (both INTEGER): compute the integer operation; store in `registers[dest]`; advance PC by 1.
- **`op` names in the error:** `Add` → `"+"`, `Subtract` → `"-"`, `Multiply` → `"*"`, `Divide` → `"/"`.
- **Overflow:** target-defined (wrap-on-overflow is acceptable; trapping is acceptable). No named error.
- **Integer division:** truncates toward zero (standard signed-integer `/` semantics). If `registers[rhs]` is INTEGER `0` and `registers[lhs]` is a non-NULL INTEGER, `registers[dest] := NULL` (SQLite-compat quirk; mainline SQLite evaluates integer `x/0` to NULL, not an error). The same rule applies to the integer `%` (modulo) path: INTEGER `0` rhs with non-NULL lhs yields NULL. Real/IEEE division paths are unaffected (IEEE `x/0.0` yields `+inf`/`-inf`/`NaN` per IEEE-754). The `EVAL_DIVISION_BY_ZERO` error kind remains defined for symmetry across language generators but is not triggered by this path. (Zero right operand of type TEXT still raises `EVAL_TYPE_ERROR` — type check precedes zero check.)

### `Negate` — unary minus

- **Operands:**
  - `dest` — register index
  - `src`  — register index
- **Semantics:**
  - If `registers[src]` is NULL: `registers[dest] := NULL`.
  - If TEXT: raise `EVAL_TYPE_ERROR` with `op = "-"` (unary) and `operand_type`.
  - Else (INTEGER): `registers[dest] := -registers[src]`, wrapping on the INT64_MIN edge case per target-defined policy.

### Comparison — `Eq`, `Ne`, `Lt`, `Le`, `Gt`, `Ge`

- **Operands (each):**
  - `dest` — register index
  - `lhs`  — register index
  - `rhs`  — register index
- **Semantics:** produce a comparison result and store in `registers[dest]`:
  - Either operand NULL → `registers[dest] := NULL`.
  - Both INTEGER → numeric comparison; `registers[dest] := 1` (true) or `0` (false).
  - Both TEXT → byte-by-byte lexicographic comparison (ASCII in 2c-1); `registers[dest] := 1` or `0`.
  - Mixed INTEGER / TEXT → raise `EVAL_TYPE_ERROR` with `op` name (see below), `left_type`, `right_type`.
- **`op` names:** `Eq` → `"="`, `Ne` → `"!="`, `Lt` → `"<"`, `Le` → `"<="`, `Gt` → `">"`, `Ge` → `">="`.

### Well-formedness extensions (Phase 2c-1)

The Phase 2b invariants 1–9 remain in force. The Phase 2c-1 harness additionally checks:

10. For every `Add` / `Subtract` / `Multiply` / `Divide` / comparison opcode: `dest < num_registers`, `lhs < num_registers`, `rhs < num_registers`.
11. For every `Negate` opcode: `dest < num_registers`, `src < num_registers`.

### VDBE error propagation (Phase 2c-1)

New `EVAL_*` errors propagate identically to the existing `STORAGE_*` errors: the VDBE terminates and returns the error unchanged (same `name`, same `fields`).

---

## Phase 2c-2 opcodes (4 additions)

Phase 2c-2 extends the ISA with three logical-operator opcodes (`And`, `Or`, `Not`) and one control-flow opcode (`JumpIfFalse`) used to implement the WHERE clause. All four operate on registers. No new error names are introduced; `EVAL_TYPE_ERROR` gains four additional `op` values (`"AND"`, `"OR"`, `"NOT"`, `"WHERE"`).

### `And` — logical AND (SQL 3VL)

- **Operands:**
  - `dest` — register index (`< num_registers`)
  - `lhs`  — register index
  - `rhs`  — register index
- **Semantics:**
  - Load `a := registers[lhs]`, `b := registers[rhs]`.
  - If `a` is TEXT or `b` is TEXT: raise `EVAL_TYPE_ERROR` with `op = "AND"`, `left_type`, `right_type`. (Both sides are classified; no short-circuit on TEXT.)
  - If `a` is `INTEGER 0` OR `b` is `INTEGER 0`: `registers[dest] := INTEGER 0` (FALSE short-circuit on the value path only, AFTER the TEXT check has cleared both sides).
  - Else if both are `INTEGER` non-zero: `registers[dest] := INTEGER 1` (TRUE).
  - Else (at least one NULL, neither FALSE): `registers[dest] := NULL`.
- Advance PC by 1.

### `Or` — logical OR (SQL 3VL)

- **Operands:** identical to `And`.
- **Semantics:**
  - Load `a := registers[lhs]`, `b := registers[rhs]`.
  - If `a` is TEXT or `b` is TEXT: raise `EVAL_TYPE_ERROR` with `op = "OR"`, `left_type`, `right_type`.
  - If `a` is `INTEGER` non-zero OR `b` is `INTEGER` non-zero: `registers[dest] := INTEGER 1` (TRUE).
  - Else if both are `INTEGER 0`: `registers[dest] := INTEGER 0` (FALSE).
  - Else (at least one NULL, neither TRUE): `registers[dest] := NULL`.
- Advance PC by 1.

### `Not` — logical NOT

- **Operands:**
  - `dest` — register index
  - `src`  — register index
- **Semantics:**
  - Load `v := registers[src]`.
  - If `v` is TEXT: raise `EVAL_TYPE_ERROR` with `op = "NOT"`, `operand_type = "TEXT"`.
  - If `v` is NULL: `registers[dest] := NULL`.
  - If `v` is `INTEGER 0`: `registers[dest] := INTEGER 1`.
  - Else (INTEGER non-zero): `registers[dest] := INTEGER 0`.
- Advance PC by 1.

### `JumpIfFalse` — conditional jump (WHERE clause gate)

- **Operands:**
  - `cond`   — register index (`< num_registers`)
  - `target` — PC target (non-negative integer, `< opcodes.length`)
- **Semantics:**
  - Load `v := registers[cond]`.
  - If `v` is TEXT: raise `EVAL_TYPE_ERROR` with `op = "WHERE"`, `operand_type = "TEXT"`.
  - If `v` is NULL or `INTEGER 0`: set `PC := target` (jump — the row is filtered out / the guarded branch is skipped).
  - If `v` is `INTEGER` non-zero: advance PC by 1 (fall through — the guarded branch executes).
- **Note on error shape.** The `op` field is `"WHERE"` — the opcode is named after the semantic use it is always compiled for in Phase 2c-2 (WHERE clause gating), not after the VDBE-level opcode name. Later phases that reuse `JumpIfFalse` for other purposes MAY extend the opcode with a discriminator field; 2c-2 does not.

### Well-formedness extensions (Phase 2c-2)

Invariants 1–9 (Phase 2b) and 10–11 (Phase 2c-1) remain. The Phase 2c-2 harness extends two existing invariants and adds one:

- **Extended 10.** For every `Add` / `Subtract` / `Multiply` / `Divide` / `Eq` / `Ne` / `Lt` / `Le` / `Gt` / `Ge` / `And` / `Or` opcode: `dest`, `lhs`, `rhs` all `< num_registers`.
- **Extended 11.** For every `Negate` / `Not` opcode: `dest`, `src` both `< num_registers`.
- **New 12.** For every `JumpIfFalse` opcode: `cond < num_registers` and `target ∈ [0, opcodes.length)`.

### 3VL truth-table summary (cross-reference)

The binary AND / OR tables and the unary NOT behavior above are exactly those defined in `spec/sql-grammar.spec.md` § "Phase 2c-2 evaluation semantics". The VDBE opcodes implement them mechanically — any divergence between the two specs is a spec bug and MUST be reported, not worked around.

---

## Phase 2c-3 opcodes (2 additions)

Phase 2c-3 adds two mutation opcodes for UPDATE and DELETE. Both operate through a write-capable cursor (opened with `OpenWrite`) that is currently positioned on a live row. No new error names are introduced; `UpdateRow` may propagate existing `STORAGE_*` errors.

### `UpdateRow` — mutate the cursor's current row

- **Operands:**
  - `cursor`        — cursor slot (must be a write cursor positioned on a live row)
  - `column_names`  — a non-empty ordered list of `IDENTIFIER` strings naming the columns to update
  - `start`         — register index
  - `count`         — positive integer (`≥ 1`), with `start + count ≤ num_registers` and `count == |column_names|`
- **Semantics:**
  1. Read `values := registers[start .. start + count - 1]`.
  2. Call `storage.update_row_at_cursor(cursor, column_names, values)`.
  3. On success: mutate the row the cursor is on; columns in `column_names` receive the corresponding `values[i]`; columns NOT in `column_names` retain their existing values. Advance PC by 1.
  4. On storage error: propagate unchanged and halt.
- **Errors:** `STORAGE_COLUMN_NOT_FOUND`, `STORAGE_TYPE_MISMATCH`, `STORAGE_DUPLICATE_COLUMN` — propagated verbatim from storage.

Note: the `column_names` list is fixed at compile time (it comes from the SQL `SET` clause). Per SQL grammar evidence R-34751-18293, the compiler MUST de-duplicate repeated column names rightmost-wins before emitting this opcode. As a result, `column_names` passed to `UpdateRow` at runtime is ALWAYS free of duplicates; `STORAGE_DUPLICATE_COLUMN` does not arise for UPDATE via this path (it still remains on the error enumeration as a safety-net surface from storage). INSERT's compile-time-precedence rule for duplicate column names is unchanged (INSERT rejects duplicates with `STORAGE_DUPLICATE_COLUMN`).

### `DeleteRow` — tombstone the cursor's current row

- **Operands:**
  - `cursor` — cursor slot (must be a write cursor positioned on a live row)
- **Semantics:**
  1. Call `storage.delete_row_at_cursor(cursor)`.
  2. Storage marks the row as tombstoned (implementation detail — see `spec/storage.spec.md`).
  3. Advance PC by 1.
- **Errors:** none. Storage's `delete_row_at_cursor` does not fail (well-formed cursor positioned on a live row is a precondition).

### Cursor lifecycle after `DeleteRow`

After `DeleteRow(cursor)`, the cursor is still "positioned on that slot" but the row it refers to is now tombstoned. Subsequent operations:

- `Column(cursor, ...)` on this slot is undefined behaviour — the compiler MUST NOT emit a `Column` between `DeleteRow` and `Next`.
- `Next(cursor, ...)` advances past the tombstoned row to the next LIVE row (skipping any tombstoned rows in between). If no live row follows, the cursor becomes past-end and falls through (normal Next semantics).
- `Close(cursor)` — normal close.

The same rule applies after `UpdateRow` except the row is still live, so `Column` on the same row is well-defined but would read the updated values — which the compiler does not do in Phase 2c-3 recipes (UPDATE reads columns BEFORE calling UpdateRow).

### Well-formedness extensions (Phase 2c-3)

Invariants 1–12 from earlier phases remain. Phase 2c-3 adds:

- **New 13.** For every `UpdateRow` opcode: `start + count ≤ num_registers`, `count ≥ 1`, `count == |column_names|`, and every `column_names[i]` is a non-empty string.
- **(Cursor check subsumed by invariant 7.)** `UpdateRow.cursor` and `DeleteRow.cursor` are validated by the existing "every opcode with a `cursor` operand: `cursor < num_cursors`" invariant.

### `Init` opcode — finally used

Phase 2b's `Init` opcode has been reserved-but-unemitted since Phase 2b. Phase 2c-3 DOES NOT change this; `Init` remains reserved for future use (subroutines, version checks, transaction pre-logic in Phase 3+). Compilers MAY continue to omit it.

## Phase 6b opcodes (6 additions)

Phase 6b introduces a second resource namespace — **sorters** — alongside the existing cursor namespace. A sorter is an append-only buffer of `(key-tuple, value-tuple)` pairs that, after a terminal `SorterSort`, can be traversed in sorted order.

The `Program` header gains a `num_sorters` field (default 0 for programs that don't use ORDER BY). Runtime allocates `num_sorters` sorters at program entry and frees them at Halt / program exit.

Sorters and cursors share NO state; they are disjoint resources.

### `SorterOpen` — open a sorter

```
SorterOpen { sorter: usize, key_count: usize, value_count: usize, direction_mask: u64 }
```

Semantics:
- Initialise sorter `sorter` as an empty buffer.
- Record its `key_count` and `value_count` (validated on each SorterInsert).
- Record `direction_mask`: bit `i` set means key `i` is `DESC`, bit clear means `ASC`. Bits above `key_count - 1` MUST be zero (well-formedness).

Invariant: `SorterOpen { sorter: k, .. }` must appear before any other sorter opcode referring to sorter `k`. Re-opening an already-open sorter is a well-formedness failure.

### `SorterInsert` — append a (keys, values) pair

```
SorterInsert { sorter: usize, keys_reg: usize, values_reg: usize }
```

Semantics:
- Read `key_count` values starting at register `keys_reg` (inclusive) into the sorter's next slot as the row's key tuple.
- Read `value_count` values starting at register `values_reg` (inclusive) as the row's value tuple.
- Append the pair. No sort yet.
- `keys_reg + key_count ≤ num_registers` and `values_reg + value_count ≤ num_registers`. The ranges MAY overlap (e.g. when the same column is used as both sort key and projected value) — this is legal and the sorter takes its own copies.

### `SorterSort` — finalise sort

```
SorterSort { sorter: usize }
```

Semantics:
- Sort the accumulated (keys, values) pairs by their key tuple, using the sorter's recorded `direction_mask`.
- Comparison rules (per `spec/sql-grammar.spec.md` § "Phase 6b semantics — execution"): NULL < INTEGER < TEXT; NULL sorts first for ASC / last for DESC; INTEGER numeric; TEXT byte-lexicographic.
- Sort is STABLE: equal-key rows keep insertion order.
- After `SorterSort`, no further `SorterInsert` on this sorter is legal in Phase 6b (well-formedness). The cursor position is logically "before first row" until `SorterRewind`.

### `SorterRewind` — position at first sorted row, or jump if empty

```
SorterRewind { sorter: usize, jump_if_empty: usize }
```

Semantics:
- If the sorter is empty, jump to `jump_if_empty`. Pointer remains "before first".
- Otherwise, position the sorter's cursor at the first sorted row.
- Mirrors the Phase 2b `Rewind` opcode for cursor-over-table. `SorterRewind` must be preceded (somewhere upstream) by `SorterSort` on the same sorter.

### `SorterNext` — advance sorter cursor

```
SorterNext { sorter: usize, jump_if_more: usize }
```

Semantics:
- Advance the sorter's cursor by one row.
- If more rows remain, jump to `jump_if_more`.
- Otherwise, fall through (cursor is now exhausted).
- Mirrors the Phase 2b `Next` opcode.

### `SorterRead` — read a value from the current sorted row

```
SorterRead { sorter: usize, slot: usize, dest: usize }
```

Semantics:
- `slot` addresses the sorter's VALUE tuple by zero-based index (NOT the key tuple — keys are sort-only, not directly readable in Phase 6b).
- `0 ≤ slot < value_count` (well-formedness).
- Copy the value at `slot` from the current sorted row into register `dest`.
- Raises no errors at runtime; WF rejects out-of-range slots at compile time.

### Well-formedness extensions (Phase 6b)

Invariants 1–13 remain. Phase 6b adds:

- **New 14.** `Program` gains `num_sorters ≥ 0`. For every opcode with a `sorter` operand: `sorter < num_sorters`.
- **New 15.** Exactly one `SorterOpen { sorter: k }` per program, per `k`. No duplicate opens. Every sorter used by any sorter-family opcode must have a `SorterOpen` lexically earlier in the opcode stream.
- **New 16.** For every `SorterOpen`: `direction_mask < (1 << key_count)` (no bits above `key_count - 1`).
- **New 17.** For every `SorterInsert { keys_reg, values_reg }`: `keys_reg + key_count ≤ num_registers` and `values_reg + value_count ≤ num_registers` (using the open's recorded counts).
- **New 18.** For every `SorterRead { slot }`: `slot < value_count` and `dest < num_registers`.
- **New 19.** Every `SorterInsert` for sorter `k` occurs lexically BEFORE any `SorterSort` for `k`. Every `SorterRewind`/`SorterNext`/`SorterRead` for `k` occurs lexically AFTER some `SorterSort` for `k`. (Compilers naturally emit in this order; the invariant exists to reject malformed programs.)
- **New 20.** Every `SorterRewind.jump_if_empty` and `SorterNext.jump_if_more` points inside the program (`< opcodes.len()`).

### Non-goals (Phase 6b opcodes)

- Key reads (`SorterReadKey`) — deferred; Phase 6b tests never need to emit key values that aren't also in the projection.
- In-place sort over the cursor (avoiding the second buffer) — rejected: the two-loop shape with an explicit sorter keeps the VDBE trivially correct and has no measurable cost for Phase 6b workloads.
- Spilling to disk — explicitly deferred. Phase 6b sorter is memory-only; workloads that exhaust memory are out of scope.

## Phase 6c opcodes (2 additions)

Phase 6c introduces scalar aggregate accumulation. Two opcodes, both register-based (no new resource namespace; accumulators live in regular VDBE registers).

### `AggStep` — update an accumulator with one input row

```
AggStep { acc_reg: usize, kind: AggregateKind, arg_reg: usize }

AggregateKind ∈ { CountStar, Count, Sum, Min, Max }
```

Semantics:

- **CountStar**: `acc_reg ← acc_reg + 1` (acc is always `Integer`; `arg_reg` is ignored — pass 0 for clarity but any in-range value is legal).
- **Count**: if `regs[arg_reg]` is `Null`, no-op. Else `acc_reg ← acc_reg + 1`.
- **Sum**: if `regs[arg_reg]` is `Null`, no-op. Else if `regs[arg_reg]` is not `Integer`, raise `VDBE_TYPE_MISMATCH { operation: "sum", kind: "<lhs kind>" }`. Else if `acc_reg` is `Null`, `acc_reg ← regs[arg_reg]`. Else `acc_reg ← acc_reg + regs[arg_reg]` (integer add; overflow semantics unchanged from Phase 2c-1 `Add`).
- **Min**: if `regs[arg_reg]` is `Null`, no-op. Else if `acc_reg` is `Null`, `acc_reg ← regs[arg_reg]`. Else `acc_reg ← sort-less-than(regs[arg_reg], acc_reg) ? regs[arg_reg] : acc_reg`. The `sort-less-than` is the same total order used by ORDER BY (see `sql-grammar.spec.md` § "Phase 6b semantics").
- **Max**: symmetric — keep the sort-greater of the two.

Arg-reg validity: `arg_reg < num_registers`. `acc_reg < num_registers`.

### `AggFinal` — copy accumulator to a destination register

```
AggFinal { acc_reg: usize, kind: AggregateKind, dest: usize }
```

Semantics:

- **CountStar, Count**: `dest ← acc_reg` (always `Integer`).
- **Sum, Min, Max**: `dest ← acc_reg` (may be `Null` if no non-NULL inputs arrived).

AggFinal exists as a separate opcode primarily because in Phase 6d (GROUP BY) it will need to also reset the accumulator for the next group. In Phase 6c it is effectively a `Copy` with a `kind` annotation for symmetry with `AggStep`; the kind is retained in the opcode payload so that harnesses can verify AggStep/AggFinal kind-pairing at well-formedness time.

### Well-formedness extensions (Phase 6c)

Invariants 1–20 remain. Phase 6c adds:

- **New 21.** For every `AggStep` and `AggFinal`: `acc_reg < num_registers` and `dest < num_registers` and `arg_reg < num_registers` (AggStep only).
- **New 22.** For each `acc_reg` value used in an `AggStep` or `AggFinal`, the `kind` field must be consistent across all opcodes referring to that `acc_reg`. A program that steps into `acc_reg = 3` with kind `Sum` and then `AggFinal`s it with kind `Min` is malformed.

### Non-goals (Phase 6c opcodes)

- `AggReset` for GROUP BY — deferred to Phase 6d.
- Decimal / floating-point accumulators — deferred until REAL type lands.
- Per-aggregate distinct deduplication — deferred.

## Phase 6d opcodes (1 addition)

Phase 6d adds GROUP BY + HAVING but only requires ONE new opcode. Accumulator reset between groups is implemented with existing `LoadConst` (0 for Count/CountStar, Null for Sum/Min/Max), so no `AggReset` opcode is needed.

### `SorterReadKey` — read a KEY value from the sorter's current row

```
SorterReadKey { sorter: usize, slot: usize, dest: usize }
```

Semantics:

- Identical to `SorterRead` (Phase 6b) but addresses the sorter's KEY tuple (not the value tuple).
- `0 ≤ slot < key_count` of the sorter's recorded key_count (well-formedness).
- Used by the GROUP BY drain loop to read the current row's group-key values and compare them to the previous row's (held in scratch registers) to detect group boundaries.

### Well-formedness extensions (Phase 6d)

Invariants 1–22 remain. Phase 6d adds:

- **New 23.** For every `SorterReadKey { slot }`: `slot < key_count` (of the matching `SorterOpen`).

### Phase 6d additional opcodes — pinned by cross-corroboration

The Phase 6d dual-regen surfaced three gaps in the pre-6d opcode set. The original 6d spec suggested that existing `Eq`/`And`/`JumpIfFalse`/`LoadConst` would suffice, but that was wrong: those are 3VL on NULL, and the grouping rule requires NULL==NULL to be TRUE for group-break detection. Two generators independently hit this and resolved differently (C: per-key is-null-flag trick + `AggFinal`-with-`CountStar`-kind-as-copy + `JumpIfFalse reg_zero` as unconditional jump; Rust: three new primitive opcodes). Per the cross-corroboration rule, we pin the Rust approach — three orthogonal primitives are cleaner than three ad-hoc compiler tricks, and they match the SQLite VDBE idiom for `OP_SCopy`, `OP_Goto`, `OP_Eq` (with NULL-handling flag).

Compliant implementations MAY continue to use the compiler-trick realisations (the C target currently does) as long as observable behaviour matches. Future regenerations normalise on these three.

#### `SortValueEq { dest: usize, lhs: usize, rhs: usize }`

Semantics:
- Compares `regs[lhs]` and `regs[rhs]` using SORT-ORDER equality (not 3VL). Two NULLs are EQUAL; NULL vs non-NULL is UNEQUAL; within a type, bytewise/numeric equality as per `sql-grammar.spec.md` § "Phase 6b semantics — execution".
- Writes `Integer(1)` or `Integer(0)` into `regs[dest]`. NEVER writes NULL. Group-break detection depends on this.

Well-formedness: `dest`, `lhs`, `rhs` all `< num_registers`.

#### `Copy { dest: usize, src: usize }`

Semantics:
- `regs[dest] ← regs[src]` (value clone — for TEXT this is an owned-string clone; for INTEGER/NULL a trivial copy).
- Idempotent; no error paths.

Well-formedness: `dest`, `src` both `< num_registers`.

#### `Jump { target: usize }`

Semantics:
- Unconditional branch to opcode index `target`.
- Analogous to `OP_Goto` in mainline-SQLite VDBE terminology.

Well-formedness: `target < opcodes.len()`.

### Non-goals (Phase 6d opcodes)

- `SorterCompareKeys` (a bundled "compare current to prev" opcode) — explicitly rejected. Compilers emit the comparison with `SorterReadKey` + `SortValueEq` + `And` + `JumpIfFalse`, keeping the opcode set orthogonal.
- `AggReset` — rejected (use `LoadConst`).

## Phase 6i opcodes (1 addition)

Phase 6i introduces `Scalar`, a single-argument pure-function opcode. CAST is the first consumer (three cast-kind variants); scalar functions (LENGTH, ABS, ...) reuse the same opcode in Phase 6j with additional kinds.

### `Scalar` — apply a single-argument pure scalar transformation

```
Scalar { kind: ScalarKind, arg_reg: usize, dest: usize }

ScalarKind ∈ { CastInteger, CastReal, CastText }   // Phase 6j will extend
```

Semantics:
- Reads `regs[arg_reg]`, applies the per-kind transformation (see `sql-grammar.spec.md` § "Phase 6i semantics — evaluation"), writes the result into `regs[dest]`.
- `arg_reg == dest` is legal (in-place cast).
- Null passes through unchanged: `regs[arg_reg] = Null` → `regs[dest] = Null` for all kinds, never errors.

Per-kind error surface:
- **`CastInteger`**: may raise `VDBE_CAST_OVERFLOW { from_kind: "Real", to_kind: "Integer" }` for Real→Integer non-finite / out-of-range; `VDBE_CAST_OVERFLOW { from_kind: "Text", to_kind: "Integer" }` for Text→Integer parsed-prefix overflow.
- **`CastReal`**: may raise `VDBE_CAST_OVERFLOW { from_kind: "Text", to_kind: "Real" }` for Text→Real overflow to ±inf. Integer→Real and Real→Real are infallible.
- **`CastText`**: may raise `VDBE_UNSUPPORTED_CAST { from_kind: "Real", to_kind: "Text" }` when the input is a Real value (Phase 6i limitation; lifted in 6j). Integer→Text and Text→Text are infallible.

### Well-formedness extensions (Phase 6i)

Invariants 1–24 remain. Phase 6i adds:

- **New 25.** For every `Scalar { arg_reg, dest }`: `arg_reg < num_registers` and `dest < num_registers`. No register-aliasing restriction between `arg_reg` and `dest` (in-place cast is allowed).

### Non-goals (Phase 6i opcodes)

- Multi-arg scalar functions (e.g. `SUBSTR(s, start, length)`, `ROUND(x, digits)`) — Phase 6j will decide between (a) introducing a `Scalar2 { kind, arg1, arg2, dest }` opcode family and (b) relaxing `Scalar` to carry a small `arg_regs` array. Dual-regen cross-corroboration will inform the choice.
- Function-name-as-string dispatch (`Call { name: &str, ... }`) — rejected: a typed `ScalarKind` enum keeps VDBE well-formedness checks simple and matches the AggregateKind idiom.
- Real→Text transform for `CastText` kind — deferred to Phase 6j together with a pinned shortest-round-trip f64 format.

## Phase 6j opcodes (0 additions — `ScalarKind` extension only)

Phase 6j adds scalar function dispatch without introducing a new opcode. The existing `Scalar { kind, arg_reg, dest }` from Phase 6i is reused; its `ScalarKind` enum gains two variants:

```
ScalarKind ∈ { CastInteger, CastReal, CastText, Length, Abs }   // Phase 6j adds Length + Abs
```

Per-kind semantics (see `sql-grammar.spec.md` § "Phase 6j semantics — evaluation"):
- **`Length`**: Null→Null; Text→Integer (UTF-8 code-point count); Integer/Real→`VDBE_TYPE_MISMATCH { operation: "length" }`.
- **`Abs`**: Null→Null; Integer→|Integer| (raising `VDBE_INTEGER_OVERFLOW` for `i64::MIN`); Real→|Real| (IEEE `fabs`); Text→`VDBE_TYPE_MISMATCH { operation: "abs" }`.

### Well-formedness (Phase 6j)

Invariants 1–25 remain unchanged. No new invariants. Invariant 25 (Scalar arg/dest in-range) already covers the new kinds.

### Non-goals (Phase 6j opcodes)

- New opcode for multi-arg functions — deferred to the first phase that actually needs one.
- A `UPPER` / `LOWER` / `TRIM` family — Phase 6k adds UPPER + LOWER; TRIM deferred.

## Phase 6k opcodes (0 additions — `ScalarKind` extension only)

Phase 6k extends `ScalarKind` with two more variants:

```
ScalarKind ∈ { CastInteger, CastReal, CastText, Length, Abs, Upper, Lower }   // Phase 6k adds Upper + Lower
```

Per-kind semantics (see `sql-grammar.spec.md` § Phase 6k):
- **`Upper`**: Null→Null; Text→byte-wise ASCII uppercase (0x61..=0x7A → ...-0x20; non-ASCII passthrough); Integer/Real→`VDBE_TYPE_MISMATCH { operation: "upper" }`.
- **`Lower`**: Null→Null; Text→byte-wise ASCII lowercase (0x41..=0x5A → ...+0x20; non-ASCII passthrough); Integer/Real→`VDBE_TYPE_MISMATCH { operation: "lower" }`.

### Well-formedness (Phase 6k)

Invariants 1–25 remain unchanged. No additions.

### Non-goals (Phase 6k opcodes)

- Unicode case mapping — deferred indefinitely.
- Multi-arg functions still deferred.

## Phase 6l opcodes (0 additions — `ScalarKind` extension only)

Phase 6l extends `ScalarKind` with three more variants:

```
ScalarKind ∈ { CastInteger, CastReal, CastText, Length, Abs, Upper, Lower, Trim, Ltrim, Rtrim }
```

Per-kind semantics (see `sql-grammar.spec.md` § Phase 6l):
- **`Ltrim`**: Null→Null; Text→strip leading bytes in `{0x20, 0x09, 0x0A, 0x0D}`; Integer/Real→`VDBE_TYPE_MISMATCH { operation: "ltrim" }`.
- **`Rtrim`**: symmetric — trailing.
- **`Trim`**: both ends.

### Well-formedness (Phase 6l)

Unchanged. max_invariant remains 25.

## Phase 6n opcodes (1 addition)

Phase 6n introduces scalar subqueries. One new opcode; no changes to existing opcodes.

### `SubqueryEmit` — emit the single-row result of a scalar subquery

```
SubqueryEmit { state_reg: usize, dest: usize, src: usize }
```

Semantics:
- If `regs[state_reg]` equals `Integer(0)`:
  - Set `regs[state_reg] = Integer(1)`.
  - Copy `regs[src]` into `regs[dest]` (value-clone; for Text, owned clone).
- Else (meaning a prior row was already emitted):
  - Raise `VDBE_SUBQUERY_MORE_THAN_ONE_ROW`.

The compiler initialises `regs[state_reg] = Integer(0)` and `regs[dest] = Null` BEFORE the subquery body runs. If the subquery body emits zero rows (no `SubqueryEmit` execution), `regs[dest]` remains `Null` — the spec's zero-rows-→-Null contract is satisfied by the initial `LoadConst Null`.

`SubqueryEmit` replaces the subquery body's `ResultRow`. A compiler that compiles a subquery's body using the same pipeline as a top-level SELECT must rewrite all emitted `ResultRow` opcodes within the subquery to `SubqueryEmit` (passing `proj[0]` as `src`; ignoring `proj[1..]` — compile-time arity check guarantees the projection has exactly one column).

### Well-formedness extensions (Phase 6n)

Invariants 1–25 remain. Phase 6n adds:

- **New 26.** For every `SubqueryEmit`: `state_reg < num_registers`, `dest < num_registers`, `src < num_registers`. No aliasing restriction.

### Non-goals (Phase 6n opcodes)

- `SubqueryBegin` / `SubqueryEnd` framing opcodes — not needed; the `LoadConst state_reg = Integer(0)` + `LoadConst dest = Null` pair serves as `SubqueryBegin`; the subquery's normal `Halt` is sufficient for `SubqueryEnd`.
- Correlated-subquery state threading — Phase 6n is uncorrelated-only.
- `SubprogramCall` / nested-frame opcodes — rejected; inline-splice compilation keeps the VDBE flat.

## Phase 6q opcodes (1 addition)

Phase 6q introduces `Concat`, the string concatenation operator. One new opcode. `ScalarKind` is NOT extended — `Concat` is a two-argument operator that does not fit the `Scalar { kind, arg_reg, dest }` shape (which is single-arg by design, see Phase 6i non-goals).

### `Concat` — string concatenation with implicit Integer→Text coercion

```
Concat { left_reg: usize, right_reg: usize, dest: usize }
```

Semantics (see `sql-grammar.spec.md` § "Phase 6q evaluation semantics — Concat operator" for the authoritative truth table):

1. Let `lv = regs[left_reg]`, `rv = regs[right_reg]`.
2. If `lv == Null` or `rv == Null`: `regs[dest] := Null`. PC += 1. (Null short-circuits BEFORE the Real check below.)
3. Else if `lv` or `rv` is a `Real`: raise `VDBE_UNSUPPORTED_CAST { from_kind: "Real", to_kind: "Text" }` and halt.
4. Else: coerce each operand to a UTF-8 string:
   - `Text(s)` → `s` as-is.
   - `Integer(v)` → signed base-10 decimal representation (same format as `Scalar { kind: CastText }` on Integer input — `-9223372036854775808` to `9223372036854775807`, no leading zeros, `-` for negatives, `0` for zero).
   - `Real(f)` — unreachable (step 3 caught it).
5. Concatenate the two coerced strings and store `regs[dest] := Text(lv_str + rv_str)`. PC += 1.

Aliasing: `left_reg == dest`, `right_reg == dest`, `left_reg == right_reg`, and all three being equal are all legal. The implementation MUST compute the fresh output buffer BEFORE overwriting `regs[dest]`. This mirrors the aliasing discipline of `Scalar { kind: Upper|Lower|Trim|... }` from Phase 6k/6l.

### Well-formedness extensions (Phase 6q)

Invariants 1–26 remain. Phase 6q adds:

- **New 27.** For every `Concat { left_reg, right_reg, dest }`: `left_reg < num_registers`, `right_reg < num_registers`, `dest < num_registers`. No aliasing restriction.

`max_invariant = 27`.

### Non-goals (Phase 6q opcodes)

- A generic `BinaryScalar { kind, left_reg, right_reg, dest }` family that subsumes `Concat` plus future 2-arg string / math operators — rejected for Phase 6q. If Phase 6s introduces `SUBSTR(s, start, length)` or similar 3-arg shape, the decision of whether to bundle `Concat` into a multi-arg `ScalarN` family will be revisited at that point. For now, one-off opcode.
- Blob support — Blob is not in the Phase 6q value model.
- Reverse-direction casts (Text→Integer when Integer operand is expected) — `||` is the only affected operator and it coerces *to* Text, not *from* it.

## Phase 6s opcodes (1 addition)

Phase 6s introduces `Scalar2`, a two-argument pure-function opcode. `IFNULL` is the first consumer. `COALESCE` is desugared at compile time to nested `Scalar2 { kind: Ifnull }` and does not introduce an opcode of its own. Future 2-arg scalars (string / math) will extend `Scalar2Kind` without introducing further opcodes.

**Phase 6bu extension.** `Scalar2Kind` gains a `Nullif` variant for the `NULLIF(x, y)` builtin. Semantics: if `v1` is `Null` → `dest := Null`; else if `v1` compares equal to `v2` under the same-tier equality rule (identical to `SortValueEq`: numeric-vs-text is NOT equal without coercion; same-tier numeric uses cross-type value compare; text is byte-equal) → `dest := Null`; else → `dest := v1` (value-clone). Never raises. See `sql-grammar.spec.md` § "Phase 6bu" for authoritative semantics and rationale. No invariant bump (bounds identical to the rest of the `Scalar2Kind` family; `max_invariant = 45` unchanged).

### `Scalar2` — apply a two-argument pure scalar transformation

```
Scalar2 { kind: Scalar2Kind, arg1_reg: usize, arg2_reg: usize, dest: usize }

Scalar2Kind ∈ { Ifnull }   // Phase 6s. Future: Round2, Substr2, Power, Mod, ...
```

Semantics (per-kind; see `sql-grammar.spec.md` § "Phase 6s evaluation semantics" for the authoritative behaviour):

**`Ifnull`:**
1. Let `v1 = regs[arg1_reg]`, `v2 = regs[arg2_reg]`.
2. If `v1 == Null`: `regs[dest] := v2`. (Value-clone; for Text, owned clone.)
3. Else: `regs[dest] := v1`. (Value-clone.)

PC += 1 in both branches. Never raises.

Aliasing: any combination of `arg1_reg`, `arg2_reg`, `dest` may coincide. Because the IFNULL operation reads both `regs[arg1_reg]` and (conditionally) `regs[arg2_reg]` before writing `regs[dest]`, aliasing is safe without a fresh-buffer pattern — the implementation can short-circuit with a direct register-to-register copy.

### Well-formedness extensions (Phase 6s)

Invariants 1–27 remain. Phase 6s adds:

- **New 28.** For every `Scalar2 { arg1_reg, arg2_reg, dest }`: `arg1_reg < num_registers`, `arg2_reg < num_registers`, `dest < num_registers`. No aliasing restriction.

`max_invariant = 28`.

### Non-goals (Phase 6s opcodes)

- A `Scalar3 { kind, arg1, arg2, arg3, dest }` opcode — not yet needed. Will be introduced together with `SUBSTR(s, start, length)` in its own phase.
- A variadic `ScalarN { kind, args: usize[], dest }` opcode — rejected. COALESCE desugars to nested `Scalar2 Ifnull` emissions at compile time, keeping opcodes fixed-shape.
- A `Coalesce` opcode — rejected (same reason).
- A dedicated `IfnullBranch` control-flow opcode (skip argN evaluation when argN-1 is non-null) — not yet worth the complexity. Our expressions are pure, so unconditional evaluation of all COALESCE args is observably equivalent to short-circuit evaluation.

## Phase 6t opcodes (1 addition)

Phase 6t introduces `TxnRollback`, the runtime-reject opcode for SQL `ROLLBACK` statements. BEGIN / COMMIT / END statements compile to empty-body programs (`[Init, Halt]`) and need no new opcode.

### `TxnRollback` — reject ROLLBACK at runtime

```
TxnRollback { }   // no operands
```

Semantics:
- Always raises `VDBE_ROLLBACK_NOT_SUPPORTED`. Execution halts; no registers / cursors consulted.

### Well-formedness extensions (Phase 6t)

Invariants 1–28 remain unchanged. No new invariants — `TxnRollback` has no operands, hence no out-of-range conditions. `max_invariant = 28`.

### Non-goals (Phase 6t opcodes)

- `TxnBegin` / `TxnCommit` opcodes — not introduced. BEGIN / COMMIT / END produce body-less programs. If Phase 4 (WAL) later needs to mark transaction boundaries in the opcode stream, it will introduce those opcodes as semantic additions at that time.
- `TxnRollbackTo { savepoint_name }` — permanent non-goal of Phase 6t (no savepoints).
- An opcode carrying a reason-code payload for the rollback rejection — not needed. The single error `VDBE_ROLLBACK_NOT_SUPPORTED` is sufficient; the rejection is unconditional.

## Phase 9a opcodes (1 addition)

Phase 9a introduces `CreateIndex`, analogous to `CreateTable` but for secondary B-tree indexes. Storage-side semantics defined in `file-format.spec.md` § "Phase 9a additions".

### `CreateIndex`

- **Operands:**
  - `name`    — index name (identifier string, case-preserved)
  - `table`   — target table name (identifier string, case-preserved)
  - `columns` — non-empty ordered list of column-name strings
  - `unique`  — boolean
- **Semantics:** call `storage.create_index(name, table, columns, unique)`. On success, advances PC by 1.
- **Errors:** any of `STORAGE_INDEX_EXISTS`, `STORAGE_TABLE_NOT_FOUND`, `STORAGE_COLUMN_NOT_FOUND` — propagated from storage, halts execution.

### Well-formedness extensions (Phase 9a)

Invariants 1–28 remain. No new invariants. `CreateIndex` carries no register or cursor operands. `max_invariant = 28`.

### Non-goals (Phase 9a opcodes)

- `IdxOpenRead` / `IdxOpenWrite` / `IdxSeek` / `IdxNext` / `IdxInsert` / `IdxDelete` — all deferred to 9b (backfill) through 9d (query planner). Phase 9a only scaffolds the storage entry and an empty leaf; no runtime index traversal or mutation opcodes are needed yet.
- `DropIndex` — deferred to Phase 9f.

## Phase 9be opcodes (5 additions)

Phase 9be adds five opcodes: four for index cursor handling, one for rowid-keyed table access (to complete the index-seek-then-table-fetch recipe).

### `IdxOpenRead`

- **Operands:**
  - `cursor`     — cursor slot index
  - `index_name` — name of the index in the schema catalog (canonical resolution key)
  - `root_page`  — page number where the index B-tree's root lives (advisory; WF-checked but not required to be unique across backends)
- **Semantics:** open a read-only cursor over the index B-tree for the index named `index_name`, and bind it to `cursor`. The cursor is open-but-unpositioned. PC += 1.
- **Errors:** none at open time (cursor validation happens at seek).
- **Retroactive pin (2026-04-18, cross-corroboration).** Both C and Rust generators independently needed name-based resolution because in-memory backends may assign `root_page = 0` to every index, making `root_page` alone insufficient to identify an index. `index_name` is therefore the canonical resolution key; `root_page` is retained for WF invariant 29 and on-disk B-tree mounting but MUST NOT be the sole identity.

### `IdxSeek`

- **Operands:**
  - `cursor`           — index cursor slot (must be opened via `IdxOpenRead`)
  - `key_reg`          — register holding the key value to seek for
  - `jump_if_no_match` — PC target to jump to if no entry exists with this key
- **Semantics:**
  - Position the index cursor at the FIRST entry whose first indexed column equals `regs[key_reg]` (using the Phase 9be type-aware comparison).
  - If no such entry exists: `PC := jump_if_no_match`. The cursor becomes unpositioned.
  - Otherwise: PC += 1. The cursor is positioned at the first matching entry.
- **Errors:** `STORAGE_CORRUPT_PAGE` on index B-tree corruption (malformed cells, offsets out of range).

### `IdxNext`

- **Operands:**
  - `cursor`                   — index cursor (must be positioned)
  - `key_reg`                  — register holding the key value the scan is filtering on
  - `jump_if_still_matching`   — PC target to jump to if the advanced position still matches `regs[key_reg]`
- **Semantics:**
  - Advance the index cursor by one cell.
  - If the new position exists AND its first indexed column equals `regs[key_reg]`: `PC := jump_if_still_matching` (loop body re-entry).
  - Else: PC += 1 (fall through — loop exit).
- **Errors:** `STORAGE_CORRUPT_PAGE` on corrupt index pages.

### `IdxRowid`

- **Operands:**
  - `cursor` — index cursor (must be positioned)
  - `dest`   — destination register
- **Semantics:** read the rowid from the current index entry's payload (always the last record column) and store it in `regs[dest]` as an Integer value. PC += 1.
- **Errors:** `STORAGE_CORRUPT_PAGE` if the rowid column is malformed or missing.

### `TableSeekRowid`

- **Operands:**
  - `cursor`    — table cursor (must be opened via `OpenRead` or `OpenWrite`)
  - `rowid_reg` — register holding the target rowid (Integer)
- **Semantics:** position the table cursor at the row with rowid equal to `regs[rowid_reg]`. PC += 1 on success.
- **Errors:** `STORAGE_CORRUPT_INDEX_REFERENCE { rowid }` — no row with the given rowid exists in the table. This is a corruption signal (the index claimed such a row existed). Halts execution.

### Well-formedness extensions (Phase 9be)

Invariants 1–28 remain. Phase 9be adds:

- **New 29.** For every `IdxOpenRead { cursor, index_name, root_page }`: `cursor < num_cursors`; `index_name` is a non-empty string naming an index that exists in the schema catalog; `root_page` MUST be ≥ 2 (page 1 is reserved for sqlite_schema); no static compile-time upper bound on `root_page` (actual upper bound is runtime file size). On in-memory backends where a placeholder `root_page` is used, WF check validates only the ≥ 2 constraint, not uniqueness.
- **New 30.** For every `IdxSeek { cursor, key_reg, jump_if_no_match }`: `cursor < num_cursors`, `key_reg < num_registers`, `jump_if_no_match < opcodes.length`.
- **New 31.** For every `IdxNext { cursor, key_reg, jump_if_still_matching }`: same bounds as `IdxSeek`.
- **New 32.** For every `IdxRowid { cursor, dest }`: `cursor < num_cursors`, `dest < num_registers`.
- **New 33.** For every `TableSeekRowid { cursor, rowid_reg }`: `cursor < num_cursors`, `rowid_reg < num_registers`.

`max_invariant = 33`.

### Non-goals (Phase 9be opcodes)

- `IdxOpenWrite` — deferred to 9c (DML maintenance needs a write cursor).
- `IdxInsert` / `IdxDelete` — deferred to 9c.
- `IdxSeekGE` / `IdxSeekLT` / range-seek variants — deferred to 9d.
- `IdxNextDesc` / reverse traversal — deferred.
- A covering-index variant that fetches columns directly from the index without `TableSeekRowid` — permanent non-goal for v1.

## Phase 9c opcodes (4 additions)

Phase 9c adds opcodes to keep indexes in sync with DML operations. Four new opcodes: one write-cursor opener, one inserter, one deleter, one table-rowid reader. All index opcodes operate on a single index B-tree (no splits — Phase 9d adds splits).

**Retroactive pin (2026-04-18, cross-corroboration).** The original 9c spec listed "3 additions". Both C and Rust generators independently introduced a 4th opcode (`TableRowid`) because the grammar spec's codegen recipes referenced `<read rowid from tbl_cursor into rowid_reg>` as an unlabelled pseudo-op. Promoted to a named opcode with invariant 37. `max_invariant = 37`.

### `IdxOpenWrite`

- **Operands:**
  - `cursor`     — cursor slot index
  - `index_name` — name of the index in the schema catalog (canonical resolution key)
  - `root_page`  — page number of the index B-tree root (advisory; same contract as `IdxOpenRead`)
- **Semantics:** open a read-write cursor over the index B-tree for the index named `index_name`, and bind it to `cursor`. The cursor is open-but-unpositioned. PC += 1.
- **Errors:** none at open time.
- **Relationship to `IdxOpenRead`:** same operand shape. The only difference is that `IdxInsert` / `IdxDelete` require a cursor opened via `IdxOpenWrite` (a read cursor refuses mutation).

### `IdxInsert`

- **Operands:**
  - `cursor`          — index cursor (must be opened via `IdxOpenWrite`)
  - `key_regs_start`  — first register in the contiguous range holding the indexed column values
  - `key_count`       — number of indexed columns (`≥ 1`; matches the index's declared column count)
  - `rowid_reg`       — register holding the rowid to record in the index cell
- **Semantics:**
  - Build an index cell record from `regs[key_regs_start..key_regs_start+key_count]` followed by `regs[rowid_reg]` as the final Integer column (per `file-format.spec.md` § "Index cell format").
  - Insert the cell into the index B-tree in sort order (NULL-first + type-precedence + rowid tie-break, identical to Phase 9be backfill ordering).
  - PC += 1 on success.
- **Errors:**
  - `STORAGE_PAGE_FULL` — the new cell would overflow the single-leaf budget. No splits in 9c (9d introduces interior index pages). Caller is expected to treat as a transaction-aborting error.
  - `VDBE_TYPE_MISMATCH { operation: "idx_insert" }` if `regs[rowid_reg]` is not an Integer (WF check; should be compile-time unreachable).
- **Note on UNIQUE:** 9c does NOT enforce uniqueness. Duplicate `(key_cols..., rowid)` tuples cannot occur (rowid is always unique), but duplicate key_cols with different rowids are accepted. Phase 9g wires UNIQUE enforcement.

### `IdxDelete`

- **Operands:**
  - `cursor`          — index cursor (must be opened via `IdxOpenWrite`)
  - `key_regs_start`  — first register in the contiguous range holding the indexed column values (OLD values for UPDATE)
  - `key_count`       — number of indexed columns
  - `rowid_reg`       — register holding the rowid of the cell to remove
- **Semantics:**
  - Locate the index cell whose record matches `(regs[key_regs_start..key_regs_start+key_count], regs[rowid_reg])` exactly (full tuple including rowid, because multiple rows may share the same indexed-col values but rowid disambiguates).
  - Remove it from the index B-tree.
  - PC += 1 on success.
- **Errors:** `STORAGE_CORRUPT_INDEX_REFERENCE { rowid }` — no matching cell found. This is a corruption signal (the table had a row with this rowid but the index doesn't — DML-maintenance bug or on-disk corruption). Halts execution.

### `TableRowid`

- **Operands:**
  - `cursor` — table cursor (must be opened via `OpenRead` or `OpenWrite`, and positioned on a row — either by `Rewind`+`Next` traversal, by `TableSeekRowid`, or as the post-condition of `InsertRow`)
  - `dest`   — destination register
- **Semantics:** read the rowid of the row the cursor currently points at, and store it in `regs[dest]` as an Integer value. PC += 1.
- **Errors:** none at runtime; WF check (invariant 37) catches out-of-range operands at compile time. Calling on an unpositioned cursor is undefined (a well-formed program never does this).
- **Symmetry with `IdxRowid`:** `IdxRowid` reads a rowid out of an index cell; `TableRowid` reads a rowid off a table cursor's current row. Both are needed for DML-maintenance codegen where an index cell must be constructed from a freshly-inserted or about-to-be-deleted table row.

### Well-formedness extensions (Phase 9c)

Invariants 1–33 remain. Phase 9c adds:

- **New 34.** For every `IdxOpenWrite { cursor, index_name, root_page }`: same constraints as invariant 29 (cursor < num_cursors; index_name non-empty and present in catalog; root_page ≥ 2).
- **New 35.** For every `IdxInsert { cursor, key_regs_start, key_count, rowid_reg }`: `cursor < num_cursors`; `key_count ≥ 1`; `key_regs_start + key_count ≤ num_registers`; `rowid_reg < num_registers`.
- **New 36.** For every `IdxDelete { cursor, key_regs_start, key_count, rowid_reg }`: same bounds as `IdxInsert`.
- **New 37.** For every `TableRowid { cursor, dest }`: `cursor < num_cursors`, `dest < num_registers`.

`max_invariant = 37`.

### Non-goals (Phase 9c opcodes)

- Splits / interior index pages — Phase 9d.
- `IdxInsertCheckUnique` / UNIQUE enforcement — Phase 9g.
- `IdxInsertWithConflict` (ON CONFLICT clause) — not on v1 roadmap.
- Bulk `IdxInsertMany` for batched INSERT — not on v1 roadmap (simpler to loop).

## Phase 9d opcodes (4 additions)

Phase 9d adds four opcodes for range scans and `ORDER BY indexed_col ASC` via index: an index-rewind (to the first cell in sort order), two half-open lower-bound seeks (`≥` and strict `>`), and an unconditional advance for walking ascending without an equality continuation. Upper-bound termination for `<` / `≤` / `BETWEEN` is handled by compile-time emission of `IdxColumn` (reuses 9be read) + `JumpIfFalse` against a bound register; no dedicated upper-bound seek opcode.

### `IdxRewind`

- **Operands:**
  - `cursor`        — index cursor (must be opened via `IdxOpenRead` or `IdxOpenWrite`)
  - `jump_if_empty` — PC target (non-negative, `< opcodes.length`); jumped to if the index has zero cells
- **Semantics:**
  - If the index has ≥ 1 cell: position the cursor at the cell with the smallest sort-key (NULL-first → INTEGER/REAL → TEXT ordering, rowid tie-break); `PC += 1`.
  - Else: `PC := jump_if_empty`. The cursor remains open-but-unpositioned.
- **Errors:** `STORAGE_CORRUPT_PAGE` on malformed pages.
- **Symmetry with table `Rewind`:** identical contract shape; the only difference is that `IdxRewind` produces cells in index-sort order, while `Rewind` produces rows in rowid order.

### `IdxSeekGE`

- **Operands:**
  - `cursor`           — index cursor (must be opened)
  - `key_reg`          — register holding the lower-bound value
  - `jump_if_past_end` — PC target jumped to if no cell has first-col `≥ regs[key_reg]`
- **Semantics:**
  - Position the cursor at the FIRST cell whose first-indexed-column value is `≥ regs[key_reg]` under the Phase 9be type-aware comparison.
  - NULL-key behaviour: a NULL `regs[key_reg]` makes EVERY non-NULL cell satisfy `x ≥ NULL` vacuously under standard SQL 3VL — but by convention we treat NULL-key range seeks the same as `IdxSeek`: short-circuit to the no-match branch. Fixture `idx-seek-ge-with-null-key-returns-nothing` gates this.
  - If no cell qualifies: `PC := jump_if_past_end`. Cursor becomes unpositioned.
  - Else: `PC += 1`. Cursor is positioned at the first qualifying cell.
- **Errors:** `STORAGE_CORRUPT_PAGE` on malformed pages.

### `IdxSeekGT`

- **Operands:** identical to `IdxSeekGE`.
- **Semantics:** as `IdxSeekGE`, but strict `>`. Position at the FIRST cell whose first-indexed-column value is strictly greater than `regs[key_reg]`. NULL key → no-match (same convention).
- **Errors:** same as `IdxSeekGE`.

### `IdxAdvance`

- **Operands:**
  - `cursor`       — index cursor (must be positioned)
  - `jump_if_more` — PC target jumped to if after advancing the cursor is still on a valid cell
- **Semantics:**
  - Advance the cursor by one cell in sort order.
  - If the new position is a valid cell: `PC := jump_if_more` (loop body re-entry).
  - Else (past the last cell): `PC += 1` (fall through, loop exit). Cursor becomes past-end.
- **Errors:** `STORAGE_CORRUPT_PAGE` on malformed pages.
- **Distinction from `IdxNext`:** `IdxNext` is equality-continuation (used for Phase 9be equality scans — jumps while key still matches). `IdxAdvance` is unconditional — jumps while a cell still exists. Upper-bound termination for range scans is compile-time emitted as `IdxColumn` → compare → `JumpIfFalse` BEFORE the loop-body work, then `IdxAdvance` at the tail.

### Well-formedness extensions (Phase 9d)

Invariants 1–37 remain. Phase 9d adds:

- **New 38.** For every `IdxRewind { cursor, jump_if_empty }`: `cursor < num_cursors`, `jump_if_empty < opcodes.length`.
- **New 39.** For every `IdxSeekGE { cursor, key_reg, jump_if_past_end }`: `cursor < num_cursors`, `key_reg < num_registers`, `jump_if_past_end < opcodes.length`.
- **New 40.** For every `IdxSeekGT { cursor, key_reg, jump_if_past_end }`: same bounds as `IdxSeekGE`.
- **New 41.** For every `IdxAdvance { cursor, jump_if_more }`: `cursor < num_cursors`, `jump_if_more < opcodes.length`.

`max_invariant = 41`.

### Phase 9d does NOT introduce

- `IdxSeekLE` / `IdxSeekLT` — upper-bound seeks are unnecessary; forward scan with compile-time termination suffices.
- `IdxPrev` / reverse traversal — permanent non-goal for v1. `ORDER BY indexed_col DESC` continues to use the existing sorter path (via the standard sorter-based ORDER BY compile recipe).
- Multi-column key seeks — deferred to a future phase.
- `IdxColumn` — not a new opcode; reuse the existing semantics of reading an index cell's i-th column via the index cursor (the Phase 9be `IdxRowid` is a specialization of this; for `IdxColumn` at arbitrary col index, the existing planner compiles to `IdxRowid` + `TableSeekRowid` + `Column`, OR generators MAY read the column directly from the positioned index cell). Fixture `upper-bound-check-against-index-column-value` gates observable semantics; the mechanism (TableSeek-and-read vs direct-from-index-cell read) is a generator-choice.

## Phase 9f opcodes (1 addition)

Phase 9f adds one opcode: `DropIndex`, for removing a user-declared index from the schema catalog. No new opcodes for PRIMARY KEY auto-indexes — those reuse the existing `CreateIndex` mechanism at compile time, and the `INTEGER PRIMARY KEY` case compiles to direct rowid-based access using existing Phase 9be / 9c opcodes (no new opcode needed).

### `DropIndex`

- **Operands:**
  - `name`       — index name (identifier string, non-empty)
  - `if_exists`  — boolean; if true, missing index is a no-op (no error)
- **Semantics:** remove the index named `name` from the schema catalog, release its root page, and remove its sqlite_schema row.
  - If the index does not exist AND `if_exists == false`: raise `COMPILE_UNKNOWN_INDEX { name }` (at compile time) or `STORAGE_INDEX_NOT_FOUND { name }` (at runtime if schema drift is detected). Compile-time resolution is preferred.
  - If the index is an auto-generated index (name prefix `sqlite_autoindex_*`): raise `COMPILE_CANNOT_DROP_AUTO_INDEX { name }`. Auto-indexes can only be removed by dropping the parent table (not in v1 scope).
  - PC += 1 on success.
- **Errors:**
  - `COMPILE_UNKNOWN_INDEX { name }` (compile-time resolved, preferred path).
  - `COMPILE_CANNOT_DROP_AUTO_INDEX { name }` (compile-time resolved if known).
  - `STORAGE_INDEX_NOT_FOUND { name }` (runtime, if schema drift).

### Well-formedness extensions (Phase 9f)

Invariants 1–41 remain. Phase 9f adds:

- **New 42.** For every `DropIndex { name, if_exists }`: `name` is a non-empty string; `if_exists` is a boolean.

`max_invariant = 42`.

### Phase 9f does NOT introduce

- `DropTable` — v1 non-goal.
- `DropIndexIfMigrationRunning` — no migration machinery in v1.
- Auto-index-aware opcodes — auto-indexes are transparent to the VDBE; they look like any other index from the opcode's perspective. The only place "auto-index" is special is the compile-time refusal to drop them.

## Phase 9g opcode extensions (0 new opcodes)

Phase 9g adds **no new opcodes**. UNIQUE enforcement is implemented as a semantic extension of two existing opcodes (`IdxInsert` and `CreateIndex`) based on an index-catalog `unique` flag. The catalog flag is set at CREATE (UNIQUE) INDEX / CREATE TABLE (... UNIQUE) time and read at INSERT / UPDATE / backfill time.

### `IdxInsert` — UNIQUE semantic extension

When the index bound to `cursor` is marked `unique = true` in the schema catalog, `IdxInsert` performs a pre-insert probe:

1. Build a search key from `regs[key_regs_start..key_regs_start+key_count]` (same bytes used for the cell body, minus the trailing rowid).
2. If ANY indexed-col value in the key is NULL: skip the check (SQLite convention — NULL never violates UNIQUE, per § "Phase 9g NULL semantics" below). Go to step 4.
3. Probe the index for any existing cell whose first-indexed-col values match the search key (ignoring the cell's rowid). If a match is found: raise `STORAGE_UNIQUE_VIOLATION { index: <index_name>, key: [key_values] }`. Halt execution. NO state mutation has occurred.
4. Proceed with the normal insert.

For non-UNIQUE indexes: behaviour is unchanged from Phase 9c.

**Error addition:** `STORAGE_UNIQUE_VIOLATION { index, key }` is now a possible `IdxInsert` error when the target index is UNIQUE.

### `CreateIndex` — UNIQUE backfill extension

When `CreateIndex` has `unique = true` (from `CREATE UNIQUE INDEX ...` or from an auto-index backing a `UNIQUE` column constraint):

- During backfill, after cells are sorted (Phase 9be sort order): walk adjacent pairs. If any adjacent pair has equal first-indexed-col values (ignoring rowid) AND neither is NULL: raise `STORAGE_UNIQUE_BACKFILL_VIOLATION { index, key }`. The index is NOT created; schema state reverts to pre-CREATE.
- NULL-keyed cells are skipped from the duplicate check (multiple NULLs are permitted).

**Error addition:** `STORAGE_UNIQUE_BACKFILL_VIOLATION { index, key }` is a new `CreateIndex` error when `unique = true`.

### No changes to invariants

Invariants 1–42 remain. `max_invariant = 42` unchanged. The UNIQUE flag is a catalog concern, not a VDBE-program-structure concern.
