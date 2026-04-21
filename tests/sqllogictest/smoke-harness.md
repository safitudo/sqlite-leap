# sqllogictest smoke harness — language-neutral spec

## Scope

Wraps the sqllogictest runner defined in `spec/sqllogictest-runner.spec.md`. The binary runs every `.test` file in a directory and reports a summary. Gate for the runner: zero failures on the smoke suite (`tests/sqllogictest/smoke/`) on BOTH C and Rust builds, with **byte-identical** SUMMARY line.

## Invocation

```
<harness-binary> <path-to-.test-file-or-directory>
```

- If the path is a file: run that single file.
- If the path is a directory: recursively find all `*.test` files, run each in file-path lexicographic order, fresh `:memory:` DB per file.

Generated into `src-{lang}/bin/sqllogictest` (C) and `src-rust/src/bin/sqllogictest.rs` (Rust), built via the target's normal build command.

## Output

Per record (one line):

```
<PASS|FAIL|SKIP> <file-relative-path>:<line-number> <record-kind> <optional-detail>
```

`<record-kind>` is exactly one of the single words `statement`, `query`, `parse`, `io` (NOT `statement ok` or `statement error` — the expected-outcome discriminator is NOT part of the kind field; include it in `<optional-detail>` on FAIL lines only, never on PASS). (2026-04-18 retroactive pin — byte-identical cross-build output requires a single canonical spelling.)

Per file (one line, AFTER all records in the file):

```
FILE <file-relative-path> passed=<int> failed=<int> skipped=<int> total=<int>
```

Note: the harness MUST omit `duration_ms` from its output. Reason: byte-identical output across C and Rust is the gate; timing would diverge. The full spec in `spec/sqllogictest-runner.spec.md` lists `duration_ms` as optional; the harness pins it OFF.

Summary line (at end):

```
SUMMARY sqllogictest target=<c|rust|wasm> passed=<int> failed=<int> skipped=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1. `skipped` does not affect exit.

## Scope cuts (v1 — smoke harness only)

The following runner-spec features are OPTIONAL for the smoke harness and MAY be omitted:

- `hash-threshold` directive (skip silently).
- Hash-based result comparison (all smoke queries are full-form).
- `--filter=<glob>` argv flag (not required; smoke runs all files).
- `label` on `query` records (skip silently).
- `mode <mode>` directive (skip silently).

Any record type listed in the runner spec § "Record types" MUST be implemented. `onlyif leap` / `skipif leap` MUST be honoured (our engine name is `leap`).

## Output ordering

Records within a file MUST be reported in file order. Files within a directory MUST be reported in lexicographic path order. This is what makes byte-identical cross-build verification feasible.

## Error handling (harness-level)

- Unparseable `.test` file: emit one FAIL line for the file (at `:0` with kind `parse`), skip the rest of the file, and count it as 1 failure.
- I/O error reading the .test file: same as above, kind `io`.

All engine errors encountered while executing a record are handled by the record's own semantics (`statement ok` expects no error; `statement error` expects an error; etc.) — the harness does NOT propagate them as harness-level failures.
