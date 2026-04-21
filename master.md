# sqlite-leap — root orchestration prompt

You are the compiler for a LEAP project. Prompts, schemas, and tests are the source. Code is the output.

**Read `CLAUDE.md` at the repo root first.** It contains the full project framing, the dual-target extension to base LEAP, the benchmark commitments, and the strict "DO NOT CHEAT" rules (the mainline SQLite source and Turso source are off-limits for code generation).

## What this project is

A reimplementation of SQLite generated from a language-neutral specification. The specification produces three builds:

- `src-c/` — C implementation
- `src-rust/` — Rust implementation
- `src-wasm/` — WASM build, compiled from `src-rust/`

All three builds must pass the same tests. Cross-build equivalence (C and Rust producing identical results on the full test corpus) is a first-class correctness requirement.

## Generation flow

When asked to build the app:

1. Read `CLAUDE.md` — project framing + forbidden sources
2. Read this file
3. Read all specs in `spec/` — language-neutral grammars, state machines, opcode tables, page layouts, operational semantics
4. Read all schemas in `schema/` — JSON Schema definitions for AST nodes, opcode payloads, page layouts, planner IR, WAL frame headers
5. Read all parts in `parts/*/master.md` and `parts/*/schema.*`
6. Read all tests in `tests/`
7. Pick a target language (C or Rust). Invoke the matching generator:
   - `generators/c/generate.sh` for C → writes into `src-c/`
   - `generators/rust/generate.sh` for Rust → writes into `src-rust/`
   - `generators/wasm/generate.sh` for WASM → builds from `src-rust/` into `src-wasm/`
8. Run the verification steps below
9. If tests fail, first ask: **was the spec ambiguous or leaking a language-specific idiom?** Fix the spec. Regenerate. Do not hand-patch generated code.

## Part independence

Each part in `parts/` must be independently generatable. A part's prompt must never reference another part's implementation. Parts communicate only through:

- Schemas in `schema/` (shared contracts)
- Their own per-part `schema.*`
- Wiring code emitted by the generator into `src-*/`

## Language-neutral spec discipline (the hardest rule)

Every file in `spec/` and `schema/` must be implementable by both a C generator and a Rust generator without either language feeling forced:

- No Rust-only idioms (`Result`, lifetimes, traits-as-contract-nouns, `impl` blocks in prose)
- No C-only idioms (raw pointer arithmetic in prose, `void*`, allocator mentions in the contract surface)
- Data shapes as abstract records (JSON Schema in `schema/`)
- Control flow as state machines or pseudo-code
- Errors as named conditions; each generator maps the name to its language's idiomatic error handling

If a spec change can't be expressed neutrally, the spec is wrong — re-level it before writing either generator.

## Test authority

If a test contradicts a prompt or spec, **the test wins**. Prompts are fuzzy; tests are executable and precise.

## Verification

Per generated build, the verification ladder is:

1. Build cleanly with zero warnings (`src-c/` via the C toolchain, `src-rust/` via `cargo`, `src-wasm/` via `wasm32-unknown-unknown` target)
2. `tests/sqllogictest/` passes on that build
3. `tests/tcl/` passes on that build
4. `tests/fuzz/` corpus produces byte-identical results to mainline SQLite on deterministic ops
5. `tests/cross-build/` — same query against the C build and the Rust build produces identical results

The benchmark harness in `bench/` is a separate ladder (six lanes, see `CLAUDE.md`). Benchmarks are not a gate for "tests pass" but are a gate for "publication."

## Generator invocation

Generators are thin wrappers over an AI coding session. For each target:

- Input: `CLAUDE.md`, `master.md`, `spec/**`, `schema/**`, `parts/**`, `tests/**`
- Output: code into the target's `src-*/` directory
- Constraint: self-contained output — `src-*/` must not import from outside itself. Copy type definitions inline as needed.

## Running the project

This is a library, not an application. After generation:

- The C build produces a single-file amalgamation + `.dylib` / `.so` / `.a`
- The Rust build produces a `cargo` crate + dylib
- The WASM build produces an ES module suitable for browsers and Node

Usage in downstream projects is via FFI bindings (Node, Python) that will live in follow-up repos, not here.

## Status

See `CLAUDE.md` → "Current status" for the active phase. This repo is iterated phase by phase; each phase has an explicit gate before the next begins.
