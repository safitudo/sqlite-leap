# LEAP type system — language-neutral vocabulary

This file is the prose companion to `/schema/shape.schema.json`. It
explains the vocabulary each `shapes.json` file uses to declare the
types and functions a part owns. Every construct here has a
mechanical mapping in each target's `/parts/targets/<target>/mapping.md`.

No Rust, no C, no other target-language syntax appears in this file
by design. Authors writing a `shapes.json` should never need to think
about how a target will render it.

## Primitive types

Referenced by bare-string name in a `TypeRef`:

- Booleans: `bool`
- Signed integers: `i8`, `i16`, `i32`, `i64`
- Unsigned integers: `u8`, `u16`, `u32`, `u64`
- Floats: `f32`, `f64` (IEEE-754)
- Program counter: `PC` (opaque unsigned; target decides width — usually pointer-sized)
- Borrowed text: `str` (UTF-8 view over a source buffer)
- Borrowed bytes: `bytes` (view over a source buffer)
- Owned text: `string` (heap-owned UTF-8)
- Owned bytes: `blob` (heap-owned byte sequence)
- Unit: `unit` (no payload; used as the success arm of a result with nothing to return)

## Constructors

A `TypeRef` is either a primitive/named type (string) or a
single-key object that wraps another `TypeRef`:

| Construct | Meaning |
|---|---|
| `{ "option": T }` | `T` may be present or absent. Absence is an explicit state, not a sentinel. |
| `{ "list": T }` | Ordered homogeneous sequence of `T`. |
| `{ "borrow": T }` | Read-only reference to a `T` owned elsewhere. Must not outlive its source. |
| `{ "mut": T }` | Mutable reference to a `T` owned elsewhere. |
| `{ "owned": T }` | Explicit ownership transfer. Equivalent to a bare `T` in most contexts; use for clarity. |
| `{ "result": { "ok": T, "err": E } }` | Success with `T` or failure with `E`. Functions that can fail declare this. |
| `{ "tuple": [A, B, ...] }` | Fixed-arity heterogeneous sequence. |

Authors can nest constructors freely:
`{ "option": { "borrow": "str" } }` = "maybe a borrowed string."

## Aggregates (type definitions)

Four `kind` values under `types.<Name>`:

- **`alias`** — non-opaque rename of an existing type. Callers may treat alias and target interchangeably.
- **`opaque`** — distinct nominal type. The representation may be hinted but callers must not introspect it. Targets emit a newtype or opaque handle.
- **`record`** — product type with named fields. Field order is stable across targets.
- **`variant`** — tagged union. Each case is either empty (no fields) or carries a record of named fields. There is no positional tuple form — use a record with generic field names if positional semantics are desired.

### Variant case forms

```
"Return":           { "fields": {} }          // unit case
"Goto":             { "fields": { "target": "PC" } }   // record case (one field)
"EmitRow":          { "fields": { "start": "Register", "count": "u32" } }  // record case (multi-field)
```

All variant cases are record-shaped. Unit cases have an empty fields
object. This keeps the target mapping uniform: every case name maps
to a variant constructor; every field within a case maps to a member.

## Functions and methods

A function is declared under either `functions` (free) or `methods.<TypeName>[]`:

```
"execute": {
  "params": [
    { "name": "op",    "type": { "borrow": "OpcodeControl" } },
    { "name": "state", "type": { "mut":    "VdbeState" } }
  ],
  "returns": "OpcodeOutcome"
}
```

For methods, the receiver is implicit; declare how it's taken via
`"receiver": "borrow" | "mut"`. Methods render as
target-idiomatic (method call in Rust; prefixed free function taking
the receiver explicitly in C).

## Error handling convention

A function that can fail declares `"returns": { "result": { "ok": T, "err": E } }`.
The target mapping renders this in its preferred way — a real
`Result` type in Rust, a return code plus out-parameter in C.
Authors never write target-specific error handling.

## Cross-part imports

A part may reference types defined elsewhere by listing them in its
`imports` map:

```
"imports": {
  "Register":   "/parts/core",
  "PC":         "/parts/core",
  "Value":      "/parts/core",
  "VdbeState":  "/parts/vdbe"
}
```

Primitive names (`bool`, `i64`, etc.) do not need imports.

## Versioning & evolution

Adding a new `variant` case is a breaking change (exhaustive matches
in targets need updating). Adding a new `record` field is breaking
unless the target mapping supports default values (most do not by
default). Treat `shapes.json` as a source artifact under the same
review discipline as `master.md`.

## What this vocabulary deliberately omits

- Generics / type parameters. If needed, add as a follow-up. For v2,
  every type is monomorphic.
- Traits / interfaces. Behavioral contracts live in prose; no
  structural interface type. If a target wants trait-based polymorphism,
  the mapping can introduce it locally (e.g., a trait for a closed set
  of variants), but the neutral vocabulary does not require it.
- Lifetime annotations. Borrow-tracking is a semantic rule enforced
  by prose + target mapping; authors never annotate.
- Async / concurrency primitives. All declared functions are
  synchronous. If async is introduced later, it will be a new
  constructor, not an ambient annotation.
