---
name: vdbe/opcodes-expr
kind: leaf
inherits:
  - /schema/opcode.schema.json
  - /schema/value.schema.json
  - /spec/memory-discipline.spec.md
  - /parts/core/master.md
  - /parts/vdbe/master.md
emits:
  c: { path: src-c-v2/vdbe/opcodes_expr.c, headers: [src-c-v2/vdbe/opcodes_expr.h] }
  rust: { path: src-rust-v2/vdbe/opcodes_expr.rs }
---

# Part: vdbe/opcodes-expr

Expression evaluation opcodes. Arithmetic, comparison, logical,
type, string, scalar function dispatch.

## Canonical enum shape

Because this family has ~40 opcodes, it uses a two-level layout:
per-op variants for unique shapes, plus a compact group variant
for binary ops with identical shape. Convention:

### Rust

```rust
use crate::core::{Register, Value};

pub enum BinOpKind {
    Add, Subtract, Multiply, Divide, Modulo,
    BitAnd, BitOr, Shl, Shr,
    Eq, Ne, Lt, Le, Gt, Ge,
    And, Or,
    Concat,
}

pub enum UnaryOpKind {
    Neg, Not, BitNot,
    IsNull, NotNull,
}

pub enum CastKind   { Integer, Real, Text }
pub enum ScalarKind {
    Length, Abs, Upper, Lower, Trim, Ltrim, Rtrim,
    Substr, Replace, Instr, Round,
    Coalesce, Nullif, Ifnull,
    Typeof, Hex, Quote, Random,
    Date, Time, Datetime, Julianday, Strftime,
    Unicode, Char, Printf,
}

pub enum OpcodeExpr<'src> {
    BinOp   { kind: BinOpKind, lhs: Register, rhs: Register, dest_reg: Register },
    UnaryOp { kind: UnaryOpKind, src: Register, dest_reg: Register },
    Cast    { kind: CastKind, src: Register, dest_reg: Register },
    Like    { hay: Register, pat: Register, esc: Option<Register>, dest_reg: Register },
    Glob    { hay: Register, pat: Register, dest_reg: Register },
    Collate { src: Register, collation: &'src str, dest_reg: Register },
    Scalar  { kind: ScalarKind, args: Vec<Register>, dest_reg: Register },
    CastRealToText { src: Register, dest_reg: Register },
}
```

### C

Same-shape layout: discriminator enum + union of operand structs.
Generator produces it in the idiomatic C style (see opcodes-core
for reference).

## Opcode semantics

### BinOp

All `BinOp` variants emit `Continue` on success. NULL propagation
rule (cross-variant): if either operand is `Value::Null`, result is
`Value::Null` — except for `IS` / `IS NOT` / `IsNull` / `NotNull`
(those live in UnaryOp for single-operand forms; for the binary
`IS` / `IS NOT` — not present in this list since SQLite's `IS` is a
special comparison — see the "IS/IS NOT special case" section).

### Arithmetic

`Add`, `Subtract`, `Multiply`, `Divide`, `Modulo`. Affinity rules:
Integer ⊕ Integer → Integer with overflow promotion to Real; any
Real operand → Real result.

**DIV/MOD by zero** → `Value::Null` (SQLite semantics, Phase 6l /
Phase 121). NOT `RuntimeCondition::DivZero`; that condition exists
for diagnostics but is not raised in default operation.

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
