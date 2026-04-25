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
- `DISTINCT` (top-level SELECT DISTINCT) — admitted via the buffer-
  sort-dedup-replay pattern (see §"DISTINCT and ORDER BY" below).
- `ORDER BY` (single-table compile path only) — admitted via the
  buffer-sort-replay pattern. ORDER BY across the JOIN compile
  path remains deferred.

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
- subqueries, ORDER BY across JOINs, compound SELECT,
  CTE, window functions, ORDER BY with NULLS FIRST/LAST modifiers
  (the parser does not currently surface them; default SQLite
  placement is used).

JOIN support is admitted in this part — see §JOINs below.

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

### Cb. JOINs (multi-source SELECT)

If `stmt.from` is a `TableRef::Joined` (or transitively contains one),
the compiler flattens the recursive tree into a left-to-right list of
SOURCES, where each source carries its `(table_name, alias?, schema,
join_kind, predicate?)` and a 0-based source index. The leftmost source
has `join_kind = Inner` synthetically (it's the outer driver, not joined
to anything). Each subsequent source carries the JoinKind that bound it
to the accumulated left.

USING(c1, c2, ...) is desugared at compile time into an equivalent ON
predicate `Eq(left.c, right.c) AND ...` where each `c` resolves into
the left accumulated schema (any source so far) and the right schema
(the new source). The USING column names are also marked as
"join-eliminated" on the right side so that `SELECT *` expansion emits
each USING column only once (taken from the LEFT side).

Caller's TableSchema input — a single TableSchema — is generalized to
a list provided in source order. The probe accepts a parallel
`schemas: Vec<TableSchema>` matched up to flattened sources by
position. (The public function signature stays — `compile_select`
accepts a single TableSchema, but the JOIN path takes a multi-schema
overload `compile_select_multi`. Both forms are exercised.)

#### Register layout

```
[0 .. ncol_total)             : column scratch, source by source
[ncol_total .. ncol_total+P)  : packed projection outputs (P cols)
[above]                       : WHERE / ON scratch + LIMIT counters
                                + per-source "matched" flag for LEFT
```

`ncol_total = sum(schemas[i].columns.len())`. Source `s`'s column
scratch starts at `column_base[s]`.

#### Nested-loop emission

For sources S0, S1, ..., Sn (left-to-right):

```
OpenRead { cursor: 0, table: S0.name }
Rewind   { cursor: 0, jump_if_empty: END }
TOP_0:
    emit Column for every column of S0 into scratch[S0]

    OpenRead { cursor: 1, table: S1.name }
    Rewind   { cursor: 1, jump_if_empty: AFTER_1 }      # for INNER/CROSS
                                                         # (LEFT: branches to LEFT_NULL_FILL_1)
    LoadConst matched_1, 0                               # only for LEFT
    TOP_1:
        emit Column for every column of S1 into scratch[S1]

        # Evaluate the join predicate for (S0, S1):
        if pred_1 is Some:
            cond = compile_expr_in_multi_schema(pred_1, schemas[..=1], column_base)
            IfNot cond -> NEXT_1
        # ...recurse for S2, S3, ... or, at the last source, do projection.

        # innermost (after all sources rewound + columns fetched):
        compile WHERE -> IfNot -> NEXT_inner
        compile each projection item -> ResultRow

    NEXT_1:
        Next { cursor: 1, jump_if_more: TOP_1 }
    AFTER_1:
        # LEFT-only NULL-fill: if matched_1 == 0, NULL-out S1's scratch
        # block and run the inner body once.
        Close { cursor: 1 }

NEXT_0:
    Next { cursor: 0, jump_if_more: TOP_0 }
END:
    Close { cursor: 0 }
    Halt
```

For LEFT JOIN at depth k:
- Reset `matched_k = 0` after the outer Rewind on S_k's parent's row.
- After the ON predicate passes (and before recursing deeper / or before
  emitting), set `matched_k = 1`.
- After the inner loop completes (NEXT_k loop ended), if `matched_k == 0`,
  fill all of S_k's column scratch with `Value::Null` via LoadConst into
  each scratch register, then run the inner-body block once with NULLs.

For CROSS / INNER without predicate (after USING desugar): same as INNER
with predicate, except the IfNot is omitted.

#### Column resolution across multiple sources

`Expr::Col { table: Some(qual), name }` resolves to the unique source
whose `name` or `alias` matches `qual` (case-insensitive ASCII), then
the column index inside that source's schema. If no source matches:
CompileError `"unknown table qualifier: <qual>"`. If two sources share
the same name+alias (impossible by construction in the probe — caller
must supply distinct names/aliases), the FIRST is taken.

`Expr::Col { table: None, name }` resolves by scanning every source's
schema in order. If one match: use it. If 0 matches: CompileError
`"unknown column: <name>"`. If 2+ matches AND the column is not in any
USING list, CompileError `"ambiguous column: <name>"`. USING-listed
columns resolve unambiguously to the LEFT-most source that contributes
the column (so `SELECT k FROM t JOIN u USING (k)` selects `t.k`).

#### `*` and `t.*` expansion under JOINs

`*` expands to (for each source S in order, for each column C in
S.schema): `Expr::Col { table: None, name: C.name }` — but USING-eliminated
columns on RIGHT-hand sources are skipped (so each USING column appears
exactly once).

`t.*` expands to the columns of the source whose name/alias matches `t`,
qualified-only (USING-elimination does not apply to `t.*`). Unknown
qualifier → CompileError.

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

## DISTINCT and ORDER BY (single-table path)

When `stmt.distinct` is true OR `stmt.order_by` is non-empty AND the
compile path is the single-table form (form B above), the emitter
routes rows through an in-memory row buffer instead of streaming them
straight to the result sink. The pattern (with one buffer slot,
slot 0):

```
# Pre-loop (in addition to the existing scan setup):
BufferOpen { buffer_slot: 0, num_cols: <projection arity + sort-key arity> }

# Inside the scan loop, after WHERE passes and projection has been
# packed into the projection register window — instead of emitting
# ResultRow:
#   1. Compile each ORDER BY key expression into registers contiguous
#      with (just past) the projection block.
#   2. BufferAppend { buffer_slot: 0, first_reg: proj_reg_base,
#                     num_cols: proj_count + n_keys }
#   (LIMIT/OFFSET, if also present, applies AFTER sort/dedup; the
#    in-loop LIMIT bookkeeping is suppressed under buffering. For the
#    probe scope, LIMIT/OFFSET combined with DISTINCT/ORDER BY is
#    deferred — fold that in once buffered LIMIT lands.)

# After the scan loop closes (i.e. at END_LABEL, before Halt):
if has_order_by: BufferSort { buffer_slot: 0, key_indices: [...], key_desc: [...] }
if has_distinct:
    if not has_order_by:
        BufferSort { buffer_slot: 0, key_indices: [0..proj_count), key_desc: [false; ...] }
    BufferDedup { buffer_slot: 0 }

BufferRewind { buffer_slot: 0, end_pc: HALT_LABEL }
REPLAY_TOP:
    BufferRead { buffer_slot: 0, dest_first_reg: <replay register>,
                 num_cols: proj_count }
    ResultRow  { start_reg: <replay register>, count: proj_count }
    BufferNext { buffer_slot: 0, body_pc: REPLAY_TOP }
HALT_LABEL:
    Close ...; Halt.
```

Notes:
- The buffer width is `proj_count + n_order_keys` so each row carries
  the values needed both for replay (the projection block) and for
  sort comparison (the trailing key block). `BufferRead` reads only
  the projection prefix back into registers for `ResultRow`.
- ORDER BY key expressions are compiled against the original schema
  (not against the projection), so keys may reference any column —
  including columns not in the projection (e.g. `SELECT a FROM t
  ORDER BY b`).
- DISTINCT WITHOUT ORDER BY: sort by every projection column (ASC),
  then dedup. Output ordering becomes the sort order. This is
  documented and accepted; a real planner would use a hash set when
  observable order isn't required, but for the spec-clean version we
  pay the sort cost.
- DISTINCT WITH ORDER BY: sort on ORDER BY keys → dedup adjacent
  on the projection prefix would not collapse semantic duplicates
  (since equal-projection rows may differ on ORDER BY keys). To keep
  semantics correct without a second sort, we sort on
  `(projection-cols ASC ..., order-by-keys-with-original-direction)`,
  dedup adjacent on the full row (which is correct because the
  projection prefix is the leading sort key), then a stable second
  sort on just the original ORDER BY keys gives the requested order.
  Implementation simplification (probe): reject `DISTINCT + ORDER BY`
  if any ORDER BY key is not also a projection column; otherwise
  sort by the ORDER BY keys + projection-tail, dedup, done. Any
  refinement is a planner concern.

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
10. **Deferred constructs** — multi-group GROUP BY / subqueries /
    ORDER BY across JOIN sources / DISTINCT across JOIN sources
    each produce a CompileError with the `"deferred: <construct>"`
    message. The compiler does not silently accept-then-ignore.
    (ORDER BY and DISTINCT in the single-table path are admitted
    via §"DISTINCT and ORDER BY".)
10g. **JOIN nested-loop semantics** — `SELECT a, b FROM t, u` (CROSS)
     emits exactly `|t| * |u|` rows — every left-row paired with every
     right-row, in left-major order.
10h. **INNER JOIN with ON** — `SELECT t.a, u.x FROM t INNER JOIN u ON
     t.a = u.k` emits one row per (t-row, u-row) pair where the predicate
     is truthy; non-matching pairs are skipped. Unmatched left rows
     produce no output (vs LEFT, where they emit a NULL-padded row).
10i. **LEFT JOIN NULL-fill** — `SELECT t.a, u.x FROM t LEFT JOIN u ON
     t.a = u.k` emits one row per left row: if 1+ right rows match the
     predicate, one output per match; if 0 right rows match, exactly
     one output with all u-side columns set to `Value::Null`.
10j. **USING (cols)** — `t JOIN u USING (k)` is semantically equivalent
     to `t JOIN u ON t.k = u.k` for predicate purposes. In a `SELECT *`
     projection, the join columns appear ONCE (taken from the left
     side). USING with no shared column or with a column that doesn't
     exist in BOTH schemas → CompileError `"USING column <name> not in
     both joined relations"`.
10k. **CROSS JOIN constraint** — A `Cross` join with non-empty `on` or
     non-empty `using` is a CompileError (already gated by parser, but
     the compiler asserts defensively).
10l. **Multi-source qualifier resolution** — `Expr::Col { table: Some(t), name }`
     resolves to the source whose `name` or `alias` equals `t`
     (case-insensitive). Unknown qualifier → CompileError
     `"unknown table qualifier: <t>"`. Unqualified column resolves
     unambiguously by scanning all sources; 2+ sources match (and the
     column is not in any USING list at the join above them) →
     CompileError `"ambiguous column: <name>"`.
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
12a. **ORDER BY single-table semantics** — `SELECT a FROM t ORDER BY a`
     emits rows in ascending order of column `a` under SQLite total
     order. `ORDER BY a DESC` reverses; multi-key ORDER BY uses
     left-to-right key precedence. Sort is stable; equal-key rows
     retain insertion (i.e. table-scan) order.
12b. **ORDER BY non-column expressions** — `SELECT a FROM t ORDER BY
     a*2` is admitted; the key expression is compiled against the
     original schema each row and stored in the sort-key portion of
     the buffer row.
12c. **DISTINCT single-table semantics** — `SELECT DISTINCT a FROM t`
     emits one row per unique value of `a` under the SQLite total
     order. Output ordering is sort-order (a documented side effect
     of the buffer-sort-dedup-replay lowering).
12d. **DISTINCT + ORDER BY** — both are admitted in the single-table
     path; the buffer is sorted by a composite key
     `(order-keys, projection-tail)`, deduped adjacent, then replayed.
     ORDER BY keys MAY reference projection columns directly; if
     they reference non-projection columns the request is rejected
     with `"deferred: DISTINCT + ORDER BY referencing non-projected
     column"`.
12e. **ORDER BY across JOIN / DISTINCT across JOIN** — admitted via
     the same buffer-sort-dedup-replay pattern. The JOIN-branch
     compiler threads a `BufferCfg` through the recursive
     `emit_inner_sources` → `emit_where_and_project` walk; the
     innermost emission writes `BufferAppend` instead of `ResultRow`,
     and the post-loop tail emits `BufferSort` / `BufferDedup` /
     `BufferRewind` / `BufferRead` / `ResultRow`. ORDER BY keys may
     reference any source's qualified columns. Multi-source DISTINCT
     dedup is total-row-equality on the projection.
12f. **LIMIT/OFFSET combined with DISTINCT or ORDER BY** —
     `CompileError "deferred: LIMIT/OFFSET with DISTINCT or ORDER
     BY"`. The buffer pattern can absorb LIMIT (truncate after
     sort/dedup) — left for a follow-up.
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
