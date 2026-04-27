---
name: prepared-statement/targets/python
kind: mapping
inherits:
  - /parts/targets/python/mapping.md
---

# Python mapping — prepared-statement

## Toolchain

- **Python**: 3.10+.
- **stdlib**: `dataclasses`, `enum`, `typing`. No third-party deps.

## Type rendering

| Shape | Python |
|---|---|
| `PreparedStatement` | `@dataclass class PreparedStatement: program: Program; arity: int` |
| `BoundParams` | `@dataclass class BoundParams: values: list[Value]` |
| `StepResult` | tagged-union ABC with `StepResultRow`, `StepResultDone`, `StepResultError(condition)` subclasses |
| `PrepareError` | exception base with `ParseFailure(error)` and `CompileFailure(error)` subclasses |
| `BindError` | `class BindError(Exception): ...; @dataclass class SlotOutOfRange(BindError): slot: int; arity: int` |

## Function signatures

```python
def prepare(db: Database, sql: str) -> PreparedStatement: ...
    # raises PrepareError on failure

def bind(stmt: PreparedStatement, params: BoundParams,
         slot: int, value: Value) -> None: ...
    # raises BindError on slot out of range

def step(stmt: PreparedStatement, params: BoundParams, db: Database) -> StepResult: ...

def reset(stmt: PreparedStatement) -> None: ...

def bound_params_for_arity(arity: int) -> BoundParams: ...
```

## Notes

- Errors raised as exceptions (Python idiom) rather than returned in
  Result-shaped pairs. The spec's `Result` types map to "raises
  PrepareError" / "raises BindError" / "returns StepResult (Error
  variant carries condition)".
- `value` types live in `/parts/core` and use the Python tagged-union
  convention already established for Value (see existing python
  mapping).
