---
name: compiler/expressions
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /schema/ast.schema.json
  - /schema/program.schema.json
  - /schema/opcode.schema.json
  - /parts/vdbe/parts/opcodes-expr/master.md
  - /parts/compiler/parts/name-resolution/master.md
emits:
  c:
    path: src-c/compiler/expressions.c
    headers: [src-c/compiler/expressions.h]
  rust:
    path: src-rust/src/compiler/expressions.rs
---

# Part: compiler/expressions

Compiles `Expression` AST nodes into opcode sequences that leave a
single Value in a caller-specified destination register. This is
the densest leaf in the compiler — every statement compiler depends
on it.

## Public interface

```
compile_expression(
    expr:          &Expression<'src>,
    dest_reg:      Register,
    ctx:           &CompileContext,
    program_out:   &mut ProgramBuilder,
) -> Result<(), CompileError>
```

- **`expr`** — an `Expression` AST node (see
  `/schema/ast.schema.json`). All nested expressions are handled by
  recursion into this function.
- **`dest_reg`** — the register that MUST hold the computed value
  after the emitted opcodes run. Caller-allocated.
- **`ctx`** — the compile context, carrying:
  - `name_scope` — current name-resolution scope (see
    `parts/name-resolution/`).
  - `reg_alloc` — register allocator for scratch registers.
  - `cursor_alloc` — cursor allocator for subqueries (delegated).
  - `aggregate_mode` — `None` | `CollectingAggregates` | `Grouped` —
    tells the compiler whether aggregates are legal and how to
    emit them (see `parts/aggregates/`).
- **`program_out`** — mutable program being built; opcodes append.

## AST kinds handled

The `Expression` variant tree this part compiles:

### Literals

- `Literal::Integer(i)` → `LoadConst(dest_reg, integer(i))`
- `Literal::Real(r)` → `LoadConst(dest_reg, real(r))`
- `Literal::Text(t)` → `LoadConst(dest_reg, text(t))`
  (owned — source-buffer may outlive the program)
- `Literal::Blob(b)` → `LoadConst(dest_reg, blob(b))`
- `Literal::Null` → `LoadConst(dest_reg, null)`
- `Literal::True` / `False` → integer 1 / 0 (SQLite convention)

### Column references

`ColumnRef { table?, column }` → delegate to
`compile_column_reference()` which calls into
`parts/name-resolution/` to resolve `(source_idx, col_idx)`, then
emits `Column(cursor, col_idx, dest_reg)`. Resolution errors
propagate unchanged:

- `EVAL_COLUMN_WITHOUT_TABLE` when no source has the column.
- `COMPILE_AMBIGUOUS_COLUMN` when multiple sources match with no
  disambiguator.
- `COMPILE_UNKNOWN_TABLE` when `table` qualifier is unknown.

### Parameter markers

`ParameterMarker { kind, name }` → reserved for future binding; v2
emits `LoadConst(dest_reg, null)` and raises a warning condition
for now (parameters aren't in v1 or v2 scope, placeholder only).

### Unary ops

- `UnaryOp::Neg(e)` → compile `e` into scratch; emit `Neg(scratch,
  dest_reg)`.
- `UnaryOp::Not(e)` → compile; emit `Not`.
- `UnaryOp::BitNot(e)` → compile; emit `BitNot`.
- `UnaryOp::Plus(e)` → compile `e` with `dest_reg` directly
  (identity).
- `UnaryOp::IsNull(e)` / `NotNull(e)` → compile; emit `IsNull` /
  `NotNull` predicate opcodes.

### Binary ops

Grouped by type-family in emission:

- Arithmetic: `+`, `-`, `*`, `/`, `%`. Emit `Add`/`Subtract`/
  `Multiply`/`Divide`/`Modulo` after compiling both operands into
  scratch registers. `Divide`/`Modulo` by zero yields NULL (SQLite
  semantics, Phase 6l) — VDBE opcode handles this directly.
- Comparison: `=`, `<>`, `!=`, `<`, `<=`, `>`, `>=`. Emit
  `Eq`/`Ne`/`Lt`/`Le`/`Gt`/`Ge` — operand order preserved.
- Logical: `AND`, `OR`. Short-circuit is implemented via
  `opcodes-control` jumps: `AND(a, b)` compiles `a`, tests via
  `JumpIfNot` to a "result = false" block, then compiles `b`, then
  finalizes. `OR(a, b)` mirrors.
- String: `||` (concat). Emit `Concat`.
- Bitwise: `&`, `|`, `<<`, `>>`. Emit `BitAnd`/`BitOr`/`Shl`/`Shr`.

### IN / NOT IN

`In(expr, InList::Values(values))` → emit `In` with an inline value
list. `In(expr, InList::Subquery(select))` → delegate to
`parts/subqueries/` which returns a Program + wire-in instructions;
current `compile_expression` emits the subquery placeholder and
resolves during the outer-compile pass (see `parts/compiler/master.md`
§ "Phase 6n sentinel").

### EXISTS

`Exists(select)` → delegate to `parts/subqueries/`.

### CASE

- Simple: `CASE base WHEN v1 THEN r1 ... ELSE rE END` — desugar to
  `CASE WHEN base = v1 THEN r1 ...`.
- Searched: `CASE WHEN c1 THEN r1 ... ELSE rE END` — emit as a
  chain of `JumpIfNot` over computed predicates.

### CAST, COLLATE, LIKE, GLOB, REGEXP

- `Cast(expr, target_type)` → emit `Cast`.
- `Collate(expr, collation)` → emit `Collate`.
- `Like(haystack, pattern, escape?)` / `Glob`. Pattern + escape
  compiled to scratch; emit `Like` / `Glob` opcode.

### Functions

- Scalar functions: dispatch table mapping function name (case-
  insensitive) to opcode kind. Names in the closed set:
  `coalesce`, `nullif`, `ifnull`, `lower`, `upper`, `length`,
  `substr`, `replace`, `instr`, `round`, `abs`, `typeof`,
  `hex`, `quote`, `trim`, `ltrim`, `rtrim`, `random`, `date`,
  `time`, `datetime`, `julianday`, `strftime`, `unicode`, `char`,
  `printf`.
- Aggregate functions: delegate to `parts/aggregates/` when
  `ctx.aggregate_mode != None`; reject with `COMPILE_AGGREGATE_NOT_ALLOWED`
  otherwise.

### Aggregates

`AggregateCall { func, args, distinct? }` → must be delegated to
`parts/aggregates/`. This sub-part NEVER emits aggregate opcodes
directly — the aggregates sub-part owns the AggStep/AggFinal
lifecycle.

## Emission rules

1. Every invocation must leave the result in `dest_reg`, regardless
   of how many scratch registers were used internally.
2. Scratch registers are allocated via `ctx.reg_alloc.next()`;
   compiler does NOT reuse them across sibling subexpressions in a
   way that would require lifetime tracking — always fresh per
   subexpression.
3. Identifier strings embedded in opcodes (column names, table
   names) are borrowed from the AST's `'src` lifetime.
4. Literal values that outlive the source (text, blob) are cloned
   into owned Value::Text / Value::Blob.

## Error conditions raised here

- `COMPILE_AGGREGATE_NOT_ALLOWED` — aggregate in a non-aggregate
  context.
- `COMPILE_NESTED_AGGREGATE` — aggregate inside aggregate argument.
- `COMPILE_UNKNOWN_FUNCTION` — name not in scalar or aggregate
  registry.
- `COMPILE_ARG_COUNT_MISMATCH` — function called with wrong arity.

Each is structured as `{kind, name?, got?, expected?}` per the
error-condition-shape rules in
`/spec/memory-discipline.spec.md` § "Error conditions".

## Phase pins owned here

- **Phase 6y** — CASE expression (simple + searched).
- **Phase 6u** — IS NULL / IS NOT NULL.
- **Phase 6v** — IN (expr-list).
- **Phase 6x** — LIKE / NOT LIKE with `%` `_` wildcards.
- **Phase 6ad** — GLOB.
- **Phase 6ae** — EXISTS / NOT EXISTS (delegates to subqueries).
- **Phase 6af** — accept parenthesized type params in CAST.
- **Phase 6ao** — SUBSTR / REPLACE / INSTR / ROUND.
- **Phase 6ap** — GROUP_CONCAT, TOTAL (delegates to aggregates).
- **Phase 6r** — Real→Text conversion via Ryu-clone (owned by
  VDBE's opcode-expr sub-part; expression compiler just wires).
- **Phase 6l** — DIV/MOD by zero → NULL (owned by VDBE; compiler
  wires).
- **Phase 6az** — NOT BETWEEN desugar to `NOT (x BETWEEN a AND b)`.

## Regeneration envelope

- Target leaf size: 1200–1800 lines per target.
- Spec size budget: this file < 600 lines.
- Atomic regen: a sub-agent with this file + inherits + schemas
  produces a passing expression compiler that compiles every
  `Expression` variant.
- Test ownership: `tests/` subdirectory under this part contains
  fixtures for each AST variant. Cross-build fixtures naming this
  part as primary run on regen.
