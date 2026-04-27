# Target mapping: scalar-builtins/json1 — Rust

## Toolchain
- rustc: 1.78+ (edition 2021)
- stdlib only; **no serde_json**, no external crates. The core lib
  (`src-rust/`) has zero runtime deps; this module hand-rolls a small
  recursive-descent JSON parser (~200 LOC) and a canonical writer.

## Module layout
- `src-rust/scalar_json1.rs` — public entry: `eval_json1(kind, args)
  -> Value`, dispatches on the new `ScalarKind::Json…` variants.
- Internal types: `JsonNode` enum, `JsonPathSegment` enum, parser /
  writer / path evaluator. None leak outside the module.

## SQL ↔ JSON value mapping
- `Value::Null` → `JsonNode::Null`
- `Value::Integer(i)` → `JsonNode::Integer(i)`
- `Value::Real(f)` → `JsonNode::Real(f)`
- `Value::Text(s)` → if `s` parses as a JSON array/object, embed
  parsed; else `JsonNode::String(s.clone())` (pin 17, 8).
- `Value::Blob(b)` → `JsonNode::String(String::from_utf8_lossy(b).into_owned())`

JSON → SQL (for `json_extract` single-path leaf):
- `Null` → `Value::Null`
- `Bool(b)` → `Value::Integer(if b {1} else {0})`
- `Integer(i)` → `Value::Integer(i)`
- `Real(f)` → `Value::Real(f)`
- `String(s)` → `Value::Text(s)`
- `Array | Object` → `Value::Text(canonical_write(node))`

## Float canonicalization
Rust's default `{}` printing for f64 yields shortest-roundtrip
representation since 1.55 (Grisu/Ryu). When the format would lose the
decimal point (`1.0` printing as `"1"`), append `.0`. This matches
mainline SQLite `%.17g` for our test corpus.

## Error surfacing
All `JsonError` variants → `Value::Null`. The dispatch wrapper is
infallible (matches existing scalar dispatch contract).
