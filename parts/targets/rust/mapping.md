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

## Toolchain pin (required)

**Target Rust version:** edition 2021, rustc 1.75+ (tested on stable 1.80).

Stdlib + crate surfaces this mapping relies on. If any are renamed,
split, or removed upstream, the emission must be re-run against the
new surface (per `feedback_target_toolchain_pin.md`). Hand-patching
src-rust erodes the "generated, not edited" invariant.

| API | Module | Notes |
|---|---|---|
| `Vec<T>` / `Box<T>` | `alloc`/std | Default growable list for `list<T>`. |
| `String` / `&str` / `&[u8]` | std | `string` → `String`; `str`/`bytes` → `&str`/`&[u8]`. |
| `Option<T>` / `Result<T, E>` | core | `option` / `result` TypeRefs emit verbatim. |
| `std::mem::take` / `replace` | std::mem | Register/slot `take_*` operations (index-over-borrow idiom). |
| `HashMap` / `BTreeMap` | std::collections | Only when prose specifies map-like aggregate + ordering. |
| `fn(...) -> ...` | core | `fn` TypeRefs emit as bare fn pointers (zero-capture callbacks). |
| dev-dep `serde_json = "1"` | — | For eq-harness runners only; **never** imported from lib code. |
| dev-dep `base64 = "0.22"` | — | For blob round-tripping in eq-harness corpus. Dev-only. |

## Storage codecs

For leaves using on-disk file-format grammar (`varint_be`,
`list_sized_by`, `codec`, `u*_be` big-endian primitives),
Rust's canonical decoders:

### Big-endian integer primitives

Use `u16::from_be_bytes` / `u32::from_be_bytes` / `u64::from_be_bytes`
/ `i64::from_be_bytes` / `f64::from_be_bytes` for power-of-2 widths:

| Primitive | Rust |
|---|---|
| `u8` | `data[off]` |
| `i8` | `data[off] as i8` |
| `u16_be` | `u16::from_be_bytes(data[off..off+2].try_into().unwrap())` |
| `u32_be` | `u32::from_be_bytes(data[off..off+4].try_into().unwrap())` |
| `u64_be` | `u64::from_be_bytes(data[off..off+8].try_into().unwrap())` |
| `i16_be`/`i32_be`/`i64_be` | same with `iN::from_be_bytes` |
| `f64_be` | `f64::from_be_bytes(data[off..off+8].try_into().unwrap())` |

For odd widths (`u24_be`, `i24_be`, `i48_be`), build from bytes:

```rust
fn read_u24_be(data: &[u8], off: usize) -> u32 {
    ((data[off] as u32) << 16) | ((data[off+1] as u32) << 8) | (data[off+2] as u32)
}
fn read_i48_be(data: &[u8], off: usize) -> i64 {
    let mut v: i64 = 0;
    for i in 0..6 { v = (v << 8) | data[off+i] as i64; }
    // Sign-extend from 48 bits.
    if v & (1i64 << 47) != 0 { v |= !0i64 << 48; }
    v
}
```

### `varint_be` — SQLite 1–9 byte big-endian huffman varint

```rust
/// Returns (value, bytes_consumed in 1..=9).
fn read_varint_be(data: &[u8], off: usize) -> (i64, usize) {
    let mut v: u64 = 0;
    for i in 0..8 {
        let b = data[off + i];
        v = (v << 7) | ((b & 0x7F) as u64);
        if b & 0x80 == 0 {
            return (v as i64, i + 1);
        }
    }
    // 9th byte: take all 8 bits.
    v = (v << 8) | data[off + 8] as u64;
    (v as i64, 9)
}
```

### `SqliteSerialTypeSequence` codec

Decodes the cell body's `(record_header_length_varint,
serial_type_1_varint, ..., serial_type_N_varint, body_bytes)`
into a `Vec<Value>` per the serial-type table. Signature:

```rust
fn decode_serial_type_sequence(
    data: &[u8], off: usize, total_payload: usize
) -> Vec<Value>
```

Implementation: read `header_length` varint, then read varints
until consumed == header_length; that's the list of serial types.
Walk the body using the widths from the serial-type table. Serial
types: 0 → Null; 1..6 → signed big-endian integers of width
{1,2,3,4,6,8}; 7 → f64_be; 8 → Integer(0); 9 → Integer(1); 10,11
reserved; N≥12 even → Blob of length (N-12)/2; N≥13 odd → Text of
length (N-13)/2.

### `list_sized_by` binding

Emit as a `for i in 0..count` loop against the sibling field:

```rust
let header = decode_page_header(data, off);
let pointers: Vec<u16> = (0..header.cell_count)
    .map(|i| u16::from_be_bytes(
        data[off + 8 + 2*i as usize..off + 10 + 2*i as usize]
            .try_into().unwrap()))
    .collect();
```

### `when`-gated fields

Emit as `Option<T>` with a conditional bind:

```rust
let right_child: Option<u32> = if matches!(page_type, 0x02 | 0x05) {
    Some(u32::from_be_bytes(data[off+8..off+12].try_into().unwrap()))
} else {
    None
};
```

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

### Recursive variants (self-referencing fields)

A variant whose field type transitively references the variant's own
name (e.g. `Expr` with `Binary { lhs: Expr, rhs: Expr }`) must be
rendered with `Box<Self>` at each recursive field in Rust, since a
Rust enum cannot contain itself by value.

```
types.Expr = {
  "kind": "variant",
  "cases": {
    "Binary": { "fields": { "lhs": "Expr", "rhs": "Expr" } }
  }
}
```

→

```rust
pub enum Expr {
    Binary { lhs: Box<Expr>, rhs: Box<Expr> },
}
```

`{ "list": "Expr" }` stays `Vec<Expr>` (Vec already heap-allocates);
no Box wrap needed inside a list.

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

## Pin 19.1 strategy declarations

Per `parts/storage/parts/btree-write/master.md` §"Pin 19.1
implementation strategies":

- **btree-write mutation strategy: B (deferred re-encode at COMMIT).**
  `cursor_delete_row` / `cursor_update_row` / non-monotonic
  `cursor_insert_row` mark `MemTable.btree.stream_invalid = true`;
  `pager_commit_transaction` calls `finalize_path_btrees` which
  re-encodes invalid tables from sorted mem-store. Monotonic-rowid
  INSERT keeps the streaming-append fast path (P19-S3).
- **Paged-read flag default:** `Pager.cursor_use_paged_reads = false`
  at pin 19.1. Mem-store rows remain the in-session read source;
  paged reads are exercised by validation probes only. Lifting the
  flag to `true` requires a corpus regression check.

Sibling targets (C/Zig/Go/Python) are free to adopt either Strategy
A or B at their pin 19.3 landing; their mapping.md declares the
choice.

## Panics policy

`panic = "abort"` is assumed at the crate level (declared in
Cargo.toml by the root generator). Allocator failures are therefore
infallible panics, matching the neutral OOM policy.
