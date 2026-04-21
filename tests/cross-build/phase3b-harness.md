# Phase 3b test harness — language-neutral spec

The Phase 3b harness is an extension of the Phase 3a harness. Case structure (backend, preload_hex, open_error, reopen markers) is unchanged. Three new step kinds are added to keep multi-page test fixtures compact.

## Location

Generated into `src-{lang}/bin/phase3b-test` (or the target language's nearest equivalent).

## Invocation

```
<harness-binary> <path-to-phase3b.json>
```

Same `argv` policy as Phase 3a.

## New step kinds (Phase 3b)

### `bulk_insert_int_range`

```json
{"bulk_insert_int_range": {"table": "t", "start": 1, "count": 1000}, "expect": {"rows": []}}
```

Semantics: for each `i` in the half-open range `[start, start + count)`, the harness executes the SQL statement `INSERT INTO <table> VALUES (<i>);` through the full tokenize → parse → compile → vdbe.run pipeline against the current backend handle.

- If any individual INSERT fails, the step fails with the first error encountered; the step's reported index is this single `bulk_insert_int_range` step (not the per-row offset).
- On success, the outcome is a Result with `rows: []` — identical to a single INSERT's success shape.
- `count` MUST be `>= 1`. `start + count − 1` MUST fit in signed 64-bit (same constraint as a single INSERT's integer literal).

### `rows_int_range` expectation

```json
{"sql": "SELECT x FROM t;", "expect": {"rows_int_range": {"start": 1, "count": 1000}}}
```

Semantics: the harness compares actual rows against the synthetic list `[[start], [start+1], ..., [start + count − 1]]`. Each actual row MUST have exactly one column of integer type. Row order is significant (insertion order). This is equivalent to writing out the full `rows` array; it exists solely to keep the fixture file human-readable.

### `row_count` expectation

```json
{"sql": "SELECT x FROM t;", "expect": {"row_count": 997}}
```

Semantics: the harness runs the SELECT and asserts the ACTUAL row count equals `row_count`. Row contents and column count are NOT checked. Used for large scans where the full contents are deterministic but not worth enumerating.

The three new kinds are mutually exclusive within a step's `expect` block — a step MUST have at most one of `rows`, `rows_int_range`, `row_count`, or `error`. Missing or multiple are harness errors.

## Pipeline per step

Unchanged from Phase 3a. The tokenize → parse → compile → vdbe.run stages apply to each synthesised SQL statement inside `bulk_insert_int_range`.

## Well-formedness invariants

Same 13 invariants from Phase 2c-3. Phase 3b introduces NO new opcodes.

## Equality rules

- `rows` / `rows_int_range`: exact match including order.
- `row_count`: integer equality.
- Error shape comparison: same field-subset rule as Phase 3a (compare only fields declared in `expect.fields`).

## Default backend

If `case.backend` is absent or `"memory"`: construct `storage.create_database()`.
If `case.backend == "disk"`: use the Phase 3a disk-temp-file policy (generate unique temp path, apply `preload_hex` if present, `open_database(path)`).

## Output

Per case: `PASS <case.name>` or `FAIL <case.name> at step <idx>: <reason>`. Final line:

```
SUMMARY phase=3b target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.

## Non-goals

- Benchmarking (Phase 8).
- Concurrency, journal / WAL inspection (Phase 3d / 4).
- Custom tree-shape assertions (e.g. "root must be interior after N inserts") — Phase 3b asserts only end-to-end observable behaviour.
- Parallelism — cases run sequentially.
