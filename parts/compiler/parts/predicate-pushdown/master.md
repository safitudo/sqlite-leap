---
name: compiler/predicate-pushdown
kind: leaf
emits:
  rust:   { path: src-rust/compiler/predicate_pushdown.rs }
  c:      { path: src-c/compiler/predicate_pushdown.c, headers: [src-c/compiler/predicate_pushdown.h] }
  zig:    { path: src-zig/compiler/predicate_pushdown.zig }
  go:     { path: src-go/compiler/predicate_pushdown.go }
  python: { path: src-python/compiler/predicate_pushdown.py }
---

# Predicate-pushdown rule (rowid point-fetch)

This part declares a single, narrowly-scoped compile-time rewrite that
the SELECT compiler (see `/parts/compiler/parts/select-compile`)
consults BEFORE its general single-table scan emitter. When the rewrite
applies, the compiler emits a constant-time point-fetch program in
place of the standard `OpenRead → Rewind → (loop body) → Next` scan
loop. When it does not apply, the compiler falls through to its
existing emission path unchanged.

Bench-validated: on the Rust target, this single rewrite lifts Lane 3
(in-memory SELECT) from 3,954 qps to 410,569 qps for the canonical
single-row primary-key lookup pattern (`SELECT * FROM t WHERE id = N`).

## Scope (v1)

Admitted: a `SelectStmt` matches the rule iff EVERY one of the
following holds. Each condition is a numbered Correctness pin below
(Pins 1–6). Mismatch on any condition → fall through to the standard
single-table emitter.

- The statement's FROM resolves to a single base table that the
  installed schema registry recognises as **declared with an
  INTEGER PRIMARY KEY column** (i.e. the schema carries a `Rowid`
  IndexSpec — see `/parts/storage/parts/mem-store` for the shape).
  Derived tables, CTEs, views, JOINs, and comma-FROMs are out of scope
  for this rule.
- `stmt.distinct` is false.
- `stmt.order_by` is empty.
- `stmt.limit` is absent.
- `stmt.offset` is absent.
- `stmt.group_by` is empty.
- `stmt.having` is absent.
- `stmt.compound` is empty (no UNION / INTERSECT / EXCEPT tail).
- The statement's projection list contains only `Star`, `TableStar`,
  bare `Col`, or other non-aggregating, non-window expressions. (The
  rule does not introspect projection further; aggregate calls in the
  projection imply single-group aggregation, which is admitted by the
  scan emitter only — fall through.)
- `stmt.where_` is `Some(predicate)`.
- The predicate is exactly `Binary(Eq, lhs, rhs)`. No outer AND/OR;
  no IS NULL; no IN; no nested parens-wrapped Binary other than the
  Eq node itself. The parser does not retain redundant parens, so
  `Eq` is the only structural form to recognise.
- After ASCII-case-insensitive lookup, exactly one of `lhs` or `rhs`
  is `Col { table: None | Some(t), name }` where `name` resolves to
  the table's INTEGER PRIMARY KEY column (the column whose 0-based
  index appears in the `Rowid` IndexSpec's `columns[0]`). The other
  side is the **key expression** (`key_expr`).
- `key_expr` is **row-independent**: a structural walk over its AST
  must encounter zero `Col` references and zero `Star` /
  `TableStar` placeholders. Bind parameters (`Param`), literals
  (`IntLit`, `RealLit`, `StrLit`, `Null`), `Cast`, `Unary`, `Binary`
  whose operand subtrees are themselves row-independent, and `Call`
  whose arguments are themselves row-independent are all admitted.
  Subqueries (`Subquery`, `Exists`, `InSubquery`) are NOT admitted in
  v1 (they require subquery materialization preludes — out of scope).

Anything else falls through.

## Declared shapes (`shapes.json`)

- `PointFetchOk` — a wrapper carrying the same `CompileSelectOk` shape
  the standard emitter returns; lifted into its own type only to make
  the compile_select integration call site readable. The `opcodes`
  field is the emit list described below; `num_cursors = 1`,
  `num_aggregates = 0`, `result_count = projection arity`.
- `try_compile_point_fetch(stmt, schema) -> option<PointFetchOk>` —
  the recogniser-and-emitter. Returns `Some` iff every Pin 1–6 holds
  (see below). Returns `None` to signal the caller to fall through to
  the standard scan emitter.

The rule itself is a recognition predicate over the AST plus a
replacement opcode template. The AST pattern is described in the
prose pins below (encoding it as data is more brittle than expressing
it as a recogniser function); `shapes.json` declares the **emit
template** in a structured form so generators can render the same
opcode sequence in every target.

## Algorithm (recogniser + emitter)

```
function try_compile_point_fetch(stmt, schema):
    # ——— Recogniser ———
    if not is_single_base_table_simple(stmt): return None
    if stmt.distinct or stmt.order_by or stmt.limit or stmt.offset
       or stmt.group_by or stmt.having or stmt.compound: return None
    if stmt.where_ is None: return None

    pred = stmt.where_
    if not is_binary_eq(pred): return None
    lhs, rhs = pred.lhs, pred.rhs

    pk_index = find_rowid_index(schema)              # via IndexSpec.kind == Rowid
    if pk_index is None: return None
    pk_col_idx = pk_index.columns[0]
    pk_col_name_lc = lower(schema.columns[pk_col_idx].name)

    if is_pk_col_ref(lhs, schema, pk_col_name_lc):
        key_expr = rhs
    elif is_pk_col_ref(rhs, schema, pk_col_name_lc):
        key_expr = lhs
    else:
        return None

    if not is_row_independent(key_expr): return None

    # ——— Emitter ———
    # Register layout:
    #   0..ncol-1     : column scratch (one per table column, populated
    #                   on hit by Column opcodes)
    #   ncol          : reg_key — receives the result of key_expr
    #   ncol+1..      : projection output regs (P regs)
    #   above that    : key_expr scratch beyond reg_key (compile_expr
    #                   places its working registers here; reg_key is
    #                   the destination; bookkeeping mirrors the
    #                   single-table emitter's reg layout convention)
    cursor = 0
    ncol = len(schema.columns)
    reg_key = ncol
    label_miss = fresh()
    label_halt = fresh()

    emit OpenRead { cursor: cursor, table: schema.name }
    emit <compile key_expr into reg_key, scratch above>
    emit SeekRowid { cursor: cursor, rowid_reg: reg_key, jump_if_miss: label_miss }
    # On hit, fall through; cursor is positioned at the matching row.
    for col in schema.columns:
        emit Column { cursor: cursor, col_idx: col.index, dest_reg: col.index }
    proj_start, proj_count = expand_and_compile_projection(
                                  stmt.projection, schema, ncol+1)
    emit ResultRow { start_reg: proj_start, count: proj_count }
    emit Goto { target: label_halt }
    bind label_miss := next_pc
    # miss path: no row emitted; close cursor and halt
    emit Close { cursor: cursor }
    emit Goto { target: label_halt }   # vestigial; both paths converge
    bind label_halt := next_pc
    emit Close { cursor: cursor }      # idempotent; harmless on miss
    emit Halt
    resolve labels into PCs (two-pass)
    return Some(PointFetchOk {
        opcodes,
        num_registers,
        num_cursors:    1,
        num_aggregates: 0,
        result_count:   proj_count,
    })
```

The `Goto` / `Close` / `Halt` / `OpenRead` / `Column` / `ResultRow`
opcodes live in the existing VDBE families (Control / Core / Rows);
`SeekRowid` lives in `/parts/vdbe/parts/opcodes-rows`. No new opcodes
are introduced by this part.

## Correctness pins

1. **Rule applies only when no compound clauses are present.** If
   ANY of `distinct`, `order_by`, `limit`, `offset`, `group_by`,
   `having`, or `compound` is non-trivial, the recogniser returns
   `None`. The standard emitter handles those forms.
2. **WHERE must be exactly `pk_col = expr` or `expr = pk_col`** — a
   single Binary(Eq, ..., ...) at the top of the predicate, with no
   AND / OR / NOT / IS NULL / parenthesised compound. The recogniser
   inspects only the immediate `Binary { op: Eq, lhs, rhs }` shape; if
   the shape doesn't match, returns `None`.
3. **The `expr` side must be row-independent.** A structural walk over
   the key expression encounters zero `Col` references and zero
   `Star` / `TableStar` placeholders. Subqueries (`Subquery`,
   `Exists`, `InSubquery`) are also rejected in v1 — they require a
   materialization prelude that is out of scope for this rule. Bind
   parameters (`Param`) ARE admitted: they are constants at execute
   time. Literals, `Cast`, `Unary`, and binary / call expressions
   whose operand subtrees are themselves row-independent are admitted.
4. **The table must declare an INTEGER PRIMARY KEY column.** The
   recogniser consults the schema's `indexes` list for an `IndexSpec`
   whose `kind` is `Rowid`. If absent, returns `None`. If multiple
   `Rowid` entries exist (illegal under the v1 mem-store invariant),
   the recogniser uses the first and treats subsequent ones as
   shape-error conditions — but well-formed callers never hit this.
5. **Cursor lifecycle.** A `Close { cursor }` opcode MUST appear
   on every control-flow path that leaves the program: the hit path
   (after `ResultRow`, before `Halt`) and the miss path (after
   `SeekRowid`'s miss-jump target, before `Halt`). The `Close` is
   idempotent (the opcode's own contract), so emitting two `Close`
   opcodes that converge into a single `Halt` is well-formed and is
   the recommended emission shape — it keeps both branches
   structurally symmetric and avoids label-rewiring complexity.
6. **Miss path emits zero rows.** On `SeekRowid`'s miss jump, the
   emission MUST NOT execute any `ResultRow` opcode before reaching
   `Halt`. Equivalently: the Goto immediately following `ResultRow`
   on the hit path skips the miss-path block, and the miss-path
   block contains only `Close` and `Halt` (or a Goto into the
   already-emitted Halt).

## Ambiguities surfaced; v1 scope decisions

- **`?` in a SELECT projection.** Admitted; the projection compiler
  routes `Param` through expr-compile alongside any other expression.
  No special handling required by predicate-pushdown.
- **`?` in WHERE matched by the rule.** Admitted; this IS the headline
  use case of predicate-pushdown for prepared statements (see
  `/parts/lib-api/parts/prepared-statement`). `key_expr = Param { idx
  }` is the canonical row-independent expression.
- **`?` in INSERT VALUES tuple cells.** Admitted by the parser; the
  insert-compile path emits `BindParam` opcodes the same way
  expression-bearing positions do. Out of scope for this rule (the
  rule is SELECT-specific).
- **`?` as a column-name or table-name.** Not admitted by the parser
  (it expects an identifier in those positions). Defer to the
  parser's existing error path.
- **`?` in LIMIT / OFFSET.** Not admitted in v1 — those positions
  expect IntLit. Wider admittance would require lowering the literal
  fast path in the standard emitter to a register-bearing form;
  out of scope.
- **`?` in ORDER BY positional integer.** Not admitted; `ORDER BY ?`
  has unclear semantics (positional column reference vs sort key
  expression) and is deferred.
- **`pk_col IS expr`** (vs `=`). Not matched by the rule (the
  recogniser only inspects `Binary { op: Eq }`). `IS` matches an
  `IsNull` AST shape under the v1 expr grammar and would not be a
  point-fetch candidate without further work.
- **`pk_col = expr AND <other_pred>`.** Not matched. A follow-up could
  recognise the AND shape, lower the rowid leg via this rule, and
  emit the residual predicate as a post-fetch `IfNot` filter — out
  of scope for v1.
- **WITHOUT ROWID tables.** Not admitted by mem-store v1 (the
  IndexSpec shape only models a `Rowid` index). When storage adds
  WITHOUT ROWID, this part will need a sibling rule keying off a
  `Unique` IndexSpec.

## Integration with select-compile

`/parts/compiler/parts/select-compile` consults this rule first in
its single-table dispatch path. Pseudocode:

```
function compile_select(stmt, schema):
    if stmt is single-table simple form:
        if let Some(ok) = try_compile_point_fetch(stmt, schema):
            return Ok(ok.into_compile_select_ok())
    # ... fall through to the existing standard emitter ...
```

The fall-through path is unchanged; this part adds a single guarded
short-circuit. Targets that have not yet regenerated this part fall
through directly (the recogniser is allowed to ALWAYS return `None`
in a stub emission, and behavior is preserved — only performance
regresses).

## Regeneration envelope

- Line budget: ~250-400 lines per target. The recogniser is a
  half-dozen guarded predicates over the AST; the emitter is a
  straight-line opcode sequence.
- No new opcodes; relies on `OpenRead` (Core), `SeekRowid` (Rows),
  `Column` (Rows), `ResultRow` (Core), `Close` (Core), `Goto`
  (Control), `Halt` (Core).
- Imports compile_expr from `/parts/compiler/parts/expr-compile` for
  the key-expression compile step.

## Smoke probe (structural)

A target's emission is well-formed iff:

1. `try_compile_point_fetch(SELECT * FROM t WHERE id = 1, schema_with_pk_id)`
   returns `Some(ok)` whose opcode list matches the §Algorithm template
   (one `OpenRead`, one `SeekRowid` with `jump_if_miss` set to a PC
   inside the program, one `ResultRow`, two `Close` opcodes, one
   `Halt`).
2. `try_compile_point_fetch(SELECT * FROM t WHERE id = 1, schema_without_pk)`
   returns `None`.
3. `try_compile_point_fetch(SELECT * FROM t WHERE id = ?, schema_with_pk_id)`
   returns `Some(ok)` (Param admitted as row-independent).
4. `try_compile_point_fetch(SELECT * FROM t WHERE id = other_col,
   schema_with_pk_id_and_other_col)` returns `None` (key_expr
   references a column).
5. `try_compile_point_fetch(SELECT * FROM t WHERE id = 1 AND x = 2,
   schema_with_pk_id)` returns `None` (top-level AND).
6. `try_compile_point_fetch(SELECT * FROM t WHERE id = 1 LIMIT 5,
   schema_with_pk_id)` returns `None` (LIMIT present).
