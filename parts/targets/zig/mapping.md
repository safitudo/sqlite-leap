---
name: targets/zig
kind: mapping
inherits:
  - /spec/type-system.spec.md
  - /schema/shape.schema.json
---

# Zig emission mapping

How to render a `shapes.json` as idiomatic Zig.

## Toolchain pin (required)

**Target Zig version:** 0.16.0+ (tested on 0.16.0_1).

Stdlib APIs this mapping relies on — if any are renamed, moved, or
removed upstream, the emission must be re-run against the new
surface (per `feedback_target_toolchain_pin.md`). Hand-patching
src-zig erodes the "generated, not edited" invariant.

| API | Location | Notes |
|---|---|---|
| `std.ArrayList(T)` | `std/array_list.zig` | **Unmanaged variant in 0.16.** No `.init(alloc)` — use `var x: std.ArrayList(T) = .empty;` and pass `alloc` on `.append(alloc, v)`, `.appendSlice(alloc, s)`, `.deinit(alloc)`. |
| `std.ArrayListUnmanaged(T)` | `std/array_list.zig` | Historical alias; prefer `ArrayList`. `.empty` is the canonical zero-value. |
| `std.heap.DebugAllocator(.{})` | `std/heap/debug_allocator.zig` | Replacement for 0.12's `GeneralPurposeAllocator`. |
| `std.Random.DefaultPrng` | `std/Random.zig` | Replaces 0.12's `std.crypto.random`. Seed explicitly; `.random().bytes(&buf)` fills bytes. |
| `std.c.clock_gettime` | `std/c.zig` | Replaces 0.12's `std.time.timestamp()`. CLOCK_REALTIME = 0. Darwin/Linux/BSD-portable via libc. |
| `std.c.timespec` | `std/c.zig` | `.sec` + `.nsec` fields; pass to `clock_gettime`. |
| `std.posix.system.clock_gettime` | `std/posix.zig` | Alternate path without libc linkage. |
| `std.process.Init` | `std/process.zig` | New in 0.16 — `pub fn main(init: std.process.Init) !void` is the blessed entry shape when you need args/env. |
| `std.process.Args.Iterator.initAllocator` | `std/process.zig` | Replaces 0.12's `std.process.argsAlloc`. |

## Canonical leaf symbol renames (camelCase everywhere)

All `storage.*` functions use camelCase in Zig emission:
`closeCursor` (not `close_cursor`), `openReadCursor`, `cursorSeekGe`,
etc. This is the same convention as the rest of the Zig stdlib.
Snake-case in shapes.json gets remapped at emission time.

(Detailed constructor rendering rules live under "Functions and
methods → Constructors" below.)

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

### Recursive variants (self-referencing fields)

A variant whose field type transitively references its own name
(e.g. `Expr` with `Binary { lhs: Expr, rhs: Expr }`) uses a pointer
to the recursive type: `*Expr`. The allocator is passed through the
constructor/parser function (Zig convention — no ambient allocator).

```zig
pub const Expr = union(enum) {
    int_lit: struct { text: []const u8 },
    binary:  struct { op: BinaryOp, lhs: *Expr, rhs: *Expr },
    // ...
};
```

`{ "list": "Expr" }` renders as `std.ArrayListUnmanaged(Expr)` — no
extra pointer. Recursive children are owned by their parent node:
a `destroy` method must recurse before freeing.

**Result-location aliasing rule (Zig 0.16+, MANDATORY).** When
assigning a recursive-variant struct literal to a variable that also
appears as an operand inside the literal, hoist the recursive child
constructions into named locals FIRST. Zig's result-location
semantics otherwise read partially-overwritten memory mid-construction,
producing silently-corrupt AST nodes (valid tag, garbage payload).

```zig
// WRONG — reads `lhs` while it's being overwritten
lhs = .{ .binary = .{ .op = op, .lhs = boxExpr(alloc, lhs), .rhs = rhs_box } };

// RIGHT — hoist boxing into a local, then assign
const lhs_box = boxExpr(alloc, lhs);
lhs = .{ .binary = .{ .op = op, .lhs = lhs_box, .rhs = rhs_box } };
```

Applies anywhere a variable is both the destination and a transitively-read
operand: Pratt parsers, recursive compilers, tree transformers.

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

### Constructors

Neutral `constructors.TypeName = [{ "name": "new", ... }]` renders as
`pub fn <camelCaseName>(...) TypeName` inside the type's struct body.
For types whose internal representation requires heap allocation
(slice fields, `std.ArrayList`, etc.), a Zig-convention `allocator:
std.mem.Allocator` parameter is prepended to the declared parameter
list and the return type becomes `std.mem.Allocator.Error!TypeName`.
This per-target augmentation does NOT leak back into other targets'
rendering — it's how Zig idiomatically expresses "this ctor allocates":

```
constructors.VdbeState = [{
  "name": "new",
  "params": [
    { "name": "num_registers",  "type": "u32" },
    { "name": "num_cursors",    "type": "u32" },
    { "name": "num_aggregates", "type": "u32" },
    { "name": "num_windows",    "type": "u32" },
    { "name": "db",             "type": { "borrow": "Database" } }
  ],
  "returns": "VdbeState"
}]
```

→

```zig
pub fn new(
    allocator: std.mem.Allocator,
    num_registers: u32,
    num_cursors: u32,
    num_aggregates: u32,
    num_windows: u32,
    db: *const Database,
) std.mem.Allocator.Error!VdbeState { /* ... */ }
```

Every Zig constructor pairs with a `pub fn deinit(self: *VdbeState)
void` that releases heap-owned payloads (registers, cursors,
aggregates, windows). `deinit` is NOT declared in `shapes.json` — it's
a Zig-only lifetime counterpart to the declared constructor. Other
targets have no analogous method.

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

## Subquery dispatch ctx (Pin α17-zig-nested-in)

Spec source: `parts/compiler/parts/select-compile/master.md` §"Subqueries
and materialization (α17)" — pin 27 + L985-996 ("schema resolution for
inner SELECTs").

Rust threads the schema registry via a thread-local consulted from the
single-schema entry `compile_select`. Zig has no thread-local equivalent;
the registry is parameter-passed as `sub_schemas`. Concretely:

- `compileSelectWithDb` / `compileSelectWithSchemas` install
  `sub_schemas`; `compileSingleTableFull` reads it and allocates a
  `SubCtx` when present.
- `materializeInnerSelect` recursively compiles the inner SELECT. The
  inner compile MUST also see `sub_schemas` — otherwise nested
  IN/EXISTS/scalar subqueries inside the inner WHERE/projection defer
  with "deferred: IN subquery" / "deferred: scalar subquery" /
  "deferred: EXISTS subquery", because the inner's `sub_ctx_active` is
  false.

Rule: route the inner compile through `compileSingleTableSub(alloc,
inner, schema, ctx.schemas)` whenever the inner is a simple single-
table SELECT (no compound / no GROUP BY / no HAVING / no aggregate or
window in projection). For richer shapes, fall back to
`compileSelect(alloc, inner, schema)` — the aggregate path is currently
sub-ctx-unaware; broadening it is a follow-up. Discriminator must
inspect `inner.compound`, `inner.group_by`, `inner.having`, and walk
each projection expr for `aggKindFor` / `exprContainsWindow`.

## Multi-schema entry delegates to single-schema entry (Pin α23a)

Spec source: `parts/compiler/parts/select-compile/master.md` and
`parts/compiler/parts/aggregates/master.md`.

`compileSelectMulti` (multi-table dispatch) and `compileSelectWithSchemas`
(subquery-aware dispatch) MUST NOT short-circuit on AST shape (GROUP BY,
HAVING, compound, aggregate, window) and reject with DEFER. The full
feature dispatch lives in `compileSelect` (single-schema entry):
window-mode fork, aggregate fork, GROUP BY / HAVING, compound. When the
incoming SELECT's FROM is `.named` and resolves against the schema
registry, the multi-table / subquery-aware entry MUST delegate to
`compileSelect(alloc, stmt, schema)` rather than emit a DEFER.

Rationale: short-circuit guards at the public entry mask working
single-schema infrastructure. This regression pattern recurred at least
4 times in the v2 corpus push (Pin 84 compound; Pin α17 subquery; α22
compound mixed-fold; α23a GROUP BY / HAVING). Each time the working
implementation existed; the public entry simply refused to invoke it.

Rule: at every public `compileSelect*` entry, before any DEFER on
GROUP BY / HAVING / compound / aggregate / window, check whether the
FROM is `.named` and the schema is resolvable. If yes, forward to
`compileSelect`. Keep DEFER strictly for shapes that genuinely lack
single-schema implementations (`.joined` with GROUP BY, `.subquery` in
FROM, etc.) — and for those, emit a DEFER message that names the
specific shape, not a generic "deferred: GROUP BY".

## Tests

Zig has first-class `test` blocks. Generator emits inline tests at
the bottom of each leaf's file, mirroring the Rust leaf's test suite:

```zig
test "truthy null is false" {
    const v = Value.null;
    try std.testing.expect(!valueIsTruthy(&v));
}
```
