---
name: predicate-pushdown/targets/zig
kind: mapping
inherits:
  - /parts/targets/zig/mapping.md
---

# Zig mapping — predicate-pushdown

## Toolchain

- **Zig**: 0.16.x (matches the rest of the repo, per
  `feedback_target_toolchain_pin`).
- **stdlib surfaces**: `std.ArrayList`, `std.mem.Allocator`,
  `std.ascii.eqlIgnoreCase`. (0.16 ArrayList init is
  `ArrayList(T).init(allocator)`.)
- **No `std.crypto.random` / `std.time.timestamp`** dependencies.

Regenerate this part if the Zig toolchain advances past 0.16.

## Type rendering

| Shape | Zig |
|---|---|
| `PointFetchOk` | `pub const PointFetchOk = struct { opcodes: []Opcode, num_registers: u32, num_cursors: u32, num_aggregates: u32, result_count: u32, opcode_template_kind: u32 };` |
| `Option<PointFetchOk>` | `?PointFetchOk` |
| `PushdownTrigger` | `pub const PushdownTrigger = enum { RowidPointFetch };` |
| `EmitOp` | `pub const EmitOp = enum { OpenReadCursor, KeyExprCompile, SeekRowidByKey, ColumnReadAll, ProjectionCompile, EmitResultRow, GotoHalt, BindMissLabel, CloseCursor, BindHaltLabel, EmitHalt };` |
| `RowidPointFetchTemplate` | `pub const RowidPointFetchTemplate = struct { trigger: PushdownTrigger, steps: []EmitOp };` |

## Function signatures

```zig
pub fn tryCompilePointFetch(
    allocator: std.mem.Allocator,
    stmt: *const SelectStmt,
    schema: *const TableSchema,
) CompileError!?PointFetchOk;

pub fn findRowidIndex(schema: *const TableSchema) ?*const IndexSpec;

pub fn isRowIndependent(expr: *const Expr) bool;
```

## Notes

- The opcode list and steps slices are owned by the returned struct;
  the caller passes the same allocator at program-disposal time
  (matches the existing Zig select-compile contract).
- Naming: Zig uses camelCase for functions; the language-neutral
  `try_compile_point_fetch` renders as `tryCompilePointFetch`. This
  is a Zig idiom, NOT a spec leak.
