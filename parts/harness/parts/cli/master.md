---
name: harness/cli
kind: leaf
inherits:
  - /spec/cli.spec.md
  - /parts/executor/master.md
emits:
  c: { path: src-c/harness/cli.c, headers: [src-c/harness/cli.h] }
  rust: { path: src-rust/src/harness/cli.rs }
---

# Part: harness/cli

The `sqlite-leap` CLI tool. Interactive REPL + batch mode. Minimal
shell surface; not aiming for feature parity with mainline
`sqlite3` CLI beyond what benchmarks and tests require.

## Modes

- **REPL** — `sqlite-leap [path]` opens an interactive prompt.
  Multi-line SQL accepted until `;`. `.help`, `.tables`, `.schema`,
  `.mode`, `.quit` meta-commands.
- **Batch** — `sqlite-leap path -batch < file.sql` reads stdin as a
  SQL script, executes, emits tab-delimited results.
- **Single-query** — `sqlite-leap path "SELECT 1"` executes one
  query, exits.

## Exit codes

- `0` — success.
- `1` — SQL error (compile or runtime).
- `2` — invalid CLI arguments.
- `3` — I/O error opening DB.

## Phase pins

- No specific phase pins; CLI is driven by cli.spec.md.

## Regeneration envelope

- Target leaf size: 400–700 lines per target.
- Spec < 100 lines.
