---
name: delete-compile
kind: leaf
emits:
  rust: { path: src-rust/compiler/delete_compile.rs }
  c:    { path: src-c/compiler/delete_compile.c, headers: [src-c/compiler/delete_compile.h] }
---

# DELETE → VDBE compiler

Compiles a parsed `DeleteStmt` + `TableSchema` into a VDBE opcode
sequence that scans the table, optionally filters by WHERE, and
deletes matching rows via `DeleteRow`. Mirrors `select-compile`'s
WHERE+scan path structurally.

## Scope

Admitted:
- `DELETE FROM t` — delete all rows.
- `DELETE FROM t WHERE <expr>` — filtered delete.
- WHERE can reference columns of `t` (resolved via the same
  `compile_expr_in_schema` helper used by select-compile, re-applied
  here).

Deferred (`CompileError "deferred: <construct>"`):
- RETURNING, constraint cascades, FK maintenance, DROP-style TRUNCATE,
  multi-table delete, USING clause.

## Algorithm

```
# Register layout:
#   0..ncol-1       : scratch per table column (via Column opcode)
#   ncol..          : WHERE predicate scratch

OpenWrite { cursor: 0, table: schema.name }
Rewind    { cursor: 0, jump_if_empty: END_LABEL }

TOP:
    # load all columns into scratch
    for col_idx in 0..schema.columns.len():
        Column { cursor: 0, col_idx, dest_reg: Register(col_idx) }
    if stmt.where_:
        cond = compile_expr_in_schema(where_, reg_base = ncol)
        IfNot { cond_reg: cond.result_reg, target: NEXT_LABEL }
    DeleteRow { cursor: 0 }
NEXT_LABEL:
    Next      { cursor: 0, jump_if_more: TOP }
END_LABEL:
    Close     { cursor: 0 }
    Halt
```

Two-pass PC resolution — same approach as select-compile.

**Cursor stability after DeleteRow:** the VDBE's DeleteRow
implementation must leave the cursor positioned such that the
following Next advances to what WOULD HAVE BEEN the next row. For
the mem-store probe, the cursor's `row_index` is updated so Next
does not skip; the storage implementation handles this correctly.

## Correctness pins

1. **No-WHERE delete all** — `DELETE FROM t` with two-row table emits
   `OpenWrite, Rewind, Column×ncol, DeleteRow, Next, Close, Halt`
   (no WHERE, no IfNot). All rows deleted.
2. **With-WHERE filter** — `DELETE FROM t WHERE a = 1` emits the
   same shape plus WHERE compile + IfNot skipping DeleteRow when the
   predicate is false.
3. **Unknown column in WHERE** — `DELETE FROM t WHERE zz = 1` →
   CompileError `"unknown column: zz"`.
4. **Table-name mismatch** — `stmt.table != schema.name` →
   CompileError `"table name mismatch"`.
5. **No matching rows** — `DELETE FROM t WHERE <never-true>` runs
   cleanly (Rewind entered loop, IfNot always skips, Next advances
   to end, Close, Halt). No panic, no error.
6. **Empty table** — `DELETE FROM t` on empty table: Rewind jumps
   past loop, straight to Close, Halt. No panic.
7. **Two-pass PC resolution** — no placeholder PCs remain in the
   emitted opcode list.
8. **Single cursor** — `num_cursors = 1`.
9. **num_registers bound** — at least `schema.columns.len() +
   WHERE scratch`.
10. **Halt at end** — final opcode is Halt.
11. **No inline tests, no invented opcodes** — only imported
    opcodes used; `compile_expr` called unchanged; column resolver
    reuses select-compile's `compile_expr_in_schema` helper
    (imported or re-implemented inline — either is acceptable for
    the probe).
12. **Deferred RETURNING** — if ever reached (parser should catch
    first), emit CompileError `"deferred: RETURNING"`.

## Regeneration envelope

- Line budget: **~150-250 lines** of Rust / **~250-400 lines** of C.
- No dependencies beyond std.
- Public items: `CompileDeleteOk`, `compile_delete`,
  `compile_delete_with_using`.

`compile_delete_with_using(stmt, target_schema, using_schema)` is the
two-table form. It opens a write cursor on `target_schema` and a read
cursor on `using_schema`, scans the cross product, evaluates WHERE
across the joined row, and DeleteRows on the target whenever the
predicate holds. Used by `slt_runner` and smoke examples. Errors as
declared in `shapes.json`: missing USING clause, table-name mismatch
on either side, RETURNING with USING (deferred). `compile_delete`
itself raises `"deferred: DELETE USING"` if invoked on a stmt where
`stmt.using` is set, so callers that admit USING-form DELETE must
dispatch to `compile_delete_with_using` explicitly.
