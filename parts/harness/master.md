---
name: harness
kind: inner
inherits:
  - /spec/memory-discipline.spec.md
  - /spec/sqllogictest-runner.spec.md
  - /spec/cli.spec.md
  - /parts/executor/master.md
emits:
  c:
    path: src-c/harness/mod.h
  rust:
    path: src-rust/src/harness/mod.rs
---

# Part: harness

Runners and CLI wrappers that call into the engine. Harness code is
not "the engine" — it's how the engine is driven from tests and
shells. Two sub-parts.

## Sub-part map

- `parts/sqllogictest-runner/` — executes sqllogictest files.
  Implements hash-threshold mode, per-query timeout, FAIL-line
  format, backend selection (`LEAP_DB_PATH`, `LEAP_WAL_APPEND` env
  vars). Absorbs v1 `/spec/sqllogictest-runner.spec.md` plus its
  Phase 4b extensions.
- `parts/cli/` — the `sqlite-leap` binary. Interactive REPL,
  `-batch` mode, startup options. Absorbs v1 `/spec/cli.spec.md`.

## Why harness is separate from executor

The executor (`parts/executor/`) is the engine's public entry.
Harness is the test-and-shell layer above it. Harness depends on
executor, not the other way around. Putting harness inside the
engine tree would conflate "how we drive the engine for validation"
with "what the engine is."

## Composition

Default inner-part composition: each sub-part emits its own module;
parent emits module glue + (optionally) a shared helper for
condition-kind → exit-code translation.
