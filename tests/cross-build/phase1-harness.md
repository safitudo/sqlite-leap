# Phase 1 test harness — language-neutral spec

The generated test harness (one per language target) consumes `phase1.json` and runs every case against the generated tokenizer → parser → executor pipeline.

## Location

Generated into `src-{lang}/bin/phase1-test` (or the target language's nearest equivalent entry point — a `main` in C, a `cargo run --bin phase1-test` crate binary in Rust).

The harness is NOT human-authored. It is generated from this spec together with the rest of the target. If human-written test code appears in `src-*/` it is a spec-discipline violation.

## Invocation

The harness accepts exactly one positional argument: the filesystem path to `phase1.json`. It is invoked as:

```
<harness-binary> <path-to-phase1.json>
```

If `argv[1]` (or the target language's equivalent) is missing or does not resolve to a readable file, the harness exits with code `2` and writes a one-line diagnostic to stderr. The harness MUST NOT probe multiple fallback locations — taking the path as an explicit argument keeps it cleanly usable from any working directory (CI, the benchmark harness, or another generator).

## Required behaviour

For every case in `phase1.json.success_cases`, the harness MUST:

1. Call the tokenizer on the case's `sql` field.
2. Call the parser on the resulting token sequence. Every Phase 1 SQL form parses to a `SelectLiteral` AST node.
3. Call the executor on the resulting AST with a freshly-constructed storage handle (Phase 1 SELECT-literal cases do not touch storage, but the handle must still be provided for API uniformity with Phase 2a+).
4. Compare the executor's Result to the case's `expect` field using the equality rules below.
5. Print exactly one line: `PASS <case.name>` or `FAIL <case.name>: <reason>`.

For every case in `phase1.json.error_cases`, the harness MUST:

1. Call the tokenizer on the case's `sql` field.
2. If the tokenizer succeeds, call the parser on the resulting tokens; if the parser succeeds, call the executor with a freshly-constructed storage handle.
3. Assert that the pipeline terminates unsuccessfully with the expected error condition whose `name` matches and whose fields match exactly.
4. Print exactly one line: `PASS <case.name>` or `FAIL <case.name>: <reason>`.

After all cases, print exactly one summary line in the format:

```
SUMMARY phase=1 target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

and exit with code `0` iff `failed == 0`, else exit code `1`.

## Equality rules (success cases)

- `null` in JSON ≡ SQL NULL
- JSON integer ≡ the generated engine's 64-bit signed integer, compared numerically
- JSON string ≡ the generated engine's UTF-8 text, compared byte-for-byte
- Row order matters; column order matters; row count must match exactly

## Equality rules (error cases)

The harness must surface enough of the error condition to compare:

- The error's `name` string, compared exactly
- Every declared field of the error, compared by value:
  - integer fields compared numerically
  - string fields compared exactly
  - array fields compared as sets (order-insensitive) for the `expected` field of `PARSE_UNEXPECTED_TOKEN`

If the engine produces a different error name than expected, the harness reports `FAIL <case.name>: expected <expected.name>, got <actual.name>`.

## Non-goals for the harness

- Timing / benchmarking (that lives in `bench/`, not here)
- JSON output, structured logs, colours — plain stdout text only
- Parallelism — cases run sequentially
- Any feature not described in this file
