# Fuzz harness — scaffolding

Two-dimensional fuzz scope for sqlite-leap. This directory holds templates,
seeds, and placeholder drivers. **No fuzzer is run from here yet** — Phase 8
wires up the long-running campaigns.

## The two dimensions

1. **SQL parse/exec fuzzing** (`sql/`)
   Feed arbitrary bytes as SQL to the engine. Success = no crashes, no
   panics, no sanitizer hits. Engine-level errors (`PARSE_UNEXPECTED_TOKEN`,
   `VDBE_TYPE_MISMATCH`, etc.) are accepted outcomes — the engine correctly
   rejected malformed input. Covers both C and Rust builds.

2. **File-format compat fuzzing** (`file-format/`)
   Bidirectional roundtrip over real SQLite database files. Either
   (a) mainline produces the DB, LEAP-SQLite reads + queries it, or
   (b) LEAP-SQLite produces the DB, mainline reads + queries it. Success =
   byte-for-byte identical SELECT results on a deterministic workload and
   zero corruption reports.

The distinction matters: dimension 1 exercises the grammar+VDBE surface;
dimension 2 exercises the pager + B-tree + WAL + on-disk format.

## Relationship to the existing in-process harness

`tests/fuzz/corpus/` + `tests/fuzz/harness-spec.md` define the **MVP
in-process harness** (binaries `fuzz-parse` / `fuzz-exec`) that runs a
curated seed corpus directly through the public engine API. That layer is
for smoke-level regression — does the seed corpus still parse and execute?

The scaffolding here (`sql/`, `file-format/`) is for **mutation-based
campaigns** (cargo-fuzz, AFL++): same engine entry points, but driven by a
fuzzer that generates millions of mutated inputs from the seeds.

Both layers share the seeds eventually; for now the seed sets are small and
independent.

## Running each loop (once wired)

### SQL fuzzing — Rust / cargo-fuzz

```
tests/fuzz/sql/run-cargo-fuzz.sh
```

Prereqs:
- `cargo install cargo-fuzz` (nightly toolchain required by libFuzzer)
- Rust build present in `src-rust/` (generated, see `generators/rust/`)
- A `fuzz/` subdirectory inside `src-rust/` created via `cargo fuzz init`,
  with the target file copied from `cargo-fuzz-target.rs.template`

### SQL fuzzing — C / AFL++

```
tests/fuzz/sql/run-afl.sh
```

Prereqs:
- `afl-cc` / `afl-fuzz` on `PATH` (AFL++ 4.x+)
- C build present in `src-c/` with libsqliteleap static lib
- Harness compiled from `afl-harness.c.template`

### File-format fuzzing — roundtrip

```
tests/fuzz/file-format/fetch-seeds.sh   # once, to populate seeds/
tests/fuzz/file-format/roundtrip.sh seeds/empty.db
```

Prereqs:
- `bench/baselines/bin/sqlite-mainline` present (run
  `bench/baselines/fetch-baselines.sh` if missing)
- Both C and Rust builds of sqlite-leap available

## What counts as success

A fuzz finding is one of:
- Process crash (non-zero exit not already whitelisted as `ENGINE_ERROR`)
- Sanitizer hit (UBSan, ASan, MSan)
- Rust `panic!` or `abort`
- Cross-target divergence: C build and Rust build produce different
  verdicts for the same input
- File-format roundtrip divergence: mainline-produced DB opened via
  sqlite-leap yields different query results than the same DB opened via
  mainline (or vice versa)

Anything else — including `ENGINE_ERROR` with a named condition — is not
a finding. The engine is allowed to reject bad input, as long as it does
so cleanly.

## Publication bar

Before we publish bidirectional file-format compatibility claims, we need:
- Zero crashes over N hours of campaign time per build (N TBD in Phase 8)
- Zero roundtrip divergences over the full generated DB corpus
- Reproducible harness: same seeds + same fuzzer version → same findings
  set

Raw campaign logs + final corpora get archived alongside the benchmark
CSVs.
