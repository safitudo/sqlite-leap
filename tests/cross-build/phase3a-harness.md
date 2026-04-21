# Phase 3a test harness — language-neutral spec

The Phase 3a harness drives the same tokenize → parse → compile → vdbe.run pipeline as Phase 2c-3, but adds a `backend` dimension: each case runs against either the in-memory `storage.create_database()` backend (existing, unchanged) or the new on-disk `storage.open_database(path)` backend.

## Location

Generated into `src-{lang}/bin/phase3a-test` (or the target language's nearest equivalent).

## Invocation

Accepts exactly one positional argument: the path to `phase3a.json`.

```
<harness-binary> <path-to-phase3a.json>
```

If `argv[1]` is missing or unreadable → exit 2 with a one-line diagnostic to stderr.

## Temp-file policy (disk cases)

Each disk case owns a unique temporary file for the duration of the case. The harness:

1. Generates a unique path `T` per case. Recommended shape: `{system-tempdir}/phase3a-{pid}-{case_index}.db`. The exact naming is target-defined; what matters is uniqueness and writability.
2. If `preload_hex` is present (see § "Preload"): writes the specified bytes to `T` before calling `open_database(T)`.
3. Calls `storage.open_database(T)`.
4. On case exit (success, failure, or mid-case FAIL), the harness MUST close the handle (via `close_database` if still open) AND delete `T`. No temp file may leak across cases.

## Preload (`preload_hex`, disk-only)

`preload_hex` is a string of hexadecimal byte pairs with no separators, no `0x` prefix, case-insensitive. If present:

1. The harness decodes the hex to bytes.
2. The bytes are written at offset 0 of `T`.
3. If fewer than `4096` bytes are provided, the harness zero-pads the file on disk to exactly `4096` bytes (so the file looks like a full page-1-sized file with corrupted or partial content).
4. If exactly or more than `4096` bytes are provided, the file content is the preload bytes verbatim with no padding.

The purpose is to let tests probe the open-path validator with known-bad or known-unsupported headers.

## Expected open error (`open_error`, disk-only)

If a disk case declares `open_error`, the harness expects `open_database(T)` to fail with that error. Comparison is by `name` equality plus a field subset check: every field present in `expect.fields` must appear with the expected value in the actual error; fields in the actual error that are not present in `expect.fields` are ignored.

When `open_error` is declared, the harness does NOT run `program` (typically it's an empty list).

## Program step kinds

Each entry in `case.program` is either:

- **SQL step**: `{"sql": "...", "expect": {...}}` — tokenize/parse/compile/run the SQL, compare outcome to `expect`.
- **Reopen marker**: `{"reopen": true}` — valid only for `backend == "disk"`. The harness:
  1. Calls `close_database(handle)` on the current handle. A failure here is reported as `FAIL <case> at step <idx>: close_database errored: <detail>`.
  2. Calls `open_database(T)` with the SAME path. A failure here fails the case.
  3. Replaces the current handle with the new one.

Using a reopen marker in a `memory` case is a harness error: print `FAIL <case> at step <idx>: reopen marker not valid on memory backend` and skip rest of the case.

## Pipeline per SQL step

Unchanged from `phase2c3-harness.md`:

1. Tokenize `step.sql` → tokens OR fail with `LEX_*`.
2. Parse tokens → AST OR fail with `PARSE_UNEXPECTED_TOKEN`.
3. Call `compiler.compile(ast, handle)` → Program OR fail with `STORAGE_*` / `EVAL_COLUMN_WITHOUT_TABLE`.
4. Verify Program well-formedness (invariants 1–13 — unchanged from 2c-3; Phase 3a adds no new opcodes).
5. Call `vdbe.run(program, handle)` → Result OR fail with `STORAGE_*` / `EVAL_DIVISION_BY_ZERO` / `EVAL_TYPE_ERROR`.
6. Compare earliest-stage outcome to `step.expect`.

New in 3a: stage 5 may raise `STORAGE_PAGE_FULL`, `STORAGE_UNSUPPORTED_TYPE`, `STORAGE_FILE_IO`, `STORAGE_CORRUPT_PAGE` during an INSERT/UPDATE/DELETE/SELECT when the disk backend is in use. These propagate identically to other `STORAGE_*` errors.

## Well-formedness invariants

Same 13 invariants from `phase2c3-harness.md` § "Well-formedness invariants". Phase 3a introduces NO new opcodes and NO new invariants.

## Equality rules

Unchanged from `phase2c3-harness.md`:

- For error comparisons (`STORAGE_*`, `EVAL_TYPE_ERROR`, `STORAGE_CORRUPT_HEADER`, `STORAGE_UNSUPPORTED_FEATURE`, `STORAGE_PAGE_FULL`, etc.): compare every field present in the `expect` block. Fields absent from `expect` are not compared.
- `expected` arrays for `PARSE_UNEXPECTED_TOKEN` are compared as sets.
- For success cases with `rows: []`, comparison is exact (no columns, no rows).
- For `rows` arrays with actual values, row order is significant (insertion order).

## Default backend

If `case.backend` is absent or explicitly `"memory"`: construct `storage.create_database()`.
If `case.backend == "disk"`: construct `storage.open_database(T)` per the policy above.

## Output

Per case: `PASS <case.name>` or `FAIL <case.name> at step <idx>: <reason>`. Final line:

```
SUMMARY phase=3a target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.

## Non-goals

- Concurrency, fsync verification, crash-recovery (Phase 3d).
- Benchmarking (lives in `bench/`).
- JSON output, colours — plain stdout only.
- Register-allocation snapshot tests (banned).
- Page-cache or journal inspection (Phase 3b+/3d).
