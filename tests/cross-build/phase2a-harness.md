# Phase 2a test harness — language-neutral spec

The generated test harness (one per language target) consumes `phase2a.json` and runs every case against the generated `tokenizer` → `parser` → `executor` pipeline, with a freshly-constructed storage handle per case.

## Location

Generated into `src-{lang}/bin/phase2a-test` (or the target language's nearest equivalent entry point — a `main` in C, a `cargo run --bin phase2a-test` crate binary in Rust).

The harness is NOT human-authored. It is generated from this spec together with the rest of the target. If human-written test code appears in `src-*/` it is a spec-discipline violation.

## Invocation

The harness accepts exactly one positional argument: the filesystem path to `phase2a.json`.

```
<harness-binary> <path-to-phase2a.json>
```

If `argv[1]` (or the target language's equivalent) is missing or does not resolve to a readable file, the harness exits with code `2` and writes a one-line diagnostic to stderr. The harness MUST NOT probe fallback locations.

## Case execution

For each case in `phase2a.json.cases`, the harness:

1. Constructs a **fresh empty storage handle** via the storage part's `create_database()` entry.
2. Iterates over `case.program` in order, step by step:
   1. Calls the tokenizer on `step.sql`.
   2. Calls the parser on the resulting token sequence.
   3. Calls the executor on the resulting AST with the current storage handle.
3. At each step, compares the actual outcome to `step.expect` using the equality rules below.
4. If any step mismatches, the case is a failure — record the case name and the first-failing step index; do NOT run remaining steps of that case. Continue with the next case.
5. If all steps pass, the case is a success.

Each step's outcome is one of:

- A successful **Result** (if tokenize + parse + execute all succeeded).
- An **error** (if any stage failed). The error's `name` is the spec-level name (`LEX_*`, `PARSE_*`, or `STORAGE_*`) and its fields match the spec exactly.

## `step.expect` shapes

Each `step.expect` is exactly one of:

- `{"rows": [...]}` — expected successful Result with the given rows. The step is a **pass** iff the actual outcome is a successful Result whose rows match by value (equality rules below).
- `{"error": {"name": "...", "fields": {...}}}` — expected failure. The step is a **pass** iff the actual outcome is a failure whose `name` matches exactly and whose fields match field-by-field (integer fields numerically, string fields byte-exactly; for the `expected` field of `PARSE_UNEXPECTED_TOKEN`, array fields compared as sets — order-insensitive).

Any other shape (including `{"rows": null}` or `{"error": null}`) is a test-definition bug; the harness treats it as a failure with diagnostic "malformed expect".

## Equality rules (success cases)

- `null` in JSON ≡ SQL NULL
- JSON integer ≡ the generated engine's 64-bit signed integer, compared numerically
- JSON string ≡ the generated engine's UTF-8 text, compared byte-for-byte
- Row count must match exactly
- Row order matters; column count and column order within each row must match exactly

## Output format

Per case, the harness prints exactly one line:

```
PASS <case.name>
```

or

```
FAIL <case.name> at step <step_index>: <short reason>
```

where `<step_index>` is the 0-based index of the first failing step.

After all cases, the harness prints one summary line:

```
SUMMARY phase=2a target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

and exits with code `0` iff `failed == 0`, else exit code `1`.

## Non-goals

- Timing / benchmarking (lives in `bench/`, not here)
- JSON output, structured logs, colours — plain stdout text only
- Parallelism — cases run sequentially
- Any feature not described in this file
