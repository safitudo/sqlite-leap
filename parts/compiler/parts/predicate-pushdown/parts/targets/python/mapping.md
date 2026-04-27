---
name: predicate-pushdown/targets/python
kind: mapping
inherits:
  - /parts/targets/python/mapping.md
---

# Python mapping — predicate-pushdown

## Toolchain

- **Python**: 3.10+ (uses `match`/`case` and `from __future__ import
  annotations`).
- **stdlib surfaces**: `dataclasses.dataclass`, `enum.Enum`,
  `typing.Optional`. No third-party deps.

Regenerate if Python advances past 3.13 in a way that changes
structural-match-on-class semantics.

## Type rendering

| Shape | Python |
|---|---|
| `PointFetchOk` | `@dataclass class PointFetchOk: opcodes: list[Opcode]; num_registers: int; num_cursors: int; num_aggregates: int; result_count: int; opcode_template_kind: int` |
| `Option<PointFetchOk>` | `Optional[PointFetchOk]` |
| `PushdownTrigger` | `class PushdownTrigger(Enum): ROWID_POINT_FETCH = 0` |
| `EmitOp` | `class EmitOp(Enum): OPEN_READ_CURSOR = 0; KEY_EXPR_COMPILE = 1; ...; EMIT_HALT = 10` |
| `RowidPointFetchTemplate` | `@dataclass class RowidPointFetchTemplate: trigger: PushdownTrigger; steps: list[EmitOp]` |

## Function signatures

```python
def try_compile_point_fetch(
    stmt: SelectStmt, schema: TableSchema
) -> Optional[PointFetchOk]: ...

def find_rowid_index(schema: TableSchema) -> Optional[IndexSpec]: ...

def is_row_independent(expr: Expr) -> bool: ...
```

`CompileError` is raised as a Python exception (matching the existing
expr-compile convention); the function returns `None` for the
"recogniser said no, fall through" signal.

## Notes

- Python target wraps `Option` with `Optional[T]` and uses `None` as
  the discriminator. Standard for the codebase.
- Recogniser uses `match expr: case Expr.Binary(BinaryOp.Eq, lhs,
  rhs): ...` — Python 3.10's structural matching keeps the
  recogniser readable and mirrors the Rust idiom.
