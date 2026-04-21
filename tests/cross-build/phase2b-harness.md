# Phase 2b test harness — language-neutral spec

The Phase 2b harness exercises the `compiler` and `vdbe` parts DIRECTLY (not via the executor), proving their public entry points exist and have well-formed contracts, and verifies each compiled program against the well-formedness invariants of `spec/vdbe-opcodes.spec.md` § "Well-formedness" before running.

## Location

Generated into `src-{lang}/bin/phase2b-test` (or the target language's nearest equivalent entry point — a `main` in C, a `cargo run --bin phase2b-test` crate binary in Rust).

The harness is NOT human-authored. It is generated from this spec together with the rest of the target.

## Invocation

```
<harness-binary> <path-to-phase2b.json>
```

Argv[1] required. If absent, exit 2 with a one-line diagnostic to stderr. No fallback probing.

## Pipeline per case

For each case in `phase2b.json.cases`, the harness:

1. Constructs a **fresh empty storage handle** via `storage.create_database()`.
2. Iterates over `case.program` in source order. For each `step`:
   1. Tokenize `step.sql` → tokens, or fail with LEX_*.
   2. Parse tokens → AST, or fail with PARSE_UNEXPECTED_TOKEN.
   3. Call `compiler.compile(ast, storage_handle)` → Program or fail with STORAGE_*.
   4. If compilation succeeded, **verify the Program's well-formedness** per `spec/vdbe-opcodes.spec.md` § "Well-formedness". A violation is reported as `FAIL <case.name> at step <idx>: malformed-program: <invariant>`.
   5. If compilation succeeded AND the program is well-formed, call `vdbe.run(program, storage_handle)` → Result or STORAGE_*.
   6. The step's outcome is the earliest-stage failure OR the final Result.
3. Compare each step's outcome to `step.expect`.
4. If any step mismatches, record `FAIL <case.name> at step <idx>: <reason>` and stop executing further steps of that case; proceed to next case.
5. If all steps pass, print `PASS <case.name>`.

## Well-formedness invariants the harness checks

Per compiled `Program`:

1. `opcodes` is non-empty.
2. `num_registers ≥ 0`, `num_cursors ≥ 0`.
3. For every `LoadConst` opcode: `dest < num_registers`.
4. For every `ResultRow` opcode: `start + count ≤ num_registers` AND `count ≥ 1`.
5. For every `Column` opcode: `dest < num_registers`.
6. For every `InsertRow` opcode: `start + count ≤ num_registers` AND `count ≥ 1`.
7. For every opcode with a `cursor` field: `cursor < num_cursors`.
8. For every `jump_if_empty` / `jump_if_more` operand: target is in `[0, opcodes.length)`.
9. The last opcode's `op` field is `"Halt"`.

On violation, the harness reports `FAIL <case.name> at step <idx>: malformed-program: invariant <1..9>`.

## Equality rules

Identical to `tests/cross-build/phase2a-harness.md` § "Equality rules".

## Output format

Per case: one line, `PASS <case.name>` or `FAIL <case.name> at step <idx>: <reason>`.

After all cases, one summary line:

```
SUMMARY phase=2b target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit code 0 iff `failed == 0`, else 1.

## Non-goals

- Benchmarking (lives in `bench/`, not here)
- JSON output, structured logs, colours — plain stdout text only
- Parallelism — cases run sequentially
- Register-allocation snapshot tests (banned by LEAP — locks implementation)
- Any feature not described in this file
