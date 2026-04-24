---
name: harness/sqllogictest-runner
kind: leaf
inherits:
  - /spec/sqllogictest-runner.spec.md
  - /parts/executor/master.md
emits:
  c: { path: src-c/harness/sqllogictest_runner.c, headers: [src-c/harness/sqllogictest_runner.h] }
  rust: { path: src-rust/src/harness/sqllogictest_runner.rs }
---

# Part: harness/sqllogictest-runner

The sqllogictest driver. Reads `*.test` files, parses them into
records, drives each record through the engine, compares outputs
against expectations.

## Record types

- `statement ok` — run; no error expected.
- `statement error [pattern]` — run; error expected; optional
  message pattern.
- `query TYPES labels` — run; compare sorted output rows to
  expected; `TYPES` declares per-column sort affinity (`T` text, `I`
  integer, `R` real).
- `query ... ---` hash-threshold mode — when row count exceeds
  threshold, compare an MD5 hash instead of literal rows.
- `hash-threshold N` — set threshold.
- `skipif dialect` / `onlyif dialect` — skip/include per dialect.

## Backend selection (v1 additions)

- `LEAP_DB_PATH=<path>` env var — runner opens the engine on a
  disk-backed path instead of `:memory:`. Phase 4b required this
  knob.
- `LEAP_WAL_APPEND=1` env var — activates Phase 4b append-on-write
  WAL mode. Only meaningful with `LEAP_DB_PATH` set.

## Per-query timeout

Each `query` or `statement` has a configurable timeout (default
30s). On timeout: emit `TIMEOUT` line in the canonical FAIL-line
format. (Phase 80)

## FAIL-line format (Phase 55 — pin)

Both C and Rust runners MUST emit the identical single-line format
on failure:

```
FAIL: <file>:<line>: <verdict> — <detail>
```

`verdict` is one of: `HASH_MISMATCH`, `ROW_COUNT_MISMATCH`,
`VALUE_MISMATCH`, `UNEXPECTED_ERROR`, `EXPECTED_ERROR_NOT_RAISED`,
`TIMEOUT`. `detail` is a short human-readable string.

## Phase pins

- **Phase 50** — port upstream sqllogictest corpus.
- **Phase 51** — hash-threshold comparison.
- **Phase 55** — FAIL-line format pin.
- **Phase 80** — per-query timeout with timeout-as-FAIL.
- **Phase 4b** — LEAP_DB_PATH + LEAP_WAL_APPEND env knobs.

## Regeneration envelope

- Target leaf size: 600–1000 lines per target.
- Spec < 200 lines.
