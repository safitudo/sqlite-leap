---
name: predicate-pushdown/targets/rust
kind: mapping
inherits:
  - /parts/targets/rust/mapping.md
---

# Rust mapping — predicate-pushdown

## Toolchain

- **rustc**: edition 2021, stable 1.75+ (tested on 1.95).
- **stdlib**: `Vec`, `Option`, `Result`, `Box` (recursion through `Expr` carriers reuses the existing parser-side boxing).
- **crates**: none beyond the universal mapping.

If the toolchain pin shifts (any rustc minor bump that changes
`from_be_bytes` / `try_into` / `Vec::extend_from_slice` API surfaces),
this part must be regenerated rather than hand-patched.

## Type rendering

| Shape | Rust |
|---|---|
| `PointFetchOk` | `pub struct PointFetchOk { pub opcodes: Vec<Opcode>, pub num_registers: u32, pub num_cursors: u32, pub num_aggregates: u32, pub result_count: u32, pub opcode_template_kind: u32 }` |
| `PushdownTrigger` | `pub enum PushdownTrigger { RowidPointFetch }` |
| `EmitOp` | `pub enum EmitOp { OpenReadCursor, KeyExprCompile, SeekRowidByKey, ColumnReadAll, ProjectionCompile, EmitResultRow, GotoHalt, BindMissLabel, CloseCursor, BindHaltLabel, EmitHalt }` |
| `RowidPointFetchTemplate` | `pub struct RowidPointFetchTemplate { pub trigger: PushdownTrigger, pub steps: Vec<EmitOp> }` |

## Function signatures

```rust
pub fn try_compile_point_fetch(
    stmt: &SelectStmt,
    schema: &TableSchema,
) -> Result<Option<PointFetchOk>, CompileError>;

pub fn find_rowid_index(schema: &TableSchema) -> Option<&IndexSpec>;

pub fn is_row_independent(expr: &Expr) -> bool;
```

The `Some / None` discriminator threads back to
`/parts/compiler/parts/select-compile`'s dispatch with no further
adapter.

## Notes

- Recogniser is a small set of guarded `match` arms over `&Expr` and
  `&SelectStmt`. Avoid recursion through `Box<Expr>` clones — borrow
  through.
- Emitter uses the existing label-allocation idiom from
  `select_compile.rs` (two-pass: emit with placeholder PCs, patch in
  a follow-up walk).
- Param expressions: `Expr::Param { idx }` lowers via the standard
  expr-compile path (which emits `OpcodeCore::BindParam { slot: idx,
  dest_reg }`); predicate-pushdown does NOT special-case Param —
  it merely accepts it as row-independent.
