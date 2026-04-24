---
name: vdbe/opcodes-window
kind: leaf
inherits:
  - /schema/opcode.schema.json
  - /parts/vdbe/parts/opcodes-agg/master.md
  - /parts/compiler/parts/window/master.md
emits:
  c: { path: src-c/vdbe/opcodes_window.c, headers: [src-c/vdbe/opcodes_window.h] }
  rust: { path: src-rust/src/vdbe/opcodes_window.rs }
---

# Part: vdbe/opcodes-window

Window-function execution. Row-number counter; partition boundary
detection; per-row aggregate-as-window output.

## Opcodes owned here

| Name | Semantics |
|---|---|
| `WindowOpen(spec)` | Begin a window session with the given PartitionBy/OrderBy spec. Allocates partition state. |
| `WindowStep(arg_regs)` | Feed one row's values into the window. |
| `WindowValue(dest_reg)` | Read current window function's value for the active row. |
| `WindowPartitionKey(dest_reg)` | Read current partition key (for boundary detection). |
| `WindowClose` | End the window session. |

## ROW_NUMBER semantics

Per partition, assign 1, 2, 3, ... in ORDER BY order. Reset on
partition boundary.

## RANK / DENSE_RANK

- `RANK`: 1, 2, 2, 4, ... — gaps after ties.
- `DENSE_RANK`: 1, 2, 2, 3, ... — no gaps.

## Aggregate-as-window

`SUM() OVER (...)`, `COUNT() OVER (...)`, etc. — use the aggregate
from `opcodes-agg` but emit a per-row `WindowValue` instead of a
per-group `AggFinal`.

## Frame clauses

Out of scope for v2. Compiler rejects; runtime does not need to
support.

## Phase pins

- **Phase 6bk** — WINDOW functions (ROW_NUMBER + simple OVER).
- **#102** — WINDOW must flow through main compiler/VDBE (both
  targets).

## Regeneration envelope

- Target leaf size: 300–500 lines per target.
- Spec < 100 lines.
