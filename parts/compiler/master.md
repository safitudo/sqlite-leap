# Part: compiler

Consumes an AST and produces a well-formed VDBE Program per `spec/vdbe-opcodes.spec.md`.

## Contract

- **Inputs:**
  - `ast` — an AST node (`schema/ast.schema.json`)
  - `storage_handle` — an opaque read-only reference to a Database. The compiler reads table schemas but MUST NOT mutate storage.
- **Output on success:** a Program (`schema/program.schema.json`) satisfying every well-formedness invariant in `spec/vdbe-opcodes.spec.md` § "Well-formedness".
- **Output on failure:** one of the schema-lookup error conditions `STORAGE_TABLE_NOT_FOUND`, `STORAGE_COLUMN_NOT_FOUND`, `STORAGE_DUPLICATE_COLUMN`, propagated verbatim (same `name`, same `fields`) from the storage part.

Each language target represents "success or failure" in its own idiomatic way.

## Required behaviour

The compiler MUST:

- Always produce well-formed programs. This is the single most important guarantee of this part; the VDBE relies on it.
- Resolve column names to 0-based column indices at compile time by querying the storage part for the target table's schema. This applies to `SelectFrom` with `projection.kind == "Columns"` and to `Insert` with `column_names != null`.
- Allocate a minimal but sufficient number of registers (typically the number of values/columns present in the statement) and cursors (one per referenced table; Phase 2b statements reference at most one table).
- Emit exactly one `OpHalt` as the final opcode of every program.
- Translate `Literal` AST nodes to Values using the identity mapping (`IntegerLiteral(v) → integer Value v`, `StringLiteral(v) → text Value v`, `NullLiteral → NULL Value`).
- Preserve case of identifier strings exactly as they appeared in the AST.
- For `Insert` with a column list containing duplicates, raise `STORAGE_DUPLICATE_COLUMN` at compile time. (The storage layer also checks this; compile-time detection is preferred because it matches SQLite's behaviour and yields a better stage for the error.)

The compiler MUST NOT:

- Call any mutating storage op (`insert_row`, `create_table`) — those happen at runtime inside the VDBE via opcodes.
- Execute or simulate any part of the program.
- Invent new opcodes outside the 12 defined in `spec/vdbe-opcodes.spec.md`.
- Emit ill-formed programs (out-of-range register indices, dangling jump targets, missing `Halt`, empty opcode list).
- Perform optimisations that would invalidate the compilation recipes below for a statement beyond register numbering. Phase 2b explicitly defers optimisation to later phases.

## Compilation recipes

These recipes are the reference translation of each AST kind. A generator MAY produce structurally different programs (e.g., different register indices) provided they pass the test suite AND satisfy well-formedness. Register and cursor indices below are illustrative; any valid contiguous allocation works.

### `CreateTable` AST

```
opcodes:
  [0] CreateTable(table = ast.table, columns = ast.columns)
  [1] Halt
num_registers: 0
num_cursors:   0
```

No schema lookup happens — the table does not yet exist.

### `Insert` AST (no column list)

Let `n = |ast.values|`.

```
opcodes:
  [0]    OpenWrite(cursor = 0, table = ast.table)
  [1..n] LoadConst(dest = i, value = translate(ast.values[i]))       for i in 0..n-1
  [n+1]  InsertRow(cursor = 0, column_names = null, start = 0, count = n)
  [n+2]  Close(cursor = 0)
  [n+3]  Halt
num_registers: n
num_cursors:   1
```

The `OpenWrite` at PC 0 may raise `STORAGE_TABLE_NOT_FOUND` at runtime, not compile time — the compiler does NOT validate table existence for INSERT-without-column-list (keeps the compilation trivial; storage catches it at OpenWrite).

### `Insert` AST (with column list)

Let `n = |ast.values|`, `names = ast.column_names`. At compile time, check in this precedence order (first match wins):

1. Query storage for `ast.table`'s schema. If the table does not exist, raise `STORAGE_TABLE_NOT_FOUND`.
2. For each `name` in `names` (left-to-right), confirm it is a column of the table. The first offending name raises `STORAGE_COLUMN_NOT_FOUND`.
3. Scan `names` left-to-right for a duplicate (case-sensitive). The first repeated name raises `STORAGE_DUPLICATE_COLUMN`.

If all checks pass, emit the same opcode skeleton as the no-column-list form, but with `column_names = names` on the `InsertRow`.

Rationale: the precedence COLUMN_NOT_FOUND > DUPLICATE_COLUMN mirrors the storage-layer precedence in `spec/storage.spec.md` § `insert_row`, keeping cross-build error surfaces identical regardless of whether the check happens at compile time (Phase 2b) or at runtime (Phase 2a).

### `Select` AST (projection.kind = "Star", table != null)

Note: as of Phase 2c-1, `SelectLiteral` and `SelectFrom` are retired; the unified `Select` kind replaces them. The recipes below enumerate all four combinations.

1. Query storage for `ast.table`'s schema. If missing, raise `STORAGE_TABLE_NOT_FOUND`.
2. Let `k = |table.columns|`. Emit:

```
opcodes:
  [0]            OpenRead(cursor = 0, table = ast.table)
  [1]            Rewind(cursor = 0, jump_if_empty = k + 4)
  [2..k+1]       Column(cursor = 0, column = i, dest = i)                for i in 0..k-1
  [k+2]          ResultRow(start = 0, count = k)
  [k+3]          Next(cursor = 0, jump_if_more = 2)
  [k+4]          Close(cursor = 0)
  [k+5]          Halt
num_registers: k
num_cursors:   1
```

Star projection with `table == null` is rejected by the parser (`star-projection` grammar rule requires `FROM`); the compiler never sees it.

### `Select` AST (projection.kind = "Expressions", table == null)

No-FROM SELECT with an expression list. Let `n = |projection.expressions|`.

1. Compile each expression `expr_i` to a program fragment that writes its value to register `dest_i`. (See "Expression compilation" below.) The ith expression must not reference any `ColumnRef` — if it does, raise `EVAL_COLUMN_WITHOUT_TABLE` (first offending name, leftmost expression in projection; within an expression, leftmost column-ref in in-order traversal).
2. Each fragment uses `dest_i = i` as its top-level output register. Subexpressions use registers `n, n+1, n+2, …` in postorder.
3. Emit the concatenation of fragments, then `ResultRow(start = 0, count = n)`, then `Halt`.
4. `num_registers` is the highest register index used plus one. `num_cursors = 0`.

### `Select` AST (projection.kind = "Expressions", table != null)

Expression list over rows of a table.

1. Query storage for `ast.table`'s schema. If missing → `STORAGE_TABLE_NOT_FOUND`.
2. For each expression `expr_i` in `projection.expressions`, resolve any `ColumnRef` to its 0-based column index within `table.columns`. If any name is not a column → `STORAGE_COLUMN_NOT_FOUND` (leftmost offending reference wins — order is: projection element left-to-right, then within each expression, left-most in-order traversal). Duplicate `ColumnRef`s in projection are allowed (matches SQLite's `SELECT a, a FROM t`).
3. Compile each expression. Top-level output registers are `0 .. n-1`. Subexpressions use registers `n, n+1, …` in postorder. `ColumnRef` compiles to a single `Column(cursor = 0, column = idx, dest = top)` emitted inside the per-row loop body.
4. Wrap the fragments in the standard row-loop skeleton:

```
opcodes:
  [0]                OpenRead(cursor = 0, table = ast.table)
  [1]                Rewind(cursor = 0, jump_if_empty = CLOSE_PC)
  ... per-row loop body (expression fragments producing regs 0..n-1) ...
  [ROWEND]           ResultRow(start = 0, count = n)
  [ROWEND+1]         Next(cursor = 0, jump_if_more = 2)
  [CLOSE_PC]         Close(cursor = 0)
  [CLOSE_PC+1]       Halt
```

`num_cursors = 1`. `num_registers` is the highest register index used plus one.

## Expression compilation (Phase 2c-1)

The compiler translates each `Expression` into a sequence of opcodes that leaves the result in a chosen `dest` register. The recursion is postorder: compile children first, pick fresh registers for their results, then emit the top-level opcode.

Register allocation strategy: fresh registers, never reused. This makes the register count equal to the number of internal AST nodes plus inputs, which is a tight upper bound. More sophisticated allocation is explicitly deferred to later phases.

Translation:

- `Literal(v)` at `dest` → emit `LoadConst(dest, translate(v))`.
- `ColumnRef(name)` at `dest` → resolve `name` to column index `c` in the enclosing table; emit `Column(cursor = 0, column = c, dest)`. If the enclosing Select has `table == null`, raise `EVAL_COLUMN_WITHOUT_TABLE` (compile time).
- `BinaryOp(op, L, R)` at `dest` → pick fresh registers `lhs_reg`, `rhs_reg`; compile `L` at `lhs_reg`; compile `R` at `rhs_reg`; emit the corresponding opcode (`Add` / `Subtract` / `Multiply` / `Divide` / `Eq` / `Ne` / `Lt` / `Le` / `Gt` / `Ge`) with `dest`, `lhs = lhs_reg`, `rhs = rhs_reg`.
- `UnaryOp("-", E)` at `dest` → pick fresh register `src_reg`; compile `E` at `src_reg`; emit `Negate(dest, src = src_reg)`.

Every per-row expression sequence lives inside the Rewind/Next loop; the `Column` opcodes inside reads fresh values from the cursor on each iteration. Literal-only and BinaryOp-over-literals fragments are stable per-iteration (same constants every row) but MUST still execute each iteration — Phase 2c-1 does not hoist invariants out of loops (deferred optimisation).

### Updated compiler error surface (Phase 2c-1)

In addition to the existing `STORAGE_TABLE_NOT_FOUND`, `STORAGE_COLUMN_NOT_FOUND`, `STORAGE_DUPLICATE_COLUMN`, the compiler may raise:

- `EVAL_COLUMN_WITHOUT_TABLE` — a `ColumnRef` appears in a Select with `table == null`. Fields: `column`.

## Phase 2c-2 compilation additions (WHERE, AND / OR / NOT)

Phase 2c-2 extends expression compilation and the `Select` emission recipe. It does NOT add new compiler-level error names; it DOES extend the set of runtime `EVAL_TYPE_ERROR` `op` values the compiled program may produce.

### Expression compilation — logical operators

- `BinaryOp(op="AND", L, R)` at `dest` → compile `L` at fresh `lhs_reg`, `R` at fresh `rhs_reg`, emit `And(dest, lhs=lhs_reg, rhs=rhs_reg)`.
- `BinaryOp(op="OR", L, R)` at `dest` → same shape, emit `Or`.
- `UnaryOp(op="NOT", E)` at `dest` → compile `E` at fresh `src_reg`, emit `Not(dest, src=src_reg)`.

The fresh-register allocation convention from Phase 2c-1 is unchanged. Logical operators are evaluated postorder just like arithmetic; no short-circuit emission.

### `Select` with `where != null`

WHERE is a gating expression applied per row inside the row-loop. The recipe extends the Phase 2c-1 "Expressions + FROM" skeleton by inserting the WHERE fragment and a `JumpIfFalse` between the per-row projection fragments and `ResultRow`. One valid lowering:

```
opcodes:
  [0]                OpenRead(cursor = 0, table = ast.table)
  [1]                Rewind(cursor = 0, jump_if_empty = CLOSE_PC)
  ... WHERE expression fragment, producing register W ...
  [JIF_PC]           JumpIfFalse(cond = W, target = NEXT_PC)
  ... per-row projection fragments producing regs 0..n-1 ...
  [ROWEND]           ResultRow(start = 0, count = n)
  [NEXT_PC]          Next(cursor = 0, jump_if_more = 2)
  [CLOSE_PC]         Close(cursor = 0)
  [CLOSE_PC+1]       Halt
```

Key constraints:

1. The WHERE fragment MUST be emitted before the projection fragments — this keeps the per-iteration work minimal (short-circuit on row rejection). An implementation MAY emit projection-first and WHERE-second; the tests accept any lowering that produces the same observable rows, but the recipe above is canonical.
2. `JumpIfFalse.target` MUST equal the PC of `Next` (NOT `Close`). Jumping to `Close` would abort the scan prematurely. The compiler performs forward-patching of this target once `NEXT_PC` is known.
3. When `Select.projection.kind == "Star"` AND `where != null`, the compiler still must expand the column list for projection (same as the Star recipe in 2c-1) AND emit the WHERE gate before the Column reads for projection. A valid lowering:

```
opcodes:
  [0]              OpenRead(cursor = 0, table = ast.table)
  [1]              Rewind(cursor = 0, jump_if_empty = CLOSE_PC)
  ... WHERE expression fragment ...
  [JIF_PC]         JumpIfFalse(cond = W, target = NEXT_PC)
  [..]             Column(cursor = 0, column = i, dest = i)   for i in 0..k-1
  [ROWEND]         ResultRow(start = 0, count = k)
  [NEXT_PC]        Next(cursor = 0, jump_if_more = 2)
  [CLOSE_PC]       Close(cursor = 0)
  [CLOSE_PC+1]     Halt
```

4. Registers used by the WHERE fragment and by projection MAY overlap or MAY be disjoint (target-defined). The canonical strategy is "disjoint": projection uses registers `0..n-1`, WHERE uses `n, n+1, …`. Fresh allocation never reuses registers within a single compiled program, so the two ranges are naturally disjoint.

5. When `Select.where` references a column of the FROM'd table, the `ColumnRef` inside WHERE is resolved just like in projection (same `STORAGE_COLUMN_NOT_FOUND` path, same `EVAL_COLUMN_WITHOUT_TABLE` rule — though the grammar already forbids WHERE without FROM, so `EVAL_COLUMN_WITHOUT_TABLE` cannot arise from WHERE at the AST level Phase 2c-2 produces).

### Column-resolution order when WHERE is present

During compile-time schema resolution:

1. Query storage for `ast.table`'s schema. Missing → `STORAGE_TABLE_NOT_FOUND`.
2. Resolve every `ColumnRef` in `projection` (leftmost in-order) — first offending → `STORAGE_COLUMN_NOT_FOUND`.
3. Resolve every `ColumnRef` in `where` (in-order traversal of the WHERE expression tree) — first offending → `STORAGE_COLUMN_NOT_FOUND`.

Projection resolution precedes WHERE resolution. A well-formed test that exercises both an unknown projection column and an unknown WHERE column will observe the projection's error. This precedence matches the source-order of the clauses in a SELECT statement.

### Phase 2c-2 compiler error surface

No new error names. Existing names apply: `STORAGE_TABLE_NOT_FOUND`, `STORAGE_COLUMN_NOT_FOUND`, `STORAGE_DUPLICATE_COLUMN`, `EVAL_COLUMN_WITHOUT_TABLE`. The compiled program may emit (at runtime) any `EVAL_TYPE_ERROR` shape, now including `op ∈ {"AND", "OR", "NOT", "WHERE"}` in addition to the 2c-1 shapes.

## Phase 2c-3 compilation — UPDATE and DELETE

Phase 2c-3 adds two top-level AST kinds (`Update`, `Delete`) and two new opcodes (`UpdateRow`, `DeleteRow`). Same register-allocation conventions; same error-precedence rules. UPDATE and DELETE produce an empty result (`{"rows": []}`).

### Compile-time schema resolution (UPDATE)

For an `Update { table, assignments, where }` AST, the compiler checks in this precedence order:

1. Query storage for `table`'s schema. Missing → `STORAGE_TABLE_NOT_FOUND`.
2. For each `assignment.column` in list-order: confirm it is a column of the table. First offending name → `STORAGE_COLUMN_NOT_FOUND`.
3. Scan `assignments` for a duplicate `column` name (case-sensitive). First repeated → `STORAGE_DUPLICATE_COLUMN` (leftmost of the repeated pair).
4. Resolve every `ColumnRef` in each `assignment.value` (assignments left-to-right, in-order traversal within each expression). First unknown → `STORAGE_COLUMN_NOT_FOUND`.
5. Resolve every `ColumnRef` in `where` (if present). First unknown → `STORAGE_COLUMN_NOT_FOUND`.

This precedence mirrors the Insert-with-column-list rule from Phase 2b and the Select-with-where rule from Phase 2c-2.

### Compile-time schema resolution (DELETE)

For a `Delete { table, where }` AST:

1. Table existence — `STORAGE_TABLE_NOT_FOUND`.
2. Resolve every `ColumnRef` in `where` (if present) — `STORAGE_COLUMN_NOT_FOUND` on first unknown.

### `Update` AST recipe

Let `n = |assignments|`. The canonical lowering:

```
opcodes:
  [0]              OpenWrite(cursor = 0, table = ast.table)
  [1]              Rewind(cursor = 0, jump_if_empty = CLOSE_PC)
  ... WHERE expression fragment (if present), producing register W ...
  [JIF_PC]         JumpIfFalse(cond = W, target = NEXT_PC)      -- omit if no WHERE
  ... assignment value fragments producing regs 0..n-1 ...
  [UPDATE_PC]      UpdateRow(cursor = 0, column_names = [c_1, ..., c_n], start = 0, count = n)
  [NEXT_PC]        Next(cursor = 0, jump_if_more = 2)
  [CLOSE_PC]       Close(cursor = 0)
  [CLOSE_PC+1]     Halt
```

Key constraints:

1. When `where == null`, the `JumpIfFalse` is omitted entirely; each row is unconditionally updated. The recipe therefore has two skeletal forms (with / without WHERE).
2. `assignment.value` fragments evaluate BEFORE `UpdateRow` runs. A `ColumnRef` inside `assignment.value` reads the row's CURRENT (pre-update) column value. All `n` expressions evaluate first, then `UpdateRow` applies the entire `n`-tuple atomically — so `UPDATE t SET a = b, b = a` swaps `a` and `b` correctly.
3. `UpdateRow.column_names` preserves the source order of the SET clause. `UpdateRow.start` / `count` reference the first `n` contiguous registers; subexpressions use fresh registers beyond `n-1`.
4. `num_cursors = 1`. `num_registers` = the highest register index used plus one.

### `Delete` AST recipe

```
opcodes:
  [0]              OpenWrite(cursor = 0, table = ast.table)
  [1]              Rewind(cursor = 0, jump_if_empty = CLOSE_PC)
  ... WHERE expression fragment (if present), producing register W ...
  [JIF_PC]         JumpIfFalse(cond = W, target = NEXT_PC)      -- omit if no WHERE
  [DEL_PC]         DeleteRow(cursor = 0)
  [NEXT_PC]        Next(cursor = 0, jump_if_more = 2)
  [CLOSE_PC]       Close(cursor = 0)
  [CLOSE_PC+1]     Halt
```

DELETE without WHERE deletes every row. The cursor's `Next` handles tombstone-skipping automatically — after `DeleteRow` the current slot is tombstoned; `Next` advances to the next live row or falls through at end.

`num_registers` can be `0` when `where == null` (DeleteRow/Next need no registers); otherwise it is the highest-used WHERE fragment register plus one. `num_cursors = 1`.

### Phase 2c-3 compiler error surface

No new error names. The compiler may raise: `STORAGE_TABLE_NOT_FOUND`, `STORAGE_COLUMN_NOT_FOUND`, `STORAGE_DUPLICATE_COLUMN` (UPDATE's SET-clause duplicates). `EVAL_COLUMN_WITHOUT_TABLE` is NOT raisable by UPDATE or DELETE because both always name a table.

The compiled program may emit, at VDBE runtime: `EVAL_TYPE_ERROR`, `EVAL_DIVISION_BY_ZERO`, `STORAGE_TYPE_MISMATCH` (UPDATE writeback only).

## Part independence

The compiler depends only on:

- `spec/sql-grammar.spec.md` (Phase 2b section for compilation semantics)
- `spec/vdbe-opcodes.spec.md` (the ISA it emits)
- `spec/storage.spec.md` (for STORAGE_* error names)
- `schema/ast.schema.json`, `schema/opcode.schema.json`, `schema/program.schema.json`, `schema/value.schema.json`
- The storage part's **read-only** operations (to resolve column indices). In practice this is the same handle the VDBE will run with; the compiler must treat it as read-only.

It does NOT depend on the VDBE, the executor, the tokenizer, or the parser.

## Implementation freedom

Internal data structures (an opcode buffer, a register counter, a column-index lookup) are target-defined. The compiler MAY walk the AST recursively, iteratively, or via a visitor pattern. Every valid implementation produces output that passes the test suite.

## Output location

Generated code lives in `src-{lang}/compiler/`. Exposes exactly one public entry point that accepts `(AST, storage_handle)` and returns a Program or the named error.
