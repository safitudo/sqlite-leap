---
name: prepared-statement/targets/rust
kind: mapping
inherits:
  - /parts/targets/rust/mapping.md
---

# Rust mapping — prepared-statement

## Toolchain

- **rustc**: edition 2021, stable 1.75+ (tested on 1.95).
- **stdlib**: `Vec`, `Option`, `Result`. No third-party deps.

## Type rendering

| Shape | Rust |
|---|---|
| `PreparedStatement` | `pub struct PreparedStatement { pub program: Program, pub arity: u32 }` |
| `BoundParams` | `pub struct BoundParams { pub values: Vec<Value> }` |
| `StepResult` | `pub enum StepResult { Row, Done, Error(RuntimeCondition) }` |
| `PrepareError` | `pub enum PrepareError { ParseFailure(ParseError), CompileFailure(CompileError) }` |
| `BindError` | `pub enum BindError { SlotOutOfRange { slot: u32, arity: u32 } }` |

## Function signatures

```rust
pub fn prepare(db: &Database, sql: &str) -> Result<PreparedStatement, PrepareError>;

pub fn bind(stmt: &PreparedStatement, params: &mut BoundParams,
            slot: u32, value: Value) -> Result<(), BindError>;

pub fn step(stmt: &PreparedStatement, params: &BoundParams, db: &Database) -> StepResult;

pub fn reset(stmt: &mut PreparedStatement);

impl BoundParams {
    pub fn for_arity(arity: u32) -> Self { /* fills with Value::Null */ }
}
```

A target-idiomatic sugar wrapper (Rust-only) MAY combine these into
a `PreparedStatement` impl:

```rust
impl PreparedStatement {
    pub fn bind(&mut self, params: &mut BoundParams, slot: u32, v: Value) -> Result<(), BindError> { ... }
    pub fn step(&self, params: &BoundParams, db: &Database) -> StepResult { ... }
    pub fn reset(&mut self) { ... }
}
```

The free-function and method forms MUST behave identically (Pins
1–7).

## Notes

- Rust's borrow checker prefers the params-out-of-statement split
  (Pin 7) — `bind` takes `&mut BoundParams` while `step` takes
  `&BoundParams + &PreparedStatement` so a single-threaded caller
  can hold both without re-borrow churn.
- Bench-validated wins: 98k → 2.58M ips on Lane 4. The non-prepared
  baseline allocates a fresh AST + Program per INSERT; the prepared
  surface allocates Program once and only the per-step VdbeState
  thereafter.
- The cached-state-on-statement optimization (avoid fresh-VdbeState
  allocation per step) is a Rust-target-private speed-up; spec-side
  it MUST NOT change observable behavior.
