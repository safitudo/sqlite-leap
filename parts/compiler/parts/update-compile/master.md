---
name: update-compile
kind: leaf
emits:
  rust: { path: src-rust/compiler/update_compile.rs }
  c:    { path: src-c/compiler/update_compile.c, headers: [src-c/compiler/update_compile.h] }
---

# UPDATE → VDBE compiler

Compiles `UpdateStmt` + `TableSchema` into VDBE opcodes that scan a
table, filter by WHERE, and rewrite matching rows via `UpdateRow`.
Combines select-compile's scan path with insert-compile's value
packing and column_names borrowing.

## Scope

Admitted:
- `UPDATE t SET col = expr[, ...] [WHERE expr]`.
- Each assignment's `expr` AND the WHERE may reference columns of
  `t` (resolved via `compile_expr_in_schema`).
- Column list in SET must only reference known columns
  (case-insensitive ASCII match).

Deferred (`CompileError "deferred: <construct>"`):
- Constraint checks (NOT NULL / UNIQUE / CHECK / FK).
- RETURNING, multi-table update, FROM clause, USING clause.

## Algorithm

```
# Register layout:
#   0..ncol-1       : scratch per-column read (via Column opcode)
#   ncol..          : WHERE predicate scratch
#   after WHERE     : assignment-value output window (packed)

# Validate: every SET column exists in schema.
for each assignment in stmt.assignments:
    if no schema column matches assignment.column (case-insensitive):
        CompileError "unknown column: <name>"

OpenWrite { cursor: 0, table: schema.name }
Rewind    { cursor: 0, jump_if_empty: END }

TOP:
    # load all row columns into scratch
    for col_idx in 0..schema.columns.len():
        Column { cursor: 0, col_idx, dest_reg: Register(col_idx) }
    if stmt.where_:
        cond = compile_expr_in_schema(where_, reg_base = ncol)
        IfNot { cond_reg: cond.result_reg, target: NEXT }
    # compile each assignment value into consecutive registers, packed
    values_base = <after WHERE scratch>
    cur = values_base
    for a in stmt.assignments:
        ok = compile_expr_in_schema(a.value, reg_base = cur)
        # pack into slot a.index by Copy if it didn't land there
        if ok.result_reg != Register(values_base + a.index): Copy
        cur = <after ok.next_reg>
    UpdateRow {
        cursor: 0,
        column_names: [Box::leak(a.column) for a in assignments],
        start_reg: Register(values_base),
        count: assignments.len(),
    }
NEXT:
    Next { cursor: 0, jump_if_more: TOP }
END:
    Close { cursor: 0 }
    Halt
```

For the probe: `UpdateRow`'s interpretation of `column_names` +
values is delegated to the storage layer. The current mem-store v3
doesn't yet handle UPDATE — a follow-up mem-store v4 will.

## Correctness pins

1. **Single-column update** — `UPDATE t SET a = 1` emits Column×ncol,
   compile_expr(1) → LoadConst, UpdateRow with count=1 + column_names=[&"a"].
2. **Multi-column update** — `UPDATE t SET a = 1, b = 2` emits two
   value compiles + UpdateRow count=2, column_names=[&"a", &"b"].
3. **With WHERE** — `UPDATE t SET a = 1 WHERE b = 2` adds
   compile_expr_in_schema(WHERE) + IfNot skipping UpdateRow when
   predicate false.
4. **Column in RHS** — `UPDATE t SET a = b + 1` compiles the RHS
   through compile_expr_in_schema so `Col(b)` resolves to scratch
   register (ncol-aware).
5. **Unknown column in SET** — `UPDATE t SET zz = 1` →
   CompileError `"unknown column: zz"`.
6. **Unknown column in WHERE** — same error path through
   compile_expr_in_schema.
7. **Table-name mismatch** — `stmt.table != schema.name` →
   CompileError `"table name mismatch"`.
8. **Empty table** — Rewind jumps past loop, straight to Close.
9. **Two-pass PC resolution** — no placeholder PCs.
10. **Single cursor** — `num_cursors = 1`.
11. **num_registers bound** — at least `schema.columns.len()` +
    WHERE scratch + assignments count.
12. **Halt at end** — final opcode is Halt.
13. **No inline tests, no invented opcodes** — same discipline as
    select/delete-compile.

## Regeneration envelope

- Line budget: **~200-320 lines** of Rust.
- No dependencies beyond std.
- Public items: `CompileUpdateOk`, `compile_update`.
