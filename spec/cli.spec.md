# `sqlite-leap-cli` — language-neutral spec

A thin command-line wrapper around the sqlite-leap engine. Purpose: (a) act as a SUT for formal round-trip tests (Phase 3e) against mainline `sqlite3`, (b) support the benchmark harness (Phase 8), (c) provide a hand-usable shell for quick demos.

Each language target emits its own binary. The native behaviour is identical across C and Rust (output bytes match on successful runs; error messages may differ by letter).

## Invocation

```
sqlite-leap-cli <db-path> [<sql>]
```

- `<db-path>` is required. If the file does not exist, it is created (empty SQLite-compatible DB per `spec/file-format.spec.md`). If the file exists, it is opened and validated.
- `<sql>` is optional. If present, its content is the SQL to execute. If absent, SQL is read from stdin until EOF.

The SQL input MAY contain multiple `;`-separated statements. The binary MUST tokenize the full input exactly once, slice the resulting token stream at SEMICOLON tokens (one statement = the run of tokens between two SEMICOLONs or between start-of-stream and the first SEMICOLON, with an appended synthesised EOF sentinel), then parse + compile + run each slice against the same database handle, in source order. Re-tokenizing source substrings is disallowed — for a buffer of N statements it silently doubles tokenizer cost and skews benchmarks. (Correctness motivation: doing it via token-stream slicing also avoids having to re-scan string literals and keeps byte offsets coherent.)

## Output

The binary writes one JSON object per statement to stdout, followed by a newline. Output format matches the cross-build harness's step-output shape:

```
{"rows": [[...], ...]}\n
```

on success, or:

```
{"error": {"name": "...", "fields": {...}}}\n
```

on failure.

Order of emission follows statement order. On the first failure, the binary emits that error line, closes the database (flushing any pending writes as specified below), and exits non-zero. Later statements are NOT attempted.

## Exit codes

- `0` — all statements ran successfully.
- `1` — a statement failed (one error line was emitted). Database was still flushed.
- `2` — invocation or I/O error that prevented opening / closing the database. Error details go to stderr; no JSON on stdout.

## Database lifecycle

- `open_database(db-path)` at start. Errors exit 2 with the `STORAGE_*` name on stderr.
- `close_database(handle)` at end (success OR statement-failure path). Errors exit 2 with the `STORAGE_*` name on stderr. **The CLI never deletes `<db-path>`.**

## Non-goals

- Interactive mode (`sqlite3`'s REPL with `.` commands) — not in Phase 3e scope. The CLI is strictly batch-per-invocation.
- Dot commands (`.schema`, `.dump`, etc.) — not supported. SQL only.
- Prompts / readline — not supported.
- Custom column separators, headers, etc. — output is always JSON.
- Multi-line statements split across stdin reads — the CLI reads stdin until EOF, then tokenizes the whole buffer as a single SQL string.

## Test authority

`tests/cross-build/roundtrip_formal.py` is the Phase 3e executable specification that exercises this CLI against mainline `sqlite3` in both directions. Both C and Rust builds of `sqlite-leap-cli` MUST pass.
