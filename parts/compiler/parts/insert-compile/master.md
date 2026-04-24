---
name: insert-compile
kind: leaf
emits:
  rust: { path: src-rust/compiler/insert_compile.rs }
  c:    { path: src-c/compiler/insert_compile.c, headers: [src-c/compiler/insert_compile.h] }
---

# INSERT → VDBE compiler

Compiles a parsed `InsertStmt` + caller-supplied `TableSchema` into VDBE
opcodes that open a write cursor, emit each row's values into a fresh
register range, and issue an `InsertRow` opcode per row. The DML mirror
to `select-compile` — proves the statement-compiler pattern handles
write paths, not just SELECT.

## Scope

Admitted:
- `INSERT INTO t VALUES (...), (...), ...` (no column list — every row
  must supply `schema.columns.len()` values in schema order).
- `INSERT INTO t (c1, c2, ...) VALUES (...), (...), ...` — each row
  supplies exactly `stmt.columns.len()` values; columns may be a
  subset of the table columns, in any order.
- Each value expression goes through `compile_expr` for literal subtrees
  (no Col references in INSERT values for the probe — user supplies
  constants or pure-literal expressions).

Deferred (CompileError `"deferred: <construct>"`):
- OR-conflict clauses, RETURNING, DEFAULT substitution.
- `INSERT ... SELECT` (requires a source query).
- Col references inside value expressions (a value depending on another
  row's column is out of scope).
- Constraint enforcement (NOT NULL, UNIQUE, CHECK, FK).

## Declared shapes (in `shapes.json`)

- `CompileInsertOk { opcodes, num_registers, num_cursors, rows_affected }`
- `compile_insert(stmt, schema) -> result<CompileInsertOk, CompileError>`
  (imports `CompileError` from `/parts/compiler/parts/expr-compile`,
  `TableSchema`/`ColumnSchema` from `/parts/compiler/parts/select-compile`).

## Algorithm

```
compile_insert(stmt, schema):
    if stmt.table != schema.name: CompileError "table name mismatch"
    # validate arity per row
    expected_arity = stmt.columns.len() if stmt.columns else schema.columns.len()
    for row in stmt.rows:
        if row.values.len() != expected_arity:
            CompileError "value count does not match column count"
    # validate named column subset, if present
    if stmt.columns:
        for c in stmt.columns:
            if schema has no column named c (case-insensitive ASCII):
                CompileError "unknown column: <c>"
    # emit opcodes:
    OpenWrite { cursor: 0, table: schema.name }
    reg_base = 0
    max_reg = 0
    for row in stmt.rows:
        # compile each value into consecutive registers
        current_reg = reg_base
        for v in row.values:
            ok = compile_expr(v, Register(current_reg))
            current_reg = ok.next_reg.0 (after the expression's allocation)
            code.extend(ok.code)
        count = expected_arity
        InsertRow {
            cursor: 0,
            column_names: if stmt.columns then Some(...) else None,
            start_reg: Register(reg_base),
            count,
        }
        max_reg = max(max_reg, current_reg)
    Close { cursor: 0 }
    Halt
    # Result:
    num_registers = max_reg
    num_cursors = 1
    rows_affected = stmt.rows.len()
```

Reg_base is fixed at 0 for every row (the registers are reused across
rows). `max_reg` tracks the highest register-index used by any row's
compile (so `num_registers` is always an upper bound).

## Correctness pins

1. **Minimal insert** — `INSERT INTO t VALUES (1)` with schema
   `t(a INT)` emits `[OpenWrite, LoadConst(r0,1), InsertRow(cursor=0,
   column_names=None, start_reg=r0, count=1), Close, Halt]`.
2. **Multi-row** — `INSERT INTO t VALUES (1), (2), (3)` emits three
   InsertRow opcodes (same cursor, same start_reg=0, count=1 each).
   `rows_affected = 3`.
3. **Multi-col** — `INSERT INTO t (a, b) VALUES (1, 2)` with schema
   `t(a INT, b INT)` emits values into consecutive registers and an
   InsertRow with `count=2` + `column_names = Some([&"a", &"b"])`.
4. **Expression values** — `INSERT INTO t VALUES (1+2, 'x'||'y')`
   emits BinOp for each value expr and passes the final register of
   each subtree into InsertRow's start_reg window.
5. **Arity mismatch** — `INSERT INTO t (a,b) VALUES (1)` → CompileError
   `"value count does not match column count"`. Detected before any
   opcode emission (validates pre-flight).
6. **Unknown column** — `INSERT INTO t (zz) VALUES (1)` with schema
   `t(a)` → CompileError `"unknown column: zz"`.
7. **Table-name mismatch** — compiler is caller-supplied; if
   `stmt.table != schema.name`, emit CompileError
   `"table name mismatch"` rather than silent-renaming.
8. **rows_affected accuracy** — equals `stmt.rows.len()`; the caller
   uses this to seed the reporting of affected-row-count.
9. **Opcode sequence ordering** — OpenWrite first, Close second-to-last,
   Halt last. Between OpenWrite and Close: N repetitions of
   `<value expression compile> + InsertRow`.
10. **Register bound** — `num_registers` is >= the highest register
    index used by any emitted opcode. Off-by-one is a pin.
11. **Single cursor** — `num_cursors = 1`.
12. **Column name borrowing** — when `stmt.columns` is non-empty,
    the emitted InsertRow.column_names carries `&'src str` slices
    pointing into the parser AST's owned column strings. The compile
    uses the source lifetime correctly (per memory-discipline spec).
13. **No inline tests, no invented opcodes** — only imported
    opcodes used; `compile_expr` called unchanged. Halt terminates.

## Regeneration envelope

- Line budget: **~200-320 lines** of Rust / **~300-500 lines** of C.
- No dependencies beyond std.
- Public items: `CompileInsertOk`, `compile_insert`.

## Smoke probe

`src-rust/examples/insert_compile_smoke.rs` (hand-written, leaplint:
runner) is extended from the select-behavioral smoke. It:

1. Constructs an empty Database.
2. Installs a table `t` with schema `t(a INT, b TEXT)` and zero rows.
3. Parses + compiles `INSERT INTO t VALUES (1, 'a'), (2, 'b')`.
4. Executes the program (needs a mem-store write path — see
   `/parts/storage/parts/mem-store-writable`, coming after this leaf).
5. Subsequently parses + compiles `SELECT * FROM t`.
6. Executes and asserts the collected rows are `[[1,'a'], [2,'b']]`.

Until mem-store-writable lands, the structural probe stands in: assert
the emitted InsertRow opcodes have the expected (`count`, `start_reg`)
pairs and the sequence (`OpenWrite`, N × `<values> + InsertRow`,
`Close`, `Halt`) in order.
