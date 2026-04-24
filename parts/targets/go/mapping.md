---
name: targets/go
kind: mapping
inherits:
  - /spec/type-system.spec.md
  - /schema/shape.schema.json
---

# Go emission mapping

How to render a `shapes.json` as idiomatic Go (1.21+).

Go has no native sum types; the mapping uses the **marker-interface
pattern** (a la `go/ast`, `database/sql`, `encoding/xml`) for
variants. Pattern-match at the call site with a type switch.

## Primitive type table

| Neutral | Go |
|---------|----|
| `bool` | `bool` |
| `i8`..`i64` | `int8`..`int64` |
| `u8`..`u64` | `uint8`..`uint64` |
| `f32`, `f64` | `float32`, `float64` |
| `PC` | `uint64` |
| `str` | `string` (Go strings are immutable byte sequences; UTF-8 by convention) |
| `bytes` | `[]byte` |
| `string` | `string` (same Go type serves both `str` and `string` roles; Go's GC handles lifetime) |
| `blob` | `[]byte` |
| `unit` | (empty — `unit` in a return slot means the function returns no value) |

## Constructor table

| Neutral | Go |
|---------|----|
| `{ "option": T }` | `*T` (pointer; `nil` = absent) |
| `{ "list": T }` | `[]T` |
| `{ "borrow": T }` | `*T` (Go has no const; document immutability in prose) |
| `{ "mut": T }` | `*T` |
| `{ "owned": T }` | `T` (by value) |
| `{ "result": { "ok": T, "err": E } }` | return tuple `(T, error)` where `error` is wrapped around `E`; see Error returns below |
| `{ "tuple": [A, B, ...] }` | struct `{ F0 A; F1 B; ... }` declared per call site, or an anonymous return tuple `(A, B, ...)` |

## Aggregates

### `alias`

```
types.PC = { "kind": "alias", "of": "u64" }
```

→ `type PC = uint64`

### `opaque`

With `representation`:

```
types.Register = { "kind": "opaque", "representation": "u32" }
```

→ defined type over the representation (Go's only newtype-like form):

```go
type Register uint32
```

No wrapper struct; the distinct type name carries the nominal
boundary.

Without `representation` (heap-managed opaque):

```go
type VdbeState struct {
    // unexported fields; accessors below
}
```

### `record`

```
types.Foo = { "kind": "record", "fields": { "x": "i64", "name": "string" } }
```

→ struct with exported fields (PascalCase):

```go
type Foo struct {
    X    int64
    Name string
}
```

### `variant` — marker-interface pattern

Given:

```
types.OpcodeControl = {
  "kind": "variant",
  "cases": {
    "Goto": { "fields": { "target": "PC" } },
    "Return": { "fields": {} }
  }
}
```

Emit:

1. A marker interface with a private method unique to this variant.
2. One struct per case, each implementing the marker.

```go
// OpcodeControl is the marker interface for the control-opcode family.
// The unexported isOpcodeControl method prevents external types from
// satisfying it.
type OpcodeControl interface {
    isOpcodeControl()
}

// OpcodeControlGoto — unconditional jump to Target.
type OpcodeControlGoto struct {
    Target uint64
}

func (OpcodeControlGoto) isOpcodeControl() {}

// OpcodeControlReturn — pop the return stack and jump.
type OpcodeControlReturn struct{}

func (OpcodeControlReturn) isOpcodeControl() {}
```

Unit cases become empty structs so the ABI stays uniform (a zero-size
value is idiomatic for markers in Go).

Dispatch at call site:

```go
switch op := op.(type) {
case OpcodeControlGoto:
    return OpcodeOutcomeJump{Target: op.Target}
case OpcodeControlReturn:
    // ...
}
```

### Parallel kind enum (optional)

For variants used as return codes (e.g., `RuntimeCondition`), a
plain enum form is more ergonomic. When a variant's cases are ALL
unit (no fields), prefer the enum form over the interface form:

```go
type RuntimeCondition int

const (
    RuntimeConditionOpcodeIllegal RuntimeCondition = iota
    RuntimeConditionCursorClosed
    // ...
)

func (c RuntimeCondition) Error() string { /* switch / name table */ }
```

The enum form implements `error` when used as the `err` arm of a
`result<_, RuntimeCondition>`. Rule: if every case has
`fields: {}`, emit the enum form; otherwise, the interface form.

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

```go
func Execute(op OpcodeControl, state *VdbeState) OpcodeOutcome { /* ... */ }
```

Note: `borrow<OpcodeControl>` maps to `OpcodeControl` (interface
value) rather than `*OpcodeControl` because Go passes interface
values by reference semantics under the hood.

### Methods

Methods are rendered as method definitions on the receiver type:

```
methods.VdbeState = [
  { "name": "pc", "receiver": "borrow", "params": [], "returns": "PC" },
  { "name": "set_pc", "receiver": "mut", "params": [{ "name": "pc", "type": "PC" }], "returns": "unit" }
]
```

→

```go
func (s *VdbeState) Pc() uint64 { /* ... */ }
func (s *VdbeState) SetPc(pc uint64) { /* ... */ }
```

`receiver: "borrow"` → pointer receiver (convention: pointer so
the method can access unexported fields; add a doc comment
"read-only" when semantics forbid mutation).
`receiver: "mut"` → pointer receiver.

### Error returns

`{ "result": { "ok": T, "err": E } }`:

- When `T == unit`: `func (...) error`
- Otherwise: `func (...) (T, error)`

`E = RuntimeCondition` (an enum implementing `error`) is used as
the error value directly:

```go
func (s *VdbeState) ReturnStackPush(pc uint64) error { /* ... */ }
func (s *VdbeState) ReturnStackPop() (uint64, error) { /* ... */ }
```

Callers use the standard `if err != nil { return err }` pattern.

## Constants

```
"constants": { "RETURN_STACK_MAX_DEPTH": { "type": "u32", "value": 64 } }
```

→ `const ReturnStackMaxDepth uint32 = 64`

## Naming

- Exported types, functions, fields, constants: PascalCase.
- Unexported (private): camelCase.
- Variant case structs: `<VariantType><CaseName>` (e.g., `OpcodeControlGoto`).
- Marker methods: `is<VariantType>` (private, lowercase `i`).
- Package names: single lowercase word, no underscores.

## File layout strategy

- **Strategy:** package-dir (one directory per part, each directory is a Go package).
- **Path derivation:**
  - Leaf at name `<parent-path>/<basename>`: `src-go/<parent-path-underscored>/<basename-underscored>/<basename-underscored>.go`. The directory IS the Go package; the file inside uses the package's name.
  - Leaf at top-level name `<basename>`: `src-go/<basename-underscored>/<basename-underscored>.go`.
  - Inner: `src-go/<name-underscored>/<basename-underscored>.go` with nested package dirs for children.
  - Hyphens become underscores (Go package names can only contain letters and digits; underscores discouraged but accepted for generated code).
- **Package declaration:** first line of body is `package <basename-underscored>`.
- **Examples:**
  - `core` → `src-go/core/core.go` with `package core`
  - `vdbe/opcodes-control` → `src-go/vdbe/opcodes_control/opcodes_control.go` with `package opcodes_control`
- **Cross-package imports:** `import "<MODULE_ROOT>/<path>"`, where `MODULE_ROOT` is the project-wide Go module path (`github.com/safitudo/leap-sqlite`) declared at the repo root and used everywhere.
- **Override hook:** `emits.go.path` in front-matter.
- **Test files:** generator ALSO emits `<basename>_test.go` in the same package dir when the leaf declares tests.

## Ownership

Go is garbage-collected; no explicit release is required. The
mapping's role is purely documentary: comments note which function
results are "fresh allocations" vs "borrowed views" (the latter
meaning: do not mutate, do not retain beyond the call).

## Tests

Go's built-in `testing` package. Each leaf emits a
`<basename>_test.go` alongside the main file:

```go
func TestTruthyNullIsFalse(t *testing.T) {
    v := ValueNull{}
    if valueIsTruthy(v) {
        t.Error("Null should not be truthy")
    }
}
```

## File skeleton

```go
// Generated from <leaf paths>. Do not edit by hand.

package <leaf-basename>

import (
    // Cross-leaf packages per shapes.json `imports` map.
)

// Types, constants, methods, functions.
```
