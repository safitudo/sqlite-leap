---
name: select-compile
kind: leaf
emits:
  rust: { path: src-rust/compiler/select_compile.rs }
  c:    { path: src-c/compiler/select_compile.c, headers: [src-c/compiler/select_compile.h] }
---

# SELECT → VDBE compiler

Compiles a parsed `SelectStmt` AST plus a caller-supplied `TableSchema`
into a sequence of VDBE opcodes that execute the query and invoke a
`ResultRow` callback for each row passing `WHERE`. This is the
**end-to-end structural probe**: parser output → compiler output →
VDBE executes → correct rows emitted. If this runs, every downstream
statement (INSERT, UPDATE, DELETE) follows the same recipe.

## Scope

Admitted:
- `SELECT [DISTINCT] projection FROM t WHERE expr LIMIT n OFFSET m`
- No-FROM SELECT (`SELECT 1 + 2`), which skips the cursor loop.
- Projection: `*` (expands to every column in the schema), `t.*`,
  `expr [AS alias]` — aliases don't affect codegen.
- `WHERE` is evaluated per row; rows that don't pass are skipped.
- `LIMIT`/`OFFSET` honored by a counter register + branch.
- **Single-group aggregation**: queries with aggregate calls in the
  projection list and EITHER no `GROUP BY` clause OR a `GROUP BY`
  whose values collapse to a single group at compile time (only the
  no-GROUP-BY form is exercised in the probe). Aggregate kinds:
  `count_star`, `count` (1-arg), `count_distinct`, `sum`, `total`,
  `avg`, `min`, `max`, `group_concat`. Lifecycle is
  AggReset → per-row AggStep → AggFinal → ResultRow.
- **HAVING in single-group mode**: the post-aggregation predicate is
  evaluated against AggValue/AggFinal results before EmitRow. If
  HAVING is false, no row is emitted.
- `DISTINCT` (top-level SELECT DISTINCT) is deferred (needs de-dup
  set opcodes).

Deferred (CompileError `"deferred: <construct>"`):
- **Multi-group aggregation** — `GROUP BY` with more than one
  potential group. **SPEC GAP**: opcodes-agg / VdbeState provide
  one accumulator per slot (no per-group keying); storage exposes
  no ephemeral btree / hash table opcode; there is no `Sort` opcode
  for sort-then-streaming-group. Multi-group requires one of:
  (a) ephemeral-table opcode family (`OpenEphemeral`, hash insert
  with key, iterate distinct keys), or (b) `Sort` opcode + group-break
  detection. Either is a new opcode family + storage primitive.
  Until a follow-up adds one, multi-group `GROUP BY` produces
  CompileError `"deferred: multi-group GROUP BY (spec gap: needs
  ephemeral-table or Sort opcode family)"`.
- JOINs, subqueries, ORDER BY, top-level DISTINCT, compound SELECT,
  CTE, window functions.

## Declared shapes (in `shapes.json`)

- `ColumnSchema { name: string, index: u32 }`
- `TableSchema { name: string, columns: list<ColumnSchema> }`
- `CompileSelectOk { opcodes, num_registers, num_cursors,
   num_aggregates, result_count }`
- `compile_select(stmt, schema) -> result<CompileSelectOk, CompileError>`
  (imports `CompileError` from `/parts/compiler/parts/expr-compile`.)

## Algorithm overview

Two forms:

### A. No-FROM SELECT (e.g. `SELECT 1+2`)

```
for each projection item (must not be Star/TableStar — flag deferred):
    compile_expr(item.expr) into reg_N..
ResultRow { start_reg, count }
Halt
```

### B. Single-table SELECT (`SELECT ... FROM t [WHERE ...] [LIMIT ...]`)

```
# Register layout, starting at 0:
#   0..ncol-1          : column scratch registers (one per table column)
#   ncol..              : projection output registers
#   last..              : WHERE scratch, LIMIT counters

# Opcode plan:
OpenRead   { cursor: 0, table: schema.name }
Rewind     { cursor: 0, jump_if_empty: END_LABEL }

TOP:
    Column { cursor: 0, col_idx: 0, dest_reg: Register(0) }    # per column
    ...                                                        # ncol times
    (optionally WHERE:)
    cond_code = compile_expr(where_, reg_base = ncol + proj_count + extra)
    IfNot { cond_reg: cond_reg, target: NEXT_LABEL }
    (projection:)
    proj_code = compile_expr(each projection item) into consecutive registers
    ResultRow { start_reg: <first proj>, count: proj_count }
    (LIMIT:)
    (bump counter, branch to END if reached)

NEXT_LABEL:
    Next { cursor: 0, jump_if_more: TOP }

END_LABEL:
    Close  { cursor: 0 }
    Halt
```

PC targets are resolved by a two-pass compile: emit with placeholder
PCs and patch after the opcode list length is known, OR track labels
and resolve in a second pass over the opcode list.

### C. Single-group aggregation (`SELECT count(*) FROM t`, `SELECT sum(age) FROM t`, with optional HAVING but no GROUP BY)

Detect aggregation mode by walking projection + HAVING + ORDER BY
and collecting aggregate `Call` nodes. An aggregate call is one
whose `name` (case-insensitive ASCII) is in the set
`{count, count_star, count_distinct, sum, total, avg, min, max,
  group_concat}`. The set of distinct aggregate-call instances
(by reference identity in the AST walk) becomes the slot list:
slot 0 → first encountered call, slot 1 → second, etc.
`num_aggregates` = slot list length.

Aggregate-kind mapping (compiler-internal):
- `count_star`     → `AggFuncKind::CountStar`     (0 args)
- `count`          → `AggFuncKind::Count`         (1 arg)
- `count_distinct` → `AggFuncKind::CountDistinct` (1 arg)
- `sum`            → `AggFuncKind::Sum`           (1 arg)
- `total`          → `AggFuncKind::Total`         (1 arg)
- `avg`            → `AggFuncKind::Avg`           (1 arg)
- `min`            → `AggFuncKind::Min`           (1 arg)
- `max`            → `AggFuncKind::Max`           (1 arg)
- `group_concat`   → `AggFuncKind::GroupConcat`   (1 or 2 args; second
                                                   arg is the separator)

Argument-arity mismatch yields CompileError
`"aggregate <name> expects <n> argument(s)"`.

Opcode plan:

```
# Pre-loop: reset every aggregate slot.
for slot, (kind, _arg_expr) in enumerate(agg_slots):
    AggReset { acc_slot: slot, kind }

OpenRead   { cursor: 0, table: schema.name }
Rewind     { cursor: 0, jump_if_empty: AGG_FINALIZE }

TOP:
    # Materialize columns 0..ncol-1 as in B.
    for col in schema.columns:
        Column { cursor: 0, col_idx: col.index, dest_reg: col.index }

    # WHERE filter (same as B).
    (optionally) IfNot ... target: NEXT_LABEL

    # Step every aggregate.
    for slot, (kind, arg_expr) in enumerate(agg_slots):
        if kind == CountStar:
            AggStep { acc_slot: slot, kind, arg_reg: 0, separator_reg: None }
            # arg_reg ignored by state for CountStar; pass 0 as placeholder.
        else:
            arg_reg = compile_expr_in_schema(arg_expr) into a fresh register
            sep_reg = None
            if kind == GroupConcat and len(call.args) == 2:
                sep_reg = compile_expr_in_schema(call.args[1])
            AggStep { acc_slot: slot, kind, arg_reg, separator_reg: sep_reg }

NEXT_LABEL:
    Next { cursor: 0, jump_if_more: TOP }

AGG_FINALIZE:
    # Finalize each slot into a fresh register; record the slot→reg map.
    for slot, (kind, _) in enumerate(agg_slots):
        AggFinal { acc_slot: slot, kind, dest_reg: agg_result_reg[slot] }

    # HAVING (if present): compile HAVING with aggregate-call references
    # rewritten to reads of agg_result_reg[slot].
    if having is Some:
        cond_reg = compile_having(having, agg_result_reg, schema)
        IfNot { cond_reg, target: SKIP_EMIT }

    # Projection: compile each projection item with aggregate-call refs
    # rewritten to reads of agg_result_reg[slot]. Bare-column refs in a
    # single-group aggregate query are an error (no row context); the
    # compiler enforces "every non-aggregate projection expression must
    # be a constant or an aggregate call" — see pin 14 below.
    proj_start = next_free_register
    for item in projection:
        compile_proj_with_agg(item, agg_result_reg) into proj_start, +1, ...
    ResultRow { start_reg: proj_start, count: proj_count }

SKIP_EMIT:
    Close  { cursor: 0 }
    Halt
```

Notes:
- **No-FROM aggregate** (e.g. `SELECT count(*)` with no FROM) is
  rejected as `CompileError "aggregate without FROM is unsupported"`
  for the probe. (Trivially handled by emitting one synthetic row,
  but not exercised here.)
- **Empty table**: Rewind jumps directly to AGG_FINALIZE; per
  `aggregate_final` empty-group rules in `parts/vdbe/shapes.json`,
  Count* → Integer(0), Sum/Avg/Min/Max → Null, Total → Real(0.0),
  GroupConcat → Null. HAVING is still evaluated; if it filters the
  single empty-group row out, no ResultRow is emitted.
- **Aggregate-call rewriting in projection/HAVING**: walk the AST
  once before emission. Each aggregate `Call` node is replaced with
  a synthetic `Col` reference scheme that maps to the slot's
  finalized register — implemented by a wrapper around
  `compile_expr_in_schema` that intercepts `Call` nodes whose name
  is in the aggregate set.

### D. Multi-group GROUP BY — DEFERRED (spec gap)

If `stmt.group_by` is non-empty, emit
`CompileError "deferred: multi-group GROUP BY (spec gap: needs
ephemeral-table or Sort opcode family)"`. See §Scope above.

This branch is intentionally a hard-stop until the spec gap is
closed. The needed primitive is one of:
1. `OpenEphemeral { cursor }` + cursor methods that key by a
   register tuple, with implicit accumulator-per-key storage.
2. A `Sort { cursor }` opcode that sorts the table by the GROUP
   BY key tuple, plus group-break detection in the scan loop.
Both are sizable additions touching opcodes-scan, storage, and
VdbeState. Out of scope for the day-1 push.

## Projection expansion

- `ProjectionItem::Star` expands to ONE `Expr::Col(col.name)` per
  `ColumnSchema` entry, in schema order.
- `ProjectionItem::TableStar { table }` expands the same way but
  requires `table == schema.name` (otherwise CompileError `"unknown
  table in t.* projection"`).
- `ProjectionItem::Expr { expr, alias }` — the alias is IGNORED by
  codegen; it's only used downstream by the caller for column naming.

## Column reference binding

Inside an expression, `Expr::Col { name }` is resolved against the
schema:
- Find the `ColumnSchema` with matching name (case-insensitive ASCII
  compare). If not found, CompileError `"unknown column: <name>"`.
- Emit `OpcodeRows::Column { cursor: 0, col_idx: schema.index,
  dest_reg: <fresh> }` instead of the IntLit/RealLit/etc. path.
- The column's value ends up in a register just like a literal would.

This is the only integration point between `compile_expr` and schema
resolution. For the probe we handle it inline (extend `compile_expr`'s
recursive match with a `Col` case) rather than introducing a
resolver part — the real compiler will split this later.

**Simplification for the probe**: rather than modify
`compile_expr`, the select compiler calls it for literal subtrees and
handles `Col` references at the select-compiler level by wrapping:
pre-emit `Column` opcodes for all schema columns into scratch
registers, then substitute column references inside expressions
with register indices pointing into those scratch slots. This means
`compile_expr` itself stays literal-only; select-compile supplies a
`Col`-resolution pre-pass.

Concretely:
1. At the top of the loop body, emit `Column { col_idx, dest_reg }`
   for EVERY column in the schema (into registers `0..ncol-1`).
2. When the WHERE or projection expression is compiled, walk the AST
   once and rewrite every `Expr::Col { name }` → a synthetic "register
   reference" node. Since `Expr` doesn't have a RegRef variant, the
   workaround is: introduce a wrapper function `compile_expr_in_schema`
   that handles Col directly (emits a `Copy { src_reg: schema_scratch,
   dest_reg: next }`) and delegates to `compile_expr` for the
   non-Col subtree by cloning the sub-expression.
3. If `compile_expr_in_schema` encounters `Col { name }`, it emits
   `Copy` into the next free register; if it encounters `Binary` /
   `Unary`, it recurses on lhs/rhs/arg; if it encounters any literal,
   it delegates to `compile_expr` (a single-node literal call).

This keeps `compile_expr`'s scope clean — it's still the "Col-less
expression compiler" — and concentrates the schema-dependent logic
here in `compile_select`.

## LIMIT / OFFSET codegen

```
# Before Rewind:
LoadConst limit_remaining_reg <- limit_value      (if LIMIT)
LoadConst offset_remaining_reg <- offset_value    (if OFFSET)

# After WHERE passes, before ResultRow:
if offset_remaining_reg > 0:
    decrement; continue to NEXT_LABEL (skip this row)
else:
    ResultRow
    decrement limit_remaining_reg
    if limit_remaining_reg == 0: Goto END_LABEL
```

For the probe, implement OFFSET and LIMIT via simple BinOp and IfNot
opcodes — no new VDBE instructions needed.

## Correctness pins

1. **No-FROM works** — `SELECT 1 + 2` compiles to a program that
   emits exactly one ResultRow with `[Integer(3)]`.
2. **Star expansion** — `SELECT * FROM t` with
   `TableSchema { name: "t", columns: [{name:"a",0},{name:"b",1}] }`
   emits ResultRows with `[t.a, t.b]` for every row. Non-Star
   projections work in parallel.
3. **WHERE filtering** — `SELECT * FROM t WHERE a = 1` emits only
   rows whose column `a` equals `Integer(1)`. The WHERE compile
   produces one extra register holding the predicate's boolean
   result; an `IfNot` jumps past ResultRow when the predicate is
   false/null.
4. **Column references resolve** — `Expr::Col { name: "a" }`
   resolves to schema.columns[N].index via case-insensitive name
   match; a miss is `CompileError { message: "unknown column: a" }`.
5. **LIMIT** — `LIMIT 3` emits 3 rows then halts (even if more
   rows exist in the table).
6. **OFFSET** — `LIMIT 3 OFFSET 2` skips the first 2 rows, emits
   the next 3.
7. **Two-pass PC resolution** — the emitted opcode list has valid
   PC targets; no placeholder PCs remain. Verify the emitted list's
   Goto/If targets are in-range for `opcodes.len()`.
8. **Single cursor** — `num_cursors = 1` for a FROM-clause query;
   `num_cursors = 0` for no-FROM.
9. **num_registers bounds check** — the emitted
   `num_registers` is >= the highest register index used by any
   opcode. Off-by-one is a pin.
10. **Deferred constructs** — JOINs / multi-group GROUP BY /
    ORDER BY / top-level DISTINCT / subqueries each produce a
    CompileError with the `"deferred: <construct>"` message. The
    compiler does not silently accept-then-ignore.
10a. **Aggregate detection** — a query is in single-group aggregation
     mode iff (a) at least one aggregate-named `Call` appears in
     projection/HAVING/ORDER BY, OR (b) a non-empty `group_by` whose
     value is a single compile-time-constant expression (probe
     simplification: only the (a) branch is exercised). HAVING
     without aggregates and without GROUP BY is `CompileError
     "HAVING requires GROUP BY or aggregate"` (probe: simply require
     aggregation mode active).
10b. **Aggregate slot allocation** — distinct aggregate `Call` AST
     nodes (by traversal order, deduplicated only by AST identity,
     not by structural equality) each get one slot. Two textually
     identical `count(*)` instances in the same query get TWO slots
     (correct, simple — dedup is a later optimization).
10c. **count_star arg arity** — `count_star` (from the `count(*)`
     desugar) MUST have zero args. The compiler emits AggStep with
     `arg_reg: 0` (placeholder; state ignores arg for CountStar) and
     `separator_reg: None`.
10d. **count_distinct arity** — `count_distinct` MUST have exactly
     one arg. Anything else: CompileError.
10e. **HAVING register binding** — HAVING is compiled AFTER all
     AggFinal opcodes; aggregate `Call` refs in HAVING resolve to
     reads of the already-finalized register. Non-aggregate column
     refs in HAVING are NOT supported in single-group mode (no
     current row context after finalization); CompileError
     `"non-aggregate column in HAVING: <name>"`.
10f. **Multi-group GROUP BY hard-stop** — if `group_by` is non-empty
     AND aggregates are present (or HAVING is present), CompileError
     with the exact text `"deferred: multi-group GROUP BY (spec gap:
     needs ephemeral-table or Sort opcode family)"`.
11. **Halt at end** — every produced opcode list terminates with
    `OpcodeCore::Halt`.
12. **result_count accuracy** — `result_count` equals the number
    of columns in a single ResultRow (the projection arity AFTER
    Star expansion).
13. **No inline tests, no invented opcodes** — the emission only
    uses opcodes already declared by the VDBE shape; no custom
    helpers leak. `compile_expr` calls go through the imported
    function unchanged.

## Regeneration envelope

- Line budget: **~400-600 lines** of Rust. The opcode weaving is
  verbose (label tracking, cursor allocation, projection expansion)
  and the schema-lookup inline walker is ~80 lines.
- No dependencies beyond std.
- Public items: `ColumnSchema`, `TableSchema`, `CompileSelectOk`,
  `compile_select`.

## Smoke probe

`src-rust/examples/select_compile_smoke.rs` (hand-written, NOT
regenerated) wires tokenize → parse_select → compile_select →
execute_program against a synthetic in-memory table, asserting the
rows emitted:

The probe needs a `Database` mock that:
- Stores one table `t(a INT, b TEXT)` with pre-loaded rows.
- Lets OpenRead / Rewind / Column / Next work on it.

The current `src-rust/storage::Database` is an empty stub (no rows);
wiring a real row source is OUT OF SCOPE for the select-compile
probe itself but IS the next task after this. For this leaf, the
smoke probe may substitute no-FROM cases only (`SELECT 1+2`, etc.)
which test the non-cursor code paths — or skip behavioral verification
entirely and only assert the structural shape of the emitted opcode
list.

Probe assertions (structural, for the first round):
1. `SELECT 1 + 2` → opcodes = `[LoadConst(r0,1), LoadConst(r1,2),
   BinOp(Add,r0,r1,r2), ResultRow(r2,1), Halt]`.
2. `SELECT * FROM t` with 2-column schema → opcodes contain
   `OpenRead(0,"t")`, `Rewind(0,_)`, 2× `Column(0,_,_)`, `ResultRow(_,2)`,
   `Next(0,_)`, `Close(0)`, `Halt` in that structural order.
3. `SELECT * FROM t WHERE a = 1` → compiles, contains an `IfNot`
   skipping ResultRow when WHERE fails.

Behavioral (row-matching) verification for the FROM cases lands in
the next probe alongside a real `Database` row source.
