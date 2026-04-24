---
name: targets/c
kind: mapping
inherits:
  - /spec/type-system.spec.md
  - /schema/shape.schema.json
---

# C emission mapping

How to render a `shapes.json` file as idiomatic C99+. The generator
consumes a leaf's `shapes.json` plus its `master.md` (prose
semantics) and applies these rules.

## Primitive type table

| Neutral | C |
|---------|---|
| `bool` | `bool` (from `<stdbool.h>`) |
| `i8`..`i64` | `int8_t`..`int64_t` |
| `u8`..`u64` | `uint8_t`..`uint64_t` |
| `f32`, `f64` | `float`, `double` |
| `PC` | `size_t` |
| `str` | `struct LeapStr { const char* ptr; size_t len; }` — borrowed |
| `bytes` | `struct LeapBytes { const uint8_t* ptr; size_t len; }` — borrowed |
| `string` | `LeapText` — owned (see parts/core emission) |
| `blob` | `LeapBlob` — owned (see parts/core emission) |
| `unit` | `void` (return position only) |

## Constructor table

| Neutral | C |
|---------|---|
| `{ "option": T }` | `struct { bool has_value; T value; }` — anonymous-inline or named per leaf |
| `{ "list": T }` | `struct { T* ptr; size_t len; }` — fixed-view form; growable lists use `{ T* ptr; size_t len; size_t cap; }` per master.md prose |
| `{ "borrow": T }` | `const T*` |
| `{ "mut": T }` | `T*` |
| `{ "owned": T }` | `T` (by value when small; `T*` caller-frees when T carries a heap payload — decide per type based on size; document in prose) |
| `{ "result": { "ok": T, "err": E } }` | function returns `E`; caller passes `T* out` (omit when `T == unit`) |
| `{ "tuple": [A, B, ...] }` | anonymous `struct { A f0; B f1; ... }` named per call site |

### Result rendering detail

For a function declared as `returns: { result: { ok: <T>, err: <E> } }`:

| T | Signature |
|---|---|
| `unit` | `E leap_<name>(args);` |
| anything else | `E leap_<name>(args, T* out_<value>);` |

Generator names the out-parameter `out_<lastReturnWord>` or
`out_value` if no obvious noun applies.

## Aggregates

### `alias`

```
types.PC = { "kind": "alias", "of": "u64" }
```

→ `typedef uint64_t LeapPC;` (but `PC` is a built-in primitive above,
so this specific case doesn't apply — aliases of primitives just
`typedef`).

### `opaque`

```
types.Register = { "kind": "opaque", "representation": "u32" }
```

→ transparent typedef (C has no newtype discipline; the `Leap`
prefix carries the nominal distinction):

```c
typedef uint32_t LeapRegister;
```

For heap-managed opaque types (no `representation` hint):

```c
typedef struct LeapCursor LeapCursor;  // forward-declared; internals in the owning .c
```

### `record`

```
types.Foo = { "kind": "record", "fields": { "x": "i64", "name": "string" } }
```

→

```c
typedef struct LeapFoo {
    int64_t    x;
    LeapText   name;
} LeapFoo;
```

### `variant`

**Two emission forms** depending on case shapes:

**Form A — all-unit variant** (every case has `fields: {}`). Emit
as a bare enum. When this variant is used as the `err` arm of a
`result<_, ThisVariant>`, reserve `_OK = 0` as the success
sentinel and start the declared cases at 1:

```c
typedef enum LeapRuntimeCondition {
    LEAP_RC_OK = 0,  // reserved success sentinel — used when this
                      // variant is the err arm of a result<_, _>
    LEAP_RC_OPCODE_ILLEGAL,
    LEAP_RC_CURSOR_CLOSED,
    // ...
} LeapRuntimeCondition;
```

Case names are SHOUTY_SNAKE and use the variant's short form
(`LEAP_RC_` for `RuntimeCondition`; pick a ≤ 4-letter prefix per
all-unit variant). The mapping emits a header-level `#define`
of the prefix if the natural long form is unwieldy.

Functions that return `result<T, ThisVariant>` compare against
`LEAP_RC_OK` to branch success vs error — no wrapping struct, no
`kind` field, no `.as.error.condition`.

**Form B — at least one non-unit case.** Emit the tagged-struct
form: a `Kind` enum plus a struct with a union:

```c
typedef enum LeapOpcodeControlKind {
    LEAP_OPCODE_CONTROL_RETURN = 0,
    LEAP_OPCODE_CONTROL_GOTO,
} LeapOpcodeControlKind;

typedef struct LeapOpcodeControl {
    LeapOpcodeControlKind kind;
    union {
        struct { size_t target; } goto_;
    } as;
} LeapOpcodeControl;
```

Empty-field cases inside a Form-B variant have no union member (only
the discriminator matters).

Union-field name: the case name lowered to snake_case; if the
snake_case form collides with a C keyword (`goto`, `return`, `if`,
etc.), suffix a single underscore.

**Choosing a form** is mechanical: if any case has a non-empty
`fields` map, use Form B. Otherwise use Form A.

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

```c
LeapOpcodeOutcome leap_opcode_control_execute(
    const LeapOpcodeControl* op,
    LeapVdbeState*           state
);
```

Function name: `leap_` + the leaf's owning-type prefix (snake_case)
+ `_` + function name. For opcode-family leaves, the prefix is the
variant type itself (e.g., `opcode_control`).

### Methods

```
methods.VdbeState = [
  { "name": "pc", "receiver": "borrow", "params": [], "returns": "PC" },
  { "name": "set_pc", "receiver": "mut", "params": [{ "name": "pc", "type": "PC" }], "returns": "unit" }
]
```

→ free functions with the receiver as the first parameter, named
`leap_<type_snake>_<method>`:

```c
size_t leap_vdbe_state_pc(const LeapVdbeState* state);
void   leap_vdbe_state_set_pc(LeapVdbeState* state, size_t pc);
```

`receiver: "borrow"` → `const LeapType* <type_snake>`
`receiver: "mut"`    → `LeapType* <type_snake>`

### Error returns

`{ "result": { "ok": <T>, "err": "RuntimeCondition" } }` →
function returns `LeapRuntimeCondition`. Success sentinel is
`LEAP_RC_OK`; any other value is a fault.

## Constants

```
"constants": { "RETURN_STACK_MAX_DEPTH": { "type": "size_t", "value": 64 } }
```

→ `#define LEAP_RETURN_STACK_MAX_DEPTH ((size_t) 64)` or
`static const size_t LEAP_RETURN_STACK_MAX_DEPTH = 64;` — prefer the
static const form unless the constant must be preprocessor-visible.

## Naming

- Types: `Leap` + PascalCase (the name from `shapes.json`).
- Enum constants: `LEAP_` + SHOUTY_SNAKE version of the type name +
  `_` + SHOUTY_SNAKE of the case name. Example:
  `LEAP_OPCODE_CONTROL_JUMP_IF_NULL`.
- Functions: `leap_` + snake_case of the owning type + `_` +
  snake_case of the function name.
- Struct fields: snake_case of the neutral field name.
- Header guard: `#ifndef LEAP_<PATH>_H` where PATH is the file path
  SHOUTY-snake'd (`leap/vdbe/opcodes_control.h` →
  `LEAP_VDBE_OPCODES_CONTROL_H`).

## Ownership rules

- `owned<string>` / `owned<blob>` carry heap payloads. Any function
  that returns one by value transfers ownership; the caller is
  responsible for eventual `leap_value_release` (or
  `leap_text_release` / `leap_blob_release` for the primitive types).
- Any path that OVERWRITES a field holding an owned-payload value
  must call the appropriate release function on the old value FIRST,
  then assign the new value. This is the C analog of Rust's
  move-assign drop.
- `borrow<T>` (emitted as `const T*`) never takes ownership. The
  caller guarantees lifetime.

## OOM policy

Allocator failures (`malloc` / `realloc` / `strdup` returning NULL)
return `LEAP_RC_IO_ERROR` per the neutral OOM policy (no
dedicated OOM condition in v2). Functions whose signature cannot
report an error (`void` returns, infallible constructors) may abort
via `abort()` on OOM — but prefer to thread an error up instead.

## File layout strategy

- **Strategy:** header + implementation pair.
- **Path derivation:** given a part `name`, emit two files:
  - Leaf: `src-c/<name-with-underscores>.h` (types + prototypes) AND `src-c/<name-with-underscores>.c` (implementations).
  - Inner: `src-c/<name-with-underscores>/mod.h` AND `src-c/<name-with-underscores>/mod.c`.
  - Hyphens in the name become underscores.
- **Examples:**
  - `core` → `src-c/core.h` + `src-c/core.c`
  - `vdbe/opcodes-control` → `src-c/vdbe/opcodes_control.h` + `src-c/vdbe/opcodes_control.c`
- **Cross-file reference:** the `.c` file begins with `#include "<basename>.h"`. Cross-part includes use the relative path from the current leaf to the imported leaf's header: `#include "../core.h"`, `#include "vdbe/opcodes_control.h"`, etc.
- **Override hook:**
  - `emits.c.path` / `emits.c.headers` in front-matter to override derived paths.
  - `emits.c.extra_headers` to declare additional private headers (e.g., `src-c/storage/btree_internal.h`).

### Header skeleton

```c
// Generated from <leaf paths>. Do not edit by hand.
#ifndef LEAP_<PATH>_H
#define LEAP_<PATH>_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Cross-leaf includes (resolved from shapes.json `imports` map)
#include "../core.h"

// Types, constants, function prototypes here.

#endif /* LEAP_<PATH>_H */
```

### Implementation skeleton

```c
// Generated from <leaf paths>. Do not edit by hand.
#include "<basename>.h"

// Static helpers first, then public functions.
```

`LEAP_<PATH>_H` guard uses the file path in SHOUTY_SNAKE. Example:
`src-c/vdbe/opcodes_control.h` → `LEAP_VDBE_OPCODES_CONTROL_H`.
