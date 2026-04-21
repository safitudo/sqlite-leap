# Part: vdbe

Executes a compiled VDBE Program against storage per `spec/vdbe-interpreter.spec.md`.

## Contract

- **Inputs:**
  - `program` — a Program (`schema/program.schema.json`). Assumed well-formed (the compiler is the warranty).
  - `storage_handle` — a mutable reference to a Database.
- **Output on success:** a Result (`schema/result.schema.json`).
- **Output on failure:** any `STORAGE_*` error propagated verbatim from a storage op invoked by an opcode (`OpenRead`, `OpenWrite`, `InsertRow`, `CreateTable`).

## Required behaviour

The VDBE MUST:

- Initialise state per `spec/vdbe-interpreter.spec.md` § "Interpreter state"
- Execute the main loop per that spec's § "Main loop"
- Honour cursor lifecycle rules (closed → open-unpositioned → open-positioned-on-i → open-past-end → closed)
- Honour register lifecycle (initialised to NULL; written by `LoadConst`/`Column`; read by `ResultRow`/`InsertRow`)
- Terminate on `Halt` and return `{"rows": result_rows}`
- Terminate on any `STORAGE_*` error and propagate the error unchanged (same `name`, same `fields`)
- Emit deterministic results across repeated invocations with identical input — no randomness, no time-dependence

The VDBE MUST NOT:

- Re-validate program well-formedness (the compiler is responsible; re-validation is waste and invites scope creep)
- Mutate the Program during execution
- Invent new opcodes or ignore unknown opcodes silently — any opcode in a well-formed program is one of the 12 defined in `spec/vdbe-opcodes.spec.md`
- Inspect storage internals directly; all interaction goes through the storage part's public ops

## Dispatch strategy

Target-defined. Valid choices include:

- A `switch` / `match` statement on `opcode.op`
- A function-pointer or trait-object dispatch table
- Tagged-enum dispatch in languages with discriminated unions
- Computed goto / threaded dispatch (not required in Phase 2b; Phase 3 benchmarking may revisit)

Dispatch choice does not affect correctness — only performance. Phase 2b is correctness-only; Phase 3 benchmarks dispatch.

## Part independence

Depends on:

- `spec/vdbe-opcodes.spec.md`
- `spec/vdbe-interpreter.spec.md`
- `spec/storage.spec.md` (for STORAGE_* error names to propagate)
- `schema/program.schema.json`, `schema/opcode.schema.json`, `schema/value.schema.json`, `schema/result.schema.json`
- The storage part's full public API (mutating ops included: `insert_row`, `create_table`; read ops: `select_all`, `select_columns`). Note that `OpOpenRead`/`OpOpenWrite`/`Column`/`Rewind`/`Next` are implemented by the VDBE against the storage part's exposed cursor-like primitives; storage is responsible for offering whatever cursor abstraction the VDBE needs. In Phase 2b, a minimal storage surface is sufficient: the VDBE may ask for a cloneable iterator over a table's rows, which the storage target implements against its internal row list.

## Phase 2c-1 note

Phase 2c-1 adds 11 opcodes (arithmetic: `Add`, `Subtract`, `Multiply`, `Divide`; unary `Negate`; comparison: `Eq`, `Ne`, `Lt`, `Le`, `Gt`, `Ge`) plus two new runtime error conditions (`EVAL_TYPE_ERROR`, `EVAL_DIVISION_BY_ZERO`). See `spec/vdbe-opcodes.spec.md` § "Phase 2c-1 opcodes" for semantics.

All new opcodes follow NULL-propagation (any NULL operand produces NULL). Type errors raise `EVAL_TYPE_ERROR` with fields describing the operator and operand types. These errors propagate identically to existing `STORAGE_*` errors — same halt-and-return behaviour, same verbatim `name` + `fields`.

## Phase 2c-2 note

Phase 2c-2 adds 4 opcodes: `And`, `Or`, `Not` (logical operators with SQL 3VL semantics), and `JumpIfFalse` (conditional PC jump, used to implement the WHERE clause).

`And` / `Or` / `Not` follow SQL 3VL — the classic truth tables in which `NULL` represents an UNKNOWN truth value. The logical operators do NOT short-circuit: the VDBE always reads both operands (or the single operand for `Not`). Any TEXT operand raises `EVAL_TYPE_ERROR` with the appropriate `op` name.

`JumpIfFalse` inspects a single register and either falls through (INTEGER non-zero) or jumps (INTEGER 0 or NULL). A TEXT value in the cond register raises `EVAL_TYPE_ERROR` with `op = "WHERE"` and `operand_type = "TEXT"`. Other callers (hypothetical future phases) might raise with a different `op`; Phase 2c-2 only compiles WHERE clauses into `JumpIfFalse`.

The VDBE's error-propagation rule is unchanged: any `EVAL_TYPE_ERROR` halts execution and returns the error unchanged (same `name`, same `fields`).

## Phase 2c-3 note

Phase 2c-3 adds 2 opcodes: `UpdateRow` and `DeleteRow`. Both operate through a write cursor that is currently positioned on a live row.

`UpdateRow` invokes `storage.update_row_at_cursor(cursor, column_names, values)` and may propagate `STORAGE_COLUMN_NOT_FOUND`, `STORAGE_DUPLICATE_COLUMN`, or `STORAGE_TYPE_MISMATCH` (typically only TYPE_MISMATCH at runtime — duplicate-column and column-not-found are normally caught at compile time; if they arise at runtime it indicates an ill-formed program).

`DeleteRow` invokes `storage.delete_row_at_cursor(cursor)` — no errors, the storage abstraction handles tombstone bookkeeping.

After `DeleteRow`, the cursor is still positioned on the slot but the row is tombstoned. `Next` advances past it automatically (skipping tombstones). `Column` after `DeleteRow` is undefined behaviour; the compiler's recipes never emit it.

Both UPDATE and DELETE produce `{"rows": []}` on success — no result rows.

## Output location

Generated code lives in `src-{lang}/vdbe/`. Exposes exactly one public entry point that accepts `(program, storage_handle)` and returns a Result or the named error.
