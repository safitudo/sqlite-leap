---
name: targets/rust
kind: mapping
inherits:
  - /spec/type-system.spec.md
  - /schema/shape.schema.json
---

# Rust emission mapping

How to render a `shapes.json` file as idiomatic Rust. The generator
consumes a leaf's `shapes.json` plus its `master.md` (prose
semantics) and applies these rules.

## Primitive type table

| Neutral | Rust |
|---------|------|
| `bool` | `bool` |
| `i8`..`i64` | `i8`..`i64` |
| `u8`..`u64` | `u8`..`u64` |
| `f32`, `f64` | `f32`, `f64` |
| `PC` | `usize` |
| `str` | `&'src str` |
| `bytes` | `&'src [u8]` |
| `string` | `String` |
| `blob` | `Vec<u8>` |
| `unit` | `()` |

**Lifetime inference.** If any field, parameter, or return type
anywhere in a type or function definition references `str`, `bytes`,
or a user-defined type that transitively borrows, the emitted
Rust item carries a single `<'src>` lifetime. If no borrows appear,
no lifetime is emitted.

## Constructor table

| Neutral | Rust |
|---------|------|
| `{ "option": T }` | `Option<T>` |
| `{ "list": T }` | `Vec<T>` |
| `{ "borrow": T }` | `&T` (adds `'src` if T transitively borrows) |
| `{ "mut": T }` | `&mut T` |
| `{ "owned": T }` | `T` |
| `{ "result": { "ok": T, "err": E } }` | `Result<T, E>` |
| `{ "tuple": [A, B, ...] }` | `(A, B, ...)` |

## Aggregates

### `alias`

```
types.PC = { "kind": "alias", "of": "u64" }
```

→ `pub type PC = u64;`

### `opaque`

```
types.Register = { "kind": "opaque", "representation": "u32" }
```

→ tuple-struct newtype with `Copy`, `Clone`, `Eq`, `Hash` derives:

```rust
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct Register(pub u32);
```

### `record`

```
types.Foo = { "kind": "record", "fields": { "x": "i64", "name": "string" } }
```

→ struct with `pub` fields + `#[derive(Clone, Debug)]`:

```rust
#[derive(Clone, Debug)]
pub struct Foo {
    pub x: i64,
    pub name: String,
}
```

### `variant`

```
types.OpcodeControl = {
  "kind": "variant",
  "cases": {
    "Return": { "fields": {} },
    "Goto":   { "fields": { "target": "PC" } }
  }
}
```

→ Rust enum. Empty-field cases render as unit variants; non-empty
render as struct variants. `#[derive(Clone, Debug)]`:

```rust
#[derive(Clone, Debug)]
pub enum OpcodeControl {
    Return,
    Goto { target: usize },
}
```

Never use tuple-variants in the output; struct-variants everywhere
for uniformity.

## Functions and methods

### Free functions (`functions.<name>`)

```
"execute": {
  "params": [
    { "name": "op",    "type": { "borrow": "OpcodeControl" } },
    { "name": "state", "type": { "mut":    "VdbeState" } }
  ],
  "returns": "OpcodeOutcome"
}
```

→ `pub fn execute(op: &OpcodeControl, state: &mut VdbeState<'src>) -> OpcodeOutcome`

Lifetimes applied per the inference rule above.

### Methods (`methods.<TypeName>[]`)

Methods render inside a single `impl` block per type:

```
methods.VdbeState = [
  { "name": "pc", "receiver": "borrow", "params": [], "returns": "PC" },
  { "name": "set_pc", "receiver": "mut", "params": [{ "name": "pc", "type": "PC" }], "returns": "unit" }
]
```

→

```rust
impl<'src> VdbeState<'src> {
    pub fn pc(&self) -> usize { /* ... */ }
    pub fn set_pc(&mut self, pc: usize) { /* ... */ }
}
```

Method receiver maps: `"borrow"` → `&self`, `"mut"` → `&mut self`.

### Error returns

`{ "result": { "ok": T, "err": E } }` → `Result<T, E>`. Generated
bodies should use `?` for propagation where natural.

### Infallible panics

Well-formedness violations (the generator can reason about these
from master.md prose) may panic with `unreachable!("...")`. Do not
panic on user data paths.

## Constants

```
"constants": { "RETURN_STACK_MAX_DEPTH": { "type": "usize", "value": 64 } }
```

→ `pub const RETURN_STACK_MAX_DEPTH: usize = 64;`

## Naming

- Types, variants: PascalCase (as declared in `shapes.json`).
- Functions, fields, methods, params: snake_case (as declared).
- Constants: SCREAMING_SNAKE_CASE.
- Module path: the leaf's `emits.rust.path` minus `.rs`, with `/` → `::`.

## File layout strategy

- **Strategy:** single-file per part.
- **Path derivation:** given a part `name`, the emitted file is:
  - Leaf: `src-rust/<name-with-underscores>.rs`
  - Inner: `src-rust/<name-with-underscores>/mod.rs`
  - Hyphens in the name become underscores (Rust doesn't allow hyphens in module paths).
- **Examples:**
  - `core` → `src-rust/core.rs`
  - `vdbe/opcodes-control` → `src-rust/vdbe/opcodes_control.rs`
  - `vdbe` (inner) → `src-rust/vdbe/mod.rs`
- **Cross-part imports:** resolved from `shapes.json.imports` via `use crate::<path>::<TypeName>;` — path mirrors the owning part's name (hyphens → underscores), never includes `mod`.
- **Override hook:** a part MAY declare `emits.rust.path` in front-matter to override the derived path. Rare — reserve for adapters and legacy integration.

## File skeleton

Each emitted `.rs` file starts with:

```rust
// Generated from <leaf master.md> + <leaf shapes.json>.
// Do not edit by hand.

use crate::core::*;           // adjust to imports in shapes.json
// ... per-leaf imports resolved from shapes.json `imports` map
```

Then types, then constants, then methods (`impl` blocks), then free
functions. `#[cfg(test)]` inline tests at the bottom.

## Ownership rules

- `owned<string>` / `owned<blob>` carry `String` / `Vec<u8>` with
  implicit `Drop` — no extra release logic needed.
- Cloning is explicit: `.clone()` at the call site.
- A `borrow<T>` in a parameter position may not be stored in a field
  of the receiver unless the receiver also carries `'src`. This is a
  soft rule enforced by Rust's borrow checker — generator does not
  need to add extra logic.

## Panics policy

`panic = "abort"` is assumed at the crate level (declared in
Cargo.toml by the root generator). Allocator failures are therefore
infallible panics, matching the neutral OOM policy.
