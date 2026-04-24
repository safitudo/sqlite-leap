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

## Toolchain pin (required)

**Target Python version:** 3.10+ (tested on 3.10, 3.11, 3.12).
Reason: `match`/`case` structural pattern matching is load-bearing
for variant dispatch; this is a 3.10+ feature.

Stdlib surfaces this mapping relies on:

| API | Module | Notes |
|---|---|---|
| `@dataclass(frozen=True, slots=True)` | dataclasses | Variant case shells. `slots=True` matters for RSS footprint. |
| `typing.Union`, `Optional`, `Any` | typing | `option<T>` → `Optional[T]`; `result<T, E>` raises an exception instead. |
| `match`/`case` | language | Dispatch on variant via `case OpcodeFoo(field=_): ...` patterns. |
| `abc.ABC` | abc | Marker base class for each variant's closed hierarchy. |
| `struct.unpack_from` | struct | On-disk big-endian reads (`>H`, `>I`, `>Q`, `>d`). |
| `int.from_bytes(b, 'big', signed=...)` | builtin | For odd widths (`i24_be`, `i48_be`) not covered by struct. |
| `base64.b64encode` / `b64decode` | base64 | Blob round-tripping in eq-harness corpus only. |
| `json.dumps` / `loads` | json | For eq-harness runners; **never** from lib code. |
| `pathlib.Path` | pathlib | Path handling in runners + tests. |

**Forbidden on emitted lib code:** no `import unittest`, no
`class ...Test*`, no `if __name__ == "__main__":` guards, no
`_Stub*` placeholder classes. See §"Generation scope" in
part-conventions.spec.md.

**Package layout:** all emitted library code lives under
`src-python/leap_sqlite/<part_path>/<leaf>.py`. Runners (not
library) may live under `src-python/` directly.

## Storage codecs

For leaves using on-disk file-format grammar (`varint_be`,
`list_sized_by`, `codec`, `u*_be` big-endian primitives),
Python's canonical decoders:

### Big-endian integer primitives

Use `struct.unpack_from` for widths 1 / 2 / 4 / 8:

| Primitive | Python |
|---|---|
| `u8` / `i8` | `data[off]` / `struct.unpack_from(">b", data, off)[0]` |
| `u16_be` | `struct.unpack_from(">H", data, off)[0]` |
| `u32_be` | `struct.unpack_from(">I", data, off)[0]` |
| `u64_be` | `struct.unpack_from(">Q", data, off)[0]` |
| `i16_be` / `i32_be` / `i64_be` | same with `>h` / `>i` / `>q` |
| `f64_be` | `struct.unpack_from(">d", data, off)[0]` |

For non-power-of-2 widths (24-bit, 48-bit), use
`int.from_bytes(data[off:off+N], "big", signed=...)`.

### `varint_be` — SQLite 1–9 byte big-endian huffman varint

```python
def read_varint_be(data: bytes, off: int) -> tuple[int, int]:
    """Returns (value as signed int64, bytes_consumed in 1..9)."""
    v = 0
    for i in range(8):
        b = data[off + i]
        v = (v << 7) | (b & 0x7F)
        if (b & 0x80) == 0:
            return (v - (1 << 64) if v >= (1 << 63) else v, i + 1)
    # 9th byte: consume all 8 bits.
    v = (v << 8) | data[off + 8]
    return (v - (1 << 64) if v >= (1 << 63) else v, 9)
```

### `SqliteSerialTypeSequence` codec

Decodes the cell body's `(record_header_length, type_1, ...,
type_N, body_bytes)` per the serial-type table. Signature:

```python
def decode_serial_type_sequence(
    data: bytes, off: int, total_payload: int
) -> list[dict]:
    """Returns a list of Value dicts: {"t": "Null"|"Integer"|"Real"|
    "Text"|"Blob", "v": <value>} (v omitted when t == "Null")."""
```

Implementation: read `header_length` varint, then read varints
until consumed == header_length; that's the list of serial types.
Walk the body using the widths from the serial-type table.

### `list_sized_by` binding

Emit as a `range(cell_count)` loop, with `cell_count` resolved
from the sibling field already decoded:

```python
header = decode_page_header(data, off)
pointers = [
    struct.unpack_from(">H", data, off + 8 + 2*i)[0]
    for i in range(header.cell_count)
]
```

### `when`-gated fields

Emit as `Optional[T]` with a conditional assignment:

```python
right_child: Optional[int] = None
if page_type in (0x02, 0x05):
    right_child = struct.unpack_from(">I", data, off + 8)[0]
```

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

### Recursive variants (self-referencing fields)

Python references are implicit: a dataclass field whose type annotation
is the enclosing class name just works at runtime. Use a string
forward-reference to satisfy the type checker. `list[Expr]` needs no
special handling.

```python
@dataclass(frozen=True)
class ExprBinary:
    op: BinaryOp
    lhs: "Expr"
    rhs: "Expr"

Expr = ExprIntLit | ExprBinary | ExprUnary | ...
```

Because Python's dataclass equality is structural, recursive equality
works naturally without an explicit walker.

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

- **Strategy:** single-file per leaf, `__init__.py` per intermediate package directory (emitted by the root generator). The top-level `src-python/leap_sqlite/` directory IS the `leap_sqlite` package root — callers add `src-python/` to `sys.path`, then `from leap_sqlite.<path> import <Name>` resolves via Python's normal import machinery (no shim).
- **Path derivation:**
  - Leaf: `src-python/leap_sqlite/<name-with-underscores>.py`
  - Inner: `src-python/leap_sqlite/<name-with-underscores>/__init__.py`
  - Hyphens become underscores (Python identifiers disallow hyphens).
- **Examples:**
  - `core` → `src-python/leap_sqlite/core.py`
  - `vdbe/opcodes-control` → `src-python/leap_sqlite/vdbe/opcodes_control.py`
  - `vdbe` (inner) → `src-python/leap_sqlite/vdbe/__init__.py`
- **Intermediate package files:** any nested leaf (e.g., `vdbe/opcodes-control`) requires `src-python/leap_sqlite/vdbe/__init__.py` to exist. The ROOT generator emits these as empty or minimal re-export files; individual leaves do not emit them. The top-level `src-python/leap_sqlite/__init__.py` itself is also emitted (empty is fine) so the package imports cleanly.
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
