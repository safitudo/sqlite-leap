---
name: targets/zig
kind: mapping
inherits:
  - /spec/type-system.spec.md
  - /schema/shape.schema.json
---

# Zig emission mapping

How to render a `shapes.json` as idiomatic Zig (0.12+).

## Primitive type table

| Neutral | Zig |
|---------|-----|
| `bool` | `bool` |
| `i8`..`i64` | `i8`..`i64` |
| `u8`..`u64` | `u8`..`u64` |
| `f32`, `f64` | `f32`, `f64` |
| `PC` | `usize` |
| `str` | `[]const u8` (UTF-8 convention; Zig has no distinct string type) |
| `bytes` | `[]const u8` |
| `string` | `[]u8` (heap-allocated via a provided allocator) |
| `blob` | `[]u8` |
| `unit` | `void` |

## Constructor table

| Neutral | Zig |
|---------|-----|
| `{ "option": T }` | `?T` |
| `{ "list": T }` | `[]T` (or `std.ArrayList(T)` where growth is required — master.md prose decides) |
| `{ "borrow": T }` | `*const T` |
| `{ "mut": T }` | `*T` |
| `{ "owned": T }` | `T` (by value when small; by pointer when T carries heap-allocated payload — decide per type; document in prose) |
| `{ "result": { "ok": T, "err": E } }` | `E!T` (Zig error union) |
| `{ "tuple": [A, B, ...] }` | anonymous `struct { A, B, ... }` |

Zig error unions require `E` to be an error set type. For
`RuntimeCondition`, emit a single error set that mirrors the variant
cases; see Aggregates → Variant-of-unit-cases below.

## Aggregates

### `alias`

```
types.PC = { "kind": "alias", "of": "u64" }
```

→ `pub const PC = u64;`

### `opaque`

With `representation`:

```
types.Register = { "kind": "opaque", "representation": "u32" }
```

→ one-field struct (Zig lacks newtypes; the wrapper struct supplies
nominal distinction):

```zig
pub const Register = struct {
    value: u32,

    pub fn init(v: u32) Register {
        return .{ .value = v };
    }
};
```

Without `representation`: emit a forward-declared opaque struct:

```zig
pub const VdbeState = opaque {};
```

### `record`

```
types.Foo = { "kind": "record", "fields": { "x": "i64", "name": "string" } }
```

→

```zig
pub const Foo = struct {
    x: i64,
    name: []u8,
};
```

### `variant`

Two forms depending on whether any case has fields:

**All-unit** (every case has `fields: {}`): emit as a plain enum.
Also emit a parallel `error set` if the variant is used as the `err`
arm of a `result<_, ThisVariant>`:

```zig
pub const RuntimeCondition = enum {
    opcode_illegal,
    cursor_closed,
    // ...
};

pub const RuntimeConditionError = error {
    OpcodeIllegal,
    CursorClosed,
    // ...
};
```

The error set uses PascalCase names (Zig's error convention); the
plain enum uses snake_case (Zig's enum-field convention). A helper
converts between them.

**Any non-unit case**: emit a tagged union. Use the tag-enum syntax
so callers can switch cleanly:

```zig
pub const OpcodeControlTag = enum {
    goto,
    if_,
    if_not,
    jump_if_null,
    gosub,
    return_,
};

pub const OpcodeControl = union(OpcodeControlTag) {
    goto: struct { target: usize },
    if_: struct { cond_reg: Register, target: usize },
    if_not: struct { cond_reg: Register, target: usize },
    jump_if_null: struct { reg: Register, target: usize },
    gosub: struct { target: usize },
    return_: void,
};
```

Zig reserves `if`, `return`, `goto` (the last only partially).
Reserved-word case names get a trailing underscore. Empty-field
cases use `void` as the case type.

## Functions and methods

### Free functions

```
"execute": {
  "params": [
    { "name": "op",    "type": { "borrow": "OpcodeControl" } },
    { "name": "state", "type": { "mut":    "VdbeState" } }
  ],
  "returns": "OpcodeOutcome"
}
```

→

```zig
pub fn execute(op: *const OpcodeControl, state: *VdbeState) OpcodeOutcome {
    // ...
}
```

### Methods

Methods are rendered as functions inside the type's declaration, with
the receiver as the first argument:

```
methods.VdbeState = [
  { "name": "pc", "receiver": "borrow", "params": [], "returns": "PC" },
  { "name": "set_pc", "receiver": "mut", "params": [{ "name": "pc", "type": "PC" }], "returns": "unit" }
]
```

→

```zig
pub const VdbeState = opaque {
    pub fn pc(self: *const VdbeState) usize { /* ... */ }
    pub fn setPc(self: *VdbeState, new_pc: usize) void { /* ... */ }
};
```

Method names convert snake_case to camelCase per Zig convention.
Parameter names that shadow the method name or built-ins are
suffix-renamed (e.g., `pc` → `new_pc` when the enclosing method is
named `setPc`).

### Error returns

`{ "result": { "ok": T, "err": "RuntimeCondition" } }` renders as
the error union over `RuntimeConditionError`:

```zig
pub fn returnStackPush(self: *VdbeState, pc: usize) RuntimeConditionError!void { /* ... */ }
pub fn returnStackPop(self: *VdbeState) RuntimeConditionError!usize { /* ... */ }
```

Callers use `try` for propagation: `const target = try state.returnStackPop();`

## Constants

```
"constants": { "RETURN_STACK_MAX_DEPTH": { "type": "u32", "value": 64 } }
```

→ `pub const RETURN_STACK_MAX_DEPTH: u32 = 64;`

## Naming

- Types, variants' tag-enum variants used as errors: PascalCase.
- Enum field names (tagged-union tags): snake_case with trailing
  underscore on keyword collisions.
- Functions, methods: camelCase.
- Free functions in a "library" role (pub fn on top level): camelCase.
- Constants: SCREAMING_SNAKE_CASE.
- File names: snake_case.

## Ownership

- `owned<string>` / `owned<blob>` — Zig has no ownership model in
  its type system. The emission convention: any function that
  returns an owned `[]u8` also takes an `allocator: std.mem.Allocator`
  parameter, and the caller is responsible for
  `allocator.free(result)` when done.
- `borrow<T>` (emitted as `*const T`) — caller retains ownership.

## Error unions and RuntimeCondition

For a target using Zig error unions, `RuntimeCondition` (as a
closed set of unit cases) gets a dual emission:

1. A plain `enum` for cases used as values (storage in structs, etc.).
2. An `error set` with the same names (PascalCased) for use in error
   unions.

A conversion helper lives in the owning leaf:

```zig
pub fn conditionToError(c: RuntimeCondition) RuntimeConditionError { /* ... */ }
pub fn errorToCondition(e: RuntimeConditionError) RuntimeCondition { /* ... */ }
```

The mapping does not require these helpers on every leaf; only the
owning leaf (parts/core) emits them.

## File layout strategy

- **Strategy:** single-file per part.
- **Path derivation:**
  - Leaf: `src-zig/<name-with-underscores>.zig`
  - Inner: `src-zig/<name-with-underscores>/mod.zig`
  - Hyphens in the name become underscores (Zig accepts both but underscores are idiomatic).
- **Examples:**
  - `core` → `src-zig/core.zig`
  - `vdbe/opcodes-control` → `src-zig/vdbe/opcodes_control.zig`
  - `vdbe` (inner) → `src-zig/vdbe/mod.zig`
- **Cross-part imports:** `@import("../core.zig")` etc., using the relative path from the current leaf to the imported leaf's file.
- **Override hook:** `emits.zig.path` in front-matter.

### File skeleton

```zig
// Generated from <leaf paths>. Do not edit by hand.

const std = @import("std");
// Cross-leaf imports resolved per the `imports` map in shapes.json:
const core = @import("../core.zig");

// Types, constants, methods, functions in that order.
```

## Tests

Zig has first-class `test` blocks. Generator emits inline tests at
the bottom of each leaf's file, mirroring the Rust leaf's test suite:

```zig
test "truthy null is false" {
    const v = Value.null;
    try std.testing.expect(!valueIsTruthy(&v));
}
```
