---
name: targets/python
kind: mapping
inherits:
  - /spec/type-system.spec.md
  - /schema/shape.schema.json
---

# Python emission mapping

How to render a `shapes.json` as idiomatic Python 3.10+.

Python has no native sum types; the mapping uses **frozen dataclass
hierarchies with a common marker base class**, combined with
`match`/`case` at call sites. Errors use **exceptions** — the native
Python idiom — rather than `Result`-style return tuples.

## Primitive type table

| Neutral | Python |
|---------|--------|
| `bool` | `bool` |
| `i8`..`i64` | `int` (Python ints are arbitrary-precision; unchecked width) |
| `u8`..`u64` | `int` (same — add a runtime check in the owning leaf if width matters) |
| `f32`, `f64` | `float` |
| `PC` | `int` |
| `str` | `str` |
| `bytes` | `bytes` |
| `string` | `str` |
| `blob` | `bytes` |
| `unit` | `None` |

## Constructor table

| Neutral | Python |
|---------|--------|
| `{ "option": T }` | `T \| None` (PEP 604) |
| `{ "list": T }` | `list[T]` |
| `{ "borrow": T }` | `T` (Python has no borrow tracking; document in prose) |
| `{ "mut": T }` | `T` (same) |
| `{ "owned": T }` | `T` |
| `{ "result": { "ok": T, "err": E } }` | return `T`, raise exception on error — see Error handling below |
| `{ "tuple": [A, B, ...] }` | `tuple[A, B, ...]` |

## Aggregates

### `alias`

```
types.PC = { "kind": "alias", "of": "u64" }
```

→ `PC = int` (module-level type alias). Add a `# type: PC = int`
comment for readability; do not use `typing.NewType` unless strong
type-checker distinction is required.

### `opaque`

With `representation`: use a frozen dataclass wrapper so the type
is nominally distinct and comparable:

```
types.Register = { "kind": "opaque", "representation": "u32" }
```

→

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Register:
    value: int
```

Without `representation`: a plain class (users never construct it
directly; the owning module provides factory functions):

```python
class VdbeState:
    """Opaque VDBE execution state. Do not instantiate directly."""
    __slots__ = ()  # subclasses fill in
```

### `record`

```
types.Foo = { "kind": "record", "fields": { "x": "i64", "name": "string" } }
```

→

```python
@dataclass(frozen=True, slots=True)
class Foo:
    x: int
    name: str
```

`frozen=True` for immutability at the Python level (matches the
neutral spec's value-semantics default). `slots=True` for memory
and attribute-safety.

### `variant`

**All-unit cases** (every case has `fields: {}`): emit as a Python
`Enum`:

```python
from enum import Enum, auto

class RuntimeCondition(Enum):
    OPCODE_ILLEGAL = auto()
    CURSOR_CLOSED = auto()
    # ...
```

Plus a subclass of `Exception` with the same name + `Error` suffix
for use in `raise`:

```python
class RuntimeConditionError(Exception):
    def __init__(self, condition: RuntimeCondition):
        super().__init__(condition.name)
        self.condition = condition
```

**Any non-unit case**: emit a frozen-dataclass hierarchy under a
common marker base class:

```
types.OpcodeControl = {
  "kind": "variant",
  "cases": {
    "Goto":   { "fields": { "target": "PC" } },
    "Return": { "fields": {} }
  }
}
```

→

```python
from dataclasses import dataclass
from typing import Union

class OpcodeControl:
    """Base marker. Do not instantiate directly — use a case subclass."""
    __slots__ = ()

@dataclass(frozen=True, slots=True)
class OpcodeControlGoto(OpcodeControl):
    target: int  # PC

@dataclass(frozen=True, slots=True)
class OpcodeControlReturn(OpcodeControl):
    pass
```

A `Union` alias at the end of the file exposes the closed set for
static type checkers:

```python
OpcodeControlAny = Union[OpcodeControlGoto, OpcodeControlReturn]
```

Dispatch uses `match` (Python 3.10+):

```python
match op:
    case OpcodeControlGoto(target=t):
        return OpcodeOutcomeJump(target=t)
    case OpcodeControlReturn():
        # ...
```

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

```python
def execute(op: OpcodeControl, state: VdbeState) -> OpcodeOutcome:
    ...
```

Naming: snake_case for functions (PEP 8).

### Methods

Methods become regular Python methods on the class:

```
methods.VdbeState = [
  { "name": "pc", "receiver": "borrow", "params": [], "returns": "PC" },
  { "name": "set_pc", "receiver": "mut", "params": [{ "name": "pc", "type": "PC" }], "returns": "unit" }
]
```

→

```python
class VdbeState:
    def pc(self) -> int:
        ...

    def set_pc(self, pc: int) -> None:
        ...
```

Python has no `borrow`/`mut` distinction — both receivers map to
`self`. Read-only semantics live in the docstring.

### Error returns

`{ "result": { "ok": T, "err": E } }` → function returns `T`
directly; failures **raise** an exception:

- When `E` is a unit-only variant (like `RuntimeCondition`): raise
  the parallel `RuntimeConditionError` with the specific condition.
- When `E` carries data: define a dedicated exception class whose
  `__init__` captures the variant payload.

Example:

```python
def return_stack_push(self, pc: int) -> None:
    if self._depth >= RETURN_STACK_MAX_DEPTH:
        raise RuntimeConditionError(RuntimeCondition.OPCODE_ILLEGAL)
    # ...

def return_stack_pop(self) -> int:
    if not self._stack:
        raise RuntimeConditionError(RuntimeCondition.OPCODE_ILLEGAL)
    return self._stack.pop()
```

Callers use `try`/`except RuntimeConditionError` or let the
exception propagate.

## Constants

```
"constants": { "RETURN_STACK_MAX_DEPTH": { "type": "u32", "value": 64 } }
```

→ `RETURN_STACK_MAX_DEPTH: int = 64` (module-level, SCREAMING_SNAKE_CASE).

## Naming

- Modules, functions, variables, parameters: snake_case.
- Classes, variant cases (dataclasses): PascalCase.
- Enum members (unit-variant cases): SCREAMING_SNAKE_CASE.
- Constants: SCREAMING_SNAKE_CASE.
- Private attributes/methods: leading underscore (`_depth`, `_stack`).

## Ownership

Python is reference-counted (CPython) / GC'd. No explicit
release. Mutability is by convention — frozen dataclasses enforce
value semantics at the Python level. The mapping's job is only to
reflect which fields/params are read-only (in comments) and to keep
variant cases immutable by default.

## File layout strategy

- **Strategy:** single-file per leaf, `__init__.py` per intermediate package directory (emitted by the root generator).
- **Path derivation:**
  - Leaf: `src-python/<name-with-underscores>.py`
  - Inner: `src-python/<name-with-underscores>/__init__.py`
  - Hyphens become underscores (Python identifiers disallow hyphens).
- **Examples:**
  - `core` → `src-python/core.py`
  - `vdbe/opcodes-control` → `src-python/vdbe/opcodes_control.py`
  - `vdbe` (inner) → `src-python/vdbe/__init__.py`
- **Intermediate package files:** any nested leaf (e.g., `vdbe/opcodes-control`) requires `src-python/vdbe/__init__.py` to exist. The ROOT generator emits these as empty or minimal re-export files; individual leaves do not emit them.
- **Cross-leaf imports:** `from leap_sqlite.<path> import <Name>`, using the root package name `leap_sqlite` (project-wide constant).
- **Override hook:** `emits.python.path` in front-matter.

```python
from leap_sqlite.core import Register, Value, OpcodeOutcome
from leap_sqlite.vdbe import VdbeState
```

## Tests

Inline tests under `if __name__ == "__main__":` aren't scalable;
emit `tests/test_<basename>.py` using `pytest`-compatible functions:

```python
def test_truthy_null_is_false() -> None:
    assert not value_is_truthy(ValueNull())
```

For this demo, inline `unittest.TestCase` at the bottom of the
emitted file is acceptable.

## Type-checker friendliness

The emission is intended to pass `mypy --strict` and `pyright`:

- Use `Union[...]` or `|` for sum types (prefer `|` on 3.10+).
- Avoid `Any` — if the neutral spec is loose, flag it as a mapping
  gap rather than escaping via `Any`.
- `__slots__` on dataclasses reduces both memory and attribute typos.
- `@dataclass(frozen=True, slots=True)` is the default; relax only
  when the neutral spec explicitly allows mutation of a field.

## File skeleton

```python
# Generated from <leaf paths>. Do not edit by hand.
"""Short one-liner from master.md prose."""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import Union

# Cross-leaf imports resolved per the shapes.json `imports` map.
# from leap_sqlite.core import ...

# Types (aliases, opaques, records, variants) in declaration order.
# Constants.
# Methods on opaque classes (grouped under the class).
# Free functions.
```
