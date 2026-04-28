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

## Input-line normalization (Pin 80)

Upstream sqllogictest corpus files use **CRLF** line endings. Every
target's `.test` parser MUST strip a trailing `\r` from each line
before comparing it against rendered output. The Python reference
driver achieves this via `f.read().splitlines()` (stdlib-default
CRLF-aware); Rust achieves this via `body.lines()` (same). Targets
that hand-roll a line splitter (manual `strchr('\n')` walks in C,
manual byte loops in Zig, manual `strings.Split` in Go) MUST add an
explicit `TrimRight(line, "\r")` per parsed line.

Failure mode if missed: every expected literal cell carries a
trailing `\r`, comparison fails byte-for-byte against rendered
output (which never has `\r`), but the FAIL diagnostic prints both
strings via `%s` where `\r` is invisible (cursor return) — making
`got` and `expected` appear byte-identical in logs. Cross-target
observation 2026-04-25: this single bug accounted for ~404k C +
~105k Zig FAIL records (~24% of all C corpus records and ~25% of
all Zig corpus records).

## Typed-cell rendering (Pin 81)

Per-typestring cell rendering rules. The runner MUST apply these
exactly when comparing cells against expected output. `null`
rendering is shared across all typestrings: `NULL`. Empty text in
typestring 'T' renders as `(empty)`.

| typechar | rule (non-NULL) |
| --- | --- |
| `I` (integer) | integer → decimal; real → `int(real)`; text → `int(text)` or `0` on parse-fail; blob → `0`. |
| `R` (real) | integer → `%.3f`; real → `%.3f`; text → `%.3f` of `float(text)` or `0.000` on parse-fail; null → `0.000`. |
| `T` (text) | integer → decimal; real → `%.3f`; text → printable-ASCII passthrough, non-printable → `@`; blob → hex. |

The `R` rule is **`%.3f`, not `%g`**. Using `%g` introduces
precision-divergence FAILs against expected literal cells (e.g.
expected `1.234`, `%g` produces `1.23`). The canonical fallback (a
hash-or-literal compare without typestring affinity) MUST also use
`%!.15g` per the file-format renderer pin, not `%g`.

This pin is target-cross-cutting: every target's slt_runner
implementation must follow these rules byte-identically. The Python
driver in `tests/sqllogictest/5target_harness/driver_python.py`
serves as the reference implementation.

## FAIL-line format (Phase 55 — pin)

Both C and Rust runners MUST emit the identical single-line format
on failure:

```
FAIL: <file>:<line>: <verdict> — <detail>
```

`verdict` is one of: `HASH_MISMATCH`, `ROW_COUNT_MISMATCH`,
`VALUE_MISMATCH`, `UNEXPECTED_ERROR`, `EXPECTED_ERROR_NOT_RAISED`,
`TIMEOUT`. `detail` is a short human-readable string.

## SELECT dispatch — multi-schema entry point (Pin 84)

The runner's `query` path MUST compile SELECT statements through the
**multi-schema** compiler entry point, never the single-schema one.
Concretely:

- For every `query` record, the runner builds a `primary` schema
  (heuristic substring match against `from <name>` in the lowered
  SQL) AND an `extras` list containing every other catalog table's
  schema, then dispatches via the compiler's "with database / with
  schemas" entry (`compile_select_with_db` in Rust, equivalent in
  every target — refer to the relevant target's `parts/compiler/
  parts/select-compile/master.md` exports).
- It is NEVER acceptable to gate the multi-schema dispatch on
  "AST contains a subquery" (or any other AST predicate). JOINs
  require `extras` to resolve every secondary source — the single-
  schema `compile_select` path's `.joined` arm rejects every
  secondary name with `"unknown table in JOIN: <name>"` because
  it has only one schema to match against.
- The reference implementation is `src-rust/examples/slt_runner.rs`
  (always passes `extras = all-other-tables`).

Failure mode if missed: every multi-table FROM clause (CROSS JOIN,
explicit JOIN, comma-list) DEFERs with `compile: unknown table in
JOIN: <name>`. Cross-target observation 2026-04-25: a Zig runner
that gated extras on `stmt_has_subquery` shed ~7000 records to
this single bucket; lifting the gate restored corpus parity on
the JOIN path with no regression on JOIN-free queries (the multi-
schema entry point behaves identically to the single-schema entry
when `extras` is empty and the FROM is a single Named source).

## Catalog capacity (Pin 83)

The runner's per-script catalog holds the schema for every table
installed by `statement ok CREATE TABLE`. Some upstream corpus files
install hundreds of tables in sequence (`t1` through `t300+`). The
catalog therefore MUST grow without a fixed compile-time cap.
Targets with dynamically-sized collections (Rust `Vec`, Go slice,
Python list, Zig `ArrayList`) get this for free; targets that use
a fixed-size array MUST resize on demand or pre-size to at least
**4096** entries. Hitting the cap is a runner bug, not a corpus
bug, and MUST NOT surface as `install: too many tables`.

## Phase pins

- **Phase 50** — port upstream sqllogictest corpus.
- **Phase 51** — hash-threshold comparison.
- **Phase 55** — FAIL-line format pin.
- **Phase 80** — per-query timeout with timeout-as-FAIL.
- **Phase 4b** — LEAP_DB_PATH + LEAP_WAL_APPEND env knobs.
- **Pin 83** — catalog capacity must scale to ≥4096 tables.
- **Pin 84** — query-path SELECT compile dispatches through the
  multi-schema entry point (always, never gated on AST shape).

## Regeneration envelope

- Target leaf size: 600–1000 lines per target.
- Spec < 200 lines.
