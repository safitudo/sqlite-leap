---
name: compiler/constraints
kind: leaf
inherits:
  - /parts/compiler/parts/expressions/master.md
  - /parts/storage/master.md
  - /parts/vdbe/parts/opcodes-rows/master.md
emits:
  c: { path: src-c/compiler/constraints.c, headers: [src-c/compiler/constraints.h] }
  rust: { path: src-rust/src/compiler/constraints.rs }
---

# Part: compiler/constraints

Emits enforcement opcodes for table constraints: NOT NULL, UNIQUE,
PRIMARY KEY (integer and composite), CHECK, GENERATED columns,
STRICT tables.

## Public interface

```
compile_insert_constraints(
    table_schema: &TableSchema<'src>,
    row_regs:     &[Register],
    ctx:          &CompileContext,
    program_out:  &mut ProgramBuilder,
) -> Result<(), CompileError>

compile_update_constraints(
    table_schema: &TableSchema<'src>,
    updated_cols: &[ColumnIndex],
    row_regs:     &[Register],
    ctx:          &CompileContext,
    program_out:  &mut ProgramBuilder,
) -> Result<(), CompileError>
```

Called by INSERT, UPDATE, UPSERT statement sub-parts before
emitting the row-mutation opcode.

## Constraint enforcement

- **NOT NULL** — emit `NotNull(reg)` check; on violation raise
  `RUNTIME_CONSTRAINT_NOT_NULL`.
- **UNIQUE / PRIMARY KEY** — emit a pre-insert index probe on the
  relevant unique index; on hit raise `RUNTIME_CONSTRAINT_UNIQUE`.
  Conflict strategy (REPLACE/IGNORE/ABORT) controls the action;
  default ABORT raises the condition. REPLACE converts to an
  UPDATE of the existing row (delegated to parts/upsert/ via
  shared helper).
- **CHECK** — compile the CHECK expression in a scope restricted to
  the row's columns. On false, raise
  `RUNTIME_CONSTRAINT_CHECK`.
- **GENERATED** (virtual/stored) — compute the generated expression
  and write the result to the corresponding column slot. STORED
  gens participate in uniqueness; VIRTUAL gens are recomputed on
  read.
- **STRICT** — type enforcement: column values must match declared
  affinity exactly. Violations raise `RUNTIME_CONSTRAINT_TYPE`.

## Phase pins

- **Phase 6am** — NOT NULL column constraints.
- **Phase 6at** — CHECK constraints.
- **Phase 6au** — multi-column table-level constraints.
- **Phase 6bi** — STRICT tables (type enforcement).
- **Phase 6bj** — GENERATED virtual columns.
- **Phase 9g** — UNIQUE enforcement (index probe).
- **Phase 9c** — DML maintenance (INSERT/UPDATE/DELETE keep indexes
  live — this sub-part emits the index-update opcodes).

## Regeneration envelope

- Target leaf size: 500–800 lines per target.
- Spec < 150 lines.
