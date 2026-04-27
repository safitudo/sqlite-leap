---
name: prepared-statement/targets/zig
kind: mapping
inherits:
  - /parts/targets/zig/mapping.md
---

# Zig mapping — prepared-statement

## Toolchain

- **Zig**: 0.16.x.
- **stdlib**: `std.ArrayList`, `std.mem.Allocator`. No third-party
  deps.

## Type rendering

| Shape | Zig |
|---|---|
| `PreparedStatement` | `pub const PreparedStatement = struct { program: Program, arity: u32 };` |
| `BoundParams` | `pub const BoundParams = struct { values: []Value, allocator: std.mem.Allocator };` |
| `StepResult` | `pub const StepResult = union(enum) { Row, Done, Error: RuntimeCondition };` |
| `PrepareError` | `pub const PrepareError = union(enum) { ParseFailure: ParseError, CompileFailure: CompileError };` |
| `BindError` | `pub const BindError = struct { slot: u32, arity: u32 };` |

## Function signatures

```zig
pub fn prepare(allocator: std.mem.Allocator, db: *const Database, sql: []const u8)
    PrepareError!PreparedStatement;

pub fn bind(stmt: *const PreparedStatement, params: *BoundParams,
            slot: u32, value: Value) BindError!void;

pub fn step(stmt: *const PreparedStatement, params: *const BoundParams,
            db: *const Database) StepResult;

pub fn reset(stmt: *PreparedStatement) void;

pub fn boundParamsForArity(allocator: std.mem.Allocator, arity: u32) !BoundParams;
```

## Notes

- Zig requires explicit allocator passing; `BoundParams` carries its
  allocator so the caller's `deinit` path is uniform.
- camelCase function names are a Zig idiom; the language-neutral
  `bound_params_for_arity` renders as `boundParamsForArity`.
