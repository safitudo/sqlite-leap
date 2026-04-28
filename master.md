---
name: root
inherits:
  - /CLAUDE.md
  - /docs/ARCHITECTURE.md
  - /spec/durability.spec.md
---

# sqlite-leap — root part (v2)

You are orchestrating a LEAP project. Specs and tests are the source
of truth. Code is the output. Read `CLAUDE.md` for project framing
and `docs/ARCHITECTURE.md` for the recursive-parts model. Those two
documents plus this file define the contract you work against.

## What this project is

A reimplementation of SQLite generated from a language-neutral
recursive parts tree. Three target builds:

- `src-c/` — C implementation
- `src-rust/` — Rust implementation
- `src-wasm/` — WASM build, compiled from `src-rust/`

All three builds pass the same tests. Cross-build equivalence
(`tests/cross-build/`) is a correctness gate, not a nicety.

## Top-level parts

The root part is **inner**. Its children are the architectural
boundaries of the engine:

- `parts/core/` — shared primitive types (leaf, zero dependencies)
- `parts/tokenizer/` — SQL text → token stream (leaf)
- `parts/parser/` — tokens → AST (inner: per-statement + expressions + clauses)
- `parts/compiler/` — AST → VDBE Program (inner: per-statement + expressions + aggregates + joins + subqueries + cte + window + views + upsert + returning + constraints + name-resolution)
- `parts/vdbe/` — Program execution (inner: opcode families)
- `parts/storage/` — on-disk engine (inner: file-format + btree + pager + wal + index)
- `parts/io-backend/` — async I/O abstraction (inner: iouring + kqueue)
- `parts/executor/` — top-level statement execution driver (leaf)
- `parts/harness/` — runner + CLI + FFI shims (inner: sqllogictest + cli)

Dependency order for generation (compile-time):

```
tokenizer  →  parser  →  compiler  →  vdbe  ←  executor
                                       ↑
                                   storage  ←  io-backend
```

## Cross-cutting specs (stay at /spec/)

### Universal — implicitly inherited by every part

Every part in `/parts/` automatically inherits the following; they
do NOT need to appear in any leaf's `inherits:` block:

- `/spec/part-conventions.spec.md` — front-matter + derivation rules
- `/spec/type-system.spec.md` — neutral type vocabulary
- `/spec/memory-discipline.spec.md` — ownership / borrow rules
- `/schema/shape.schema.json` — meta-schema for `shapes.json`

### Non-universal cross-cutting specs

These are invariants that bind specific parts (not all) and own no
emission. A part lists them in its own `inherits:` only if relevant:

- `/spec/durability.spec.md` — fsync/barrier rules; binds storage +
  io-backend.
- `/spec/sqllogictest-runner.spec.md` — test-runner behavior; binds
  `harness/sqllogictest-runner`.
- `/spec/bench-lanes.spec.md` — benchmark harness contract.
- `/spec/fuzz-corpus.spec.md` — fuzz corpus generation and replay.
- `/spec/ci-infra.spec.md` — CI pipeline expectations.
- `/spec/cli.spec.md` — `sqlite-leap` CLI shape; binds `harness/cli`.
- `/spec/wasm-ffi.spec.md` — WASM boundary contract.

Part-scoped v1 specs (`sql-grammar`, `vdbe-opcodes`, `file-format`,
`wal`, `storage`, `pager-async`, `io-backend*`, `vdbe-interpreter`)
have migrated into their owning parts' `master.md` files. They no
longer live in `/spec/`.

## Generation flow (v2)

1. Read `CLAUDE.md`, `docs/ARCHITECTURE.md`, this file.
2. Pick a target language (C or Rust).
3. The generator walks `parts/` recursively. For each part:
   - If **leaf**: resolve `inherits`; concatenate ancestor chain;
     spawn one sub-agent; sub-agent emits code at `emits.<target>.path`.
   - If **inner**: regenerate children first (recursing). Then emit
     composition glue (module file, header aggregation).
4. After full traversal, compile, run `tests/sqllogictest/`,
   `tests/cross-build/`, `tests/fuzz/`, `tests/tcl/`.
5. If a test fails: identify the owning part. Fix its master.md.
   Regenerate only that part. Re-run. **Do not hand-edit generated
   code.**

## Language-neutral discipline (unchanged from v1)

Every `master.md` and `schema.*` file must be implementable by both
a C generator and a Rust generator without either feeling forced.
The hardest rule: no Rust-only idioms (`Result`, lifetimes,
traits-as-contract-nouns), no C-only idioms (raw pointers, `void*`,
allocator mentions). Errors as named conditions. Control flow as
state machines or pseudo-code.

## Test authority

If a test contradicts a spec: the test wins. Prompts are fuzzy;
tests are executable.

## Verification ladder

Per generated build:

1. Builds cleanly, zero warnings.
2. All part-owned `tests/` pass.
3. `tests/cross-build/` passes (C and Rust produce identical results).
4. `tests/sqllogictest/` pass rate ≥ v1 floor (C 588/622, Rust 620/622).
5. `tests/fuzz/` corpus matches mainline SQLite on deterministic ops.
6. `tests/tcl/` passes.

Benchmarks (`bench/`) are a separate publication gate, not a
correctness gate.

## Status

v1 frozen at `main@9877a7e`. v2 under active authoring on this
branch (`v2-recursive-parts`). See `DASHBOARD.md` for the live
status of v2 sub-part authoring.
