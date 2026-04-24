---
name: vdbe/opcodes-window
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /schema/opcode.schema.json
  - /parts/core/master.md
  - /parts/vdbe/master.md
  - /parts/vdbe/parts/opcodes-agg/master.md
emits:
  c: { path: src-c-v2/vdbe/opcodes_window.c, headers: [src-c-v2/vdbe/opcodes_window.h] }
  rust: { path: src-rust-v2/vdbe/opcodes_window.rs }
---

# Part: vdbe/opcodes-window

Window-function execution. Row-number counter; partition boundary
detection; per-row aggregate-as-window output.

## Canonical enum shape

### Rust

```rust
use crate::core::Register;
use crate::vdbe::opcodes_agg::{AccumulatorSlot, AggFuncKind};

pub type WindowSlot = u32;

pub enum WindowKind {
    RowNumber,
    Rank,
    DenseRank,
    Aggregate(AggFuncKind),   // SUM() OVER (...), COUNT() OVER (...), etc.
}

pub enum OpcodeWindow {
    WindowOpen          { slot: WindowSlot, kind: WindowKind, n_partition_keys: u32, n_order_keys: u32 },
    WindowStep          { slot: WindowSlot, arg_reg: Option<Register> },
    WindowValue         { slot: WindowSlot, dest_reg: Register },
    WindowPartitionKey  { slot: WindowSlot, key_idx: u32, dest_reg: Register },
    WindowClose         { slot: WindowSlot },
}
```

## Per-opcode semantics

All return `OpcodeOutcome::Continue` on success (or `Halt` on
illegal op). None emit rows directly — window output feeds back
into the compiler's projection pipeline via `WindowValue` into a
register.

| Name | Semantics |
|---|---|
| `WindowOpen` | Allocate a window session in `VdbeState::windows[slot]`. Reset per-partition state. |
| `WindowStep` | Feed a row into the window. For aggregate windows: apply `arg_reg`'s value via the underlying aggregate step. For RowNumber/Rank/DenseRank: advance counters per ORDER BY comparison. |
| `WindowValue` | Read the current window function's value for the active row into `regs[dest_reg]`. RowNumber → Integer; Rank/DenseRank → Integer; Aggregate → the aggregate's current finalized value (same rules as AggFinal but read-only). |
| `WindowPartitionKey` | Read the current partition's `key_idx`-th key component into `regs[dest_reg]`. Used by the outer scan to detect partition boundaries. |
| `WindowClose` | Free the window session. |

## Frame clauses

Out of scope for v2. Compiler rejects `ROWS BETWEEN ...` at compile
time with `COMPILE_WINDOW_FRAME_UNSUPPORTED`. Runtime never sees a
frame spec.

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
