---
name: vdbe/opcodes-expr
kind: leaf
inherits:
  - /schema/opcode.schema.json
  - /schema/value.schema.json
  - /spec/memory-discipline.spec.md
emits:
  c: { path: src-c/vdbe/opcodes_expr.c, headers: [src-c/vdbe/opcodes_expr.h] }
  rust: { path: src-rust/src/vdbe/opcodes_expr.rs }
---

# Part: vdbe/opcodes-expr

Expression evaluation opcodes. Arithmetic, comparison, logical,
type, string, scalar function dispatch.

## Opcode families

### Arithmetic

`Add`, `Subtract`, `Multiply`, `Divide`, `Modulo`, `Neg`,
`BitAnd`, `BitOr`, `BitNot`, `Shl`, `Shr`. Standard two-operand
→ dest-register shape. NULL operands yield NULL result.

**DIV/MOD by zero** → NULL (SQLite semantics, Phase 6l / Phase
121).

### Comparison

`Eq`, `Ne`, `Lt`, `Le`, `Gt`, `Ge`, `IsNull`, `NotNull`. Affinity-
aware: compare integers to reals by numeric value, texts by
collation, blobs by bytewise. Phase 6as evidence: UNION ALL with
mixed types uses affinity equality, not strict-equal.

### Logical

`And`, `Or`, `Not`. Three-valued (NULL as UNKNOWN). `And` NULLs:
`FALSE AND NULL = FALSE`; `TRUE AND NULL = NULL`. Symmetric for
`Or`.

### Type

`Cast(src, target, dest)`, `Collate`, `IsInteger`, `IsReal`,
`IsText`, `IsBlob`, `IsNull` (also listed above for comparison).

### String

`Concat` (`||`), `Like(hay, pat[, esc])`, `Glob(hay, pat)`,
`Substr(src, start[, len])`, `Length(src)`, `Upper`/`Lower`,
`Replace`, `Instr`, `Round`, `Trim`/`Ltrim`/`Rtrim`.

### Scalar functions

`CallScalar(func_id, arg_regs, dest_reg)` — dispatches via a
static function-id table. The table enumerates every supported
scalar: `coalesce`, `nullif`, `ifnull`, `abs`, `typeof`, `hex`,
`quote`, `random`, `date`, `time`, `datetime`, `julianday`,
`strftime`, `unicode`, `char`, `printf`.

### Real→Text formatting (Phase 6r)

Real-to-text conversion uses SQLite's `%!.15g` format via a
Ryu-clone. The opcode `CastRealToText` implements the conversion.
Cross-build requirement: byte-identical output between C and Rust
on the full corpus.

## NULL propagation rule

Most binary opcodes: if either operand is NULL, result is NULL.
Exceptions: `IS` / `IS NOT` / `IsNull` / `NotNull` — these return
integer 0/1 on NULL, not NULL.

## Phase pins

- **Phase 6u** — IS NULL / IS NOT NULL.
- **Phase 6x** — LIKE wildcards.
- **Phase 6ad** — GLOB.
- **Phase 6r** — Real→Text %!.15g Ryu-clone.
- **Phase 6l / #120 / #121** — DIV/MOD by zero → NULL.
- **Phase 117** — NULLIF scalar.
- **Phase 6as** — UNION ALL affinity equality (not
  SCALAR2_STRICT_EQ).

## Regeneration envelope

- Target leaf size: 800–1200 lines per target.
- Spec < 200 lines.
