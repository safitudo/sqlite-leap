---
name: compiler/window
kind: leaf
inherits:
  - /parts/compiler/parts/expressions/master.md
  - /parts/compiler/parts/aggregates/master.md
  - /parts/vdbe/parts/opcodes-window/master.md
emits:
  c: { path: src-c/compiler/window.c, headers: [src-c/compiler/window.h] }
  rust: { path: src-rust/src/compiler/window.rs }
---

# Part: compiler/window

Compiles window functions: `OVER ([PARTITION BY ...] [ORDER BY ...])`
and the canonical `ROW_NUMBER()`. v2 scope is deliberately narrow —
enough to pass v1's window fixtures (Phase 6bk).

## Public interface

```
compile_window_call(
    call:         &WindowCall<'src>,
    spec:         &WindowSpec<'src>,
    ctx:          &CompileContext,
    dest_reg:     Register,
    program_out:  &mut ProgramBuilder,
) -> Result<(), CompileError>
```

Delegated to by `parts/expressions/` when it encounters a
`WindowCall` AST (aggregate call with an OVER clause).

## Supported window functions

- `ROW_NUMBER()` — integer sequence within partition.
- `RANK()` / `DENSE_RANK()` — ranking per ORDER BY within partition.
- Aggregate-as-window: `SUM() OVER (...)`, `COUNT(*) OVER (...)`,
  etc. — use the aggregate's accumulator with per-row emission.

## Compilation strategy

1. Materialize the base query's rows into a buffer (sort-sensitive).
2. Partition the buffer by `PARTITION BY` expressions.
3. Within each partition, iterate in `ORDER BY` order. Compute the
   window function per row; store in the row's output slot.
4. Emit rows in original (or user-ordered) sequence.

Frame clauses (`ROWS BETWEEN ...`) are **out of scope** for v2's
initial cut — spec documents them as future work, compiler rejects
frame specifications with `COMPILE_WINDOW_FRAME_UNSUPPORTED` to
preserve forward compat.

## Phase pins

- **Phase 6bk** — WINDOW functions (ROW_NUMBER + simple OVER).

## Regeneration envelope

- Target leaf size: 400–600 lines per target.
- Spec < 150 lines.
