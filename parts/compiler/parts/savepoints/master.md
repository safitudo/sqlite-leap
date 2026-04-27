---
name: compiler/savepoints
kind: leaf
shapes: ./shapes.json
emits:
  rust: { path: src-rust/compiler/savepoints.rs }
  c:    { path: src-c/compiler/savepoints.c, headers: [src-c/compiler/savepoints.h] }
---

# Compile SAVEPOINT / RELEASE / ROLLBACK TO into VDBE programs

Lowers each variant of `SavepointStmt` (declared by
`/parts/parser/parts/savepoint-stmt`) into a tiny VDBE Program that
emits exactly one opcode from the savepoint opcode family declared
by `/parts/vdbe/parts/opcodes-savepoint`.

There is no expression compilation, no register allocation, no
cursor management. Each form lowers to a single opcode whose only
payload is the savepoint name (a string, owned).

## Compile mappings

| AST variant                  | Emitted opcode                                |
|------------------------------|-----------------------------------------------|
| `SavepointStmt::Savepoint`   | `OpcodeSavepoint::Savepoint { name }`         |
| `SavepointStmt::Release`     | `OpcodeSavepoint::ReleaseSavepoint { name }`  |
| `SavepointStmt::RollbackTo`  | `OpcodeSavepoint::RollbackToSavepoint { name }`|

Each compiled program is exactly two opcodes:

```
0: <one-of-the-three savepoint opcodes>
1: Halt(Ok)                     # terminates the program
```

`Halt(Ok)` lives in `/parts/vdbe/parts/opcodes-control` (or
`opcodes-core`, depending on whichever owns the terminal); it is
imported, not redefined here.

## Algorithm

```
compile_savepoint(stmt) -> Program:
    program = empty Program
    case stmt:
        Savepoint { name }:
            program.emit(OpcodeSavepoint::Savepoint { name: copy(name) })
        Release { name }:
            program.emit(OpcodeSavepoint::ReleaseSavepoint { name: copy(name) })
        RollbackTo { name }:
            program.emit(OpcodeSavepoint::RollbackToSavepoint { name: copy(name) })
    program.emit(Halt(Ok))
    return program
```

## Naming and normalization

- The savepoint name is preserved EXACTLY as the parser delivered
  it (no case folding, no whitespace trimming). The runtime stack
  performs name comparison with the same byte-for-byte rule.
- A name MAY shadow an existing savepoint of the same name on the
  stack: declaring `SAVEPOINT a` while another `a` is already on
  the stack pushes a new, deeper `a` frame. Subsequent `RELEASE a`
  / `ROLLBACK TO a` resolve to the **innermost** matching frame
  (LIFO scan from the top). This is mainline-compatible behavior
  per the published lang_savepoint.html semantics.

## Implicit outer transaction

If `Savepoint` is compiled and executed while no transaction is
open, the runtime (see `/parts/storage/parts/savepoints` pin S2)
implicitly opens one. The compiler emits no extra opcode for this:
the opcode handler in the VDBE owns the implicit-begin behavior.

## DDL inside a savepoint

DDL statements (CREATE TABLE, DROP TABLE, ALTER TABLE) are
compile-able and runnable inside a savepoint frame. The schema
delta is captured by the storage layer alongside the page deltas
(see storage pin S6), so a `RollbackTo` reverts schema changes too.
The compiler emits no special prelude for DDL-in-savepoint; it
just compiles DDL normally and trusts the savepoint stack to
journal the schema change as part of the frame.

## Correctness pins

1. **One opcode per AST variant** — `Savepoint` → `Savepoint`
   opcode; `Release` → `ReleaseSavepoint` opcode; `RollbackTo` →
   `RollbackToSavepoint` opcode. No other lowering paths.
2. **Owned name in opcode payload** — the `name` field on each
   emitted opcode is OWNED, not borrowed from the AST. This is
   the same rule that applies elsewhere in the compiler: the
   Program outlives the AST.
3. **Trailing Halt(Ok)** — every compiled savepoint program
   terminates with `Halt(Ok)`. A Program with no terminal Halt
   would run off the end and the VDBE loop reports
   `RuntimeCondition::OpcodeIllegal`.
4. **No register allocation** — savepoint compilation never
   reserves a register, never reads one, never writes one. The
   compiled Program declares `register_count = 0`.
5. **No cursor allocation** — savepoint compilation never opens
   or closes a cursor. The compiled Program declares
   `cursor_count = 0`.
6. **Name preserved verbatim** — case, quoting (post-tokenization),
   embedded whitespace are all preserved as the parser delivered
   them. No normalization in the compiler.
7. **Compile-time always succeeds** — savepoint compilation
   raises no `CompileError`. Every well-formed `SavepointStmt`
   produces a valid Program. Errors (no-such-savepoint,
   stack-overflow) are RUNTIME conditions raised by the storage
   layer's savepoint stack.
8. **DDL pass-through** — a `SAVEPOINT` followed by DDL followed
   by `ROLLBACK TO` requires no special compile-time handling
   for the DDL. The compiler treats DDL as ordinary statements;
   the storage savepoint stack journals schema changes alongside
   page changes (see storage pin S6).
9. **No invented helpers** — the file exports only
   `compile_savepoint`. No cross-part state, no name interning.
10. **No interaction with `BEGIN` / `COMMIT`** — top-level
    transaction control statements are owned by a separate
    `transaction-stmt` part and a separate compiler leaf. This
    part composes with that one through the storage savepoint
    stack only — neither part calls into the other at compile
    time.

## Regeneration envelope

- Line budget: **~80-120 lines** of Rust. A 3-arm match plus
  the trailing `Halt(Ok)` emit.
- Public items: `compile_savepoint`. (No type re-exports; the
  Program and OpcodeSavepoint variants are imported.)

## Smoke probe

`src-rust/examples/compile_savepoint_smoke.rs` (hand-written, NOT
regenerated) parses each of these and asserts the resulting
Program shape:

```text
1. SAVEPOINT a       → [Savepoint{name="a"}, Halt(Ok)]
2. RELEASE a         → [ReleaseSavepoint{name="a"}, Halt(Ok)]
3. ROLLBACK TO a     → [RollbackToSavepoint{name="a"}, Halt(Ok)]
```

Runner prints `OK: all 3 savepoint statements compile to expected
2-opcode programs` on success.
