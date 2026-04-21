# Phase 2c-1 test harness — language-neutral spec

The Phase 2c-1 harness drives the tokenize → parse → compile → vdbe.run pipeline (same structure as phase2b-harness, but with the expanded Phase 2c-1 ISA and error surface). Like the Phase 2b harness, it calls `compiler.compile` and `vdbe.run` directly (not through the executor), and verifies program well-formedness between compile and run.

## Location

Generated into `src-{lang}/bin/phase2c1-test` (or the target language's nearest equivalent).

## Invocation

Accepts exactly one positional argument: the path to `phase2c1.json`.

```
<harness-binary> <path-to-phase2c1.json>
```

If `argv[1]` is missing or unreadable → exit 2 with a one-line diagnostic to stderr.

## Pipeline per case

For each case in `phase2c1.json.cases`, the harness:

1. Constructs a **fresh empty storage handle** via `storage.create_database()`.
2. Iterates `case.program` in source order. For each `step`:
   1. Tokenize `step.sql` → tokens OR fail with `LEX_*`.
   2. Parse tokens → AST OR fail with `PARSE_UNEXPECTED_TOKEN`.
   3. Call `compiler.compile(ast, storage_handle)` → Program OR fail with `STORAGE_*` / `EVAL_COLUMN_WITHOUT_TABLE`.
   4. Verify the Program's well-formedness per `spec/vdbe-opcodes.spec.md` (invariants 1–11; see below). A violation is reported as `FAIL <case.name> at step <idx>: malformed-program: invariant <n>`.
   5. Call `vdbe.run(program, storage_handle)` → Result OR fail with `STORAGE_*` / `EVAL_DIVISION_BY_ZERO` / `EVAL_TYPE_ERROR`.
   6. Compare the earliest-stage outcome (error OR final Result) to `step.expect`.
3. On first mismatch, record FAIL and stop that case's steps; continue with the next case.
4. If all steps pass: print `PASS <case.name>`.

## Well-formedness invariants (Phase 2c-1 set)

The harness checks invariants 1–11 from `spec/vdbe-opcodes.spec.md`:

1. `opcodes` non-empty.
2. `num_registers ≥ 0`, `num_cursors ≥ 0`.
3. `LoadConst.dest < num_registers`.
4. `ResultRow.start + count ≤ num_registers` and `count ≥ 1`.
5. `Column.dest < num_registers`.
6. `InsertRow.start + count ≤ num_registers` and `count ≥ 1`.
7. Every `cursor` operand satisfies `cursor < num_cursors`.
8. Every `jump_if_empty` / `jump_if_more` is in `[0, |opcodes|)`.
9. Last opcode is `Halt`.
10. For every `Add` / `Subtract` / `Multiply` / `Divide` / `Eq` / `Ne` / `Lt` / `Le` / `Gt` / `Ge`: `dest`, `lhs`, `rhs` all `< num_registers`.
11. For every `Negate`: `dest`, `src` both `< num_registers`.

## Equality rules

Identical to `phase2a-harness.md` § "Equality rules", plus:

- For `EVAL_TYPE_ERROR` fields: the harness compares every field present in the `expect` block. Absent fields are not compared; any extra field beyond `op`/`left_type`/`right_type`/`operand_type` is a test-definition bug.
- `expected` arrays for `PARSE_UNEXPECTED_TOKEN` are compared as sets (order-insensitive), consistent with earlier phases.

## Output

Per case: `PASS <case.name>` or `FAIL <case.name> at step <idx>: <reason>`. Final line:

```
SUMMARY phase=2c1 target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.

## Non-goals

- Benchmarking (lives in `bench/`)
- JSON output, colours — plain stdout only
- Parallelism — cases run sequentially
- Register-allocation snapshot tests (banned)
- Any feature beyond what this file describes
