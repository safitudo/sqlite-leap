# Fuzz harness binaries — MVP scope (parse-only + exec-only)

First-stage implementation of the four harnesses described in `spec/fuzz-corpus.spec.md`. Stage 1 delivers the two harnesses that need no external oracle: `parse-only` and `exec-only`. The two roundtrip harnesses (`roundtrip-db`, `roundtrip-sql`) need a Python driver + mainline `sqlite3` oracle and are deferred to a follow-up session.

## Binary names

- C: `src-c/bin/fuzz-parse`, `src-c/bin/fuzz-exec`
- Rust: `src-rust/src/bin/fuzz_parse.rs`, `src-rust/src/bin/fuzz_exec.rs`

## Invocation

Both harnesses take a path to a single input file OR a directory:

```
<harness> <path>
```

- If `<path>` is a file: consume it as one SQL input; emit one verdict line; exit.
- If `<path>` is a directory: iterate every regular file recursively in lexicographic order; emit one verdict line per file; summary line at end; exit.

## Per-input verdict (one line)

```
<OK|ENGINE_ERROR|CRASH> <file-relative-path> [<error-kind>]
```

- `OK`: the input was consumed without crashing AND without raising any engine error. Parsed/executed cleanly.
- `ENGINE_ERROR`: the engine raised a named error condition (e.g. `PARSE_UNEXPECTED_TOKEN`, `VDBE_TYPE_MISMATCH`). `<error-kind>` is the condition name. Counted as "accepted" — NOT a fuzz finding, the engine correctly rejected malformed input.
- `CRASH`: the harness propagated an unexpected failure (panic, abort, sanitizer hit). In the harness binary itself this is signalled by a NON-ZERO EXIT STATUS of the per-input sub-invocation; the orchestrator (a shell driver running the harness) records this as a crash. The in-process harness does NOT emit CRASH lines — crashes terminate before the output can be written; the orchestrator attributes the current input to CRASH.

For directory iteration, the harness runs each input in the same process (no per-input fork) for speed. Crashes therefore terminate the full run. This is acceptable for the MVP: the seed corpus is known-good and should never crash. The orchestrator that handles corpus-wide fuzz runs is a shell loop `for f in corpus/*; do ./fuzz-parse "$f"; done` and catches crashes via exit code per input.

## Summary line

At the end of a directory run (NOT after a single-file run):

```
SUMMARY fuzz=<parse|exec> target=<c|rust> ok=<int> engine_error=<int> total=<int>
```

Exit 0 always (unless the harness was invoked with no arguments or on a nonexistent path — those are usage errors, exit 2). A CRASH terminates the process before the summary emits, so the orchestrator detects a missing SUMMARY as a crash.

## `parse-only` harness

Reads the input as a raw byte buffer, splits on ASCII `;` byte (naive byte-split — MVP does NOT tokenize-aware split; seed corpus is curated so no `;` appears inside string literals), passes each non-empty trimmed substatement to the tokenizer + parser in sequence. Discards each resulting AST. Expected outcomes: `OK` iff every substatement parses successfully; `ENGINE_ERROR` with the first failing substatement's `LEX_*` / `PARSE_*` kind. Any other outcome is a fuzz finding. A fully empty input (only whitespace / only semicolons) is `OK` (no substatement to parse).

## `exec-only` harness

Reads the input as SQL, splits on `;` (same rule as parse-only), parses + compiles + runs each non-empty substatement SEQUENTIALLY against the SAME fresh `:memory:` DB (so `CREATE; INSERT; SELECT` works as a realistic batch). Result rows (if any) are drained but not emitted. Expected outcomes: `OK` iff every substatement executes without error; `ENGINE_ERROR` with the first failing substatement's condition kind.

**Limitation**: the naive `;`-split does not handle `;` bytes inside string literals. For the curated seed corpus this is safe (no such input). When mutation-based fuzzing lands, a tokenizer-aware splitter MUST be added at the harness boundary to avoid false positives. (2026-04-18 pin — known gap.)

## Seed corpus

Inputs live under `tests/fuzz/corpus/sql/`:

- `valid/` — 50+ hand-curated SQL statements covering every grammar production we ship through Phase 9g.
- `malformed/` — 20+ SQL strings known to fail parse (unterminated strings, unbalanced parens, unknown keywords, etc.). Should ALL produce `ENGINE_ERROR`, NEVER `CRASH`.

Future stages add `corpus/sql-mutated/` (fuzzer-produced) and `corpus/db*/` (DB-level corpora).

## Byte-identical output requirement

The two harnesses must produce IDENTICAL per-input verdicts on both C and Rust builds given the same seed corpus. That is: the set of `ENGINE_ERROR` conditions and their kinds must match. SUMMARY differs only in the `target=` token.

The orchestrator driver (shell script) is NOT part of this spec — it's a thin loop. Documented in `tests/fuzz/run-fuzz-smoke.sh` (deferred).

## Scope cuts vs full fuzz-corpus spec

Omitted from MVP:
- libFuzzer / cargo-fuzz integration (the `LLVMFuzzerTestOneInput` entry-point form). Harness binary's argv form is sufficient for driving from a shell loop and from Python.
- Timeout/OOM enforcement (the harness doesn't install rlimit). Orchestrator handles this externally.
- The `roundtrip-db` and `roundtrip-sql` harnesses. Deferred because they need a Python driver and a mainline-SQLite comparison oracle.
- Corpus minimisation. First-stage corpus is hand-curated; minimisation passes come after a real fuzz campaign produces corpus-merge candidates.
