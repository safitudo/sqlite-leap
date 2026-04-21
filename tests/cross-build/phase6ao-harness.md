# Phase 6ao harness — scalar string/numeric funcs: SUBSTR / REPLACE / INSTR / ROUND

Extends the existing Phase 6j / 6s scalar-function infrastructure with four more functions. Two variadic-arity (SUBSTR, ROUND), two fixed-arity (REPLACE is 3-arg, INSTR is 2-arg). No new VDBE opcode kind needed — reuses `Scalar` (1-arg), `Scalar2` (2-arg), and introduces a new `Scalar3` opcode family for 3-arg functions (SUBSTR with explicit length, REPLACE). **One new invariant `Scalar3::*` base pinning `max_invariant=45`.** No new keywords (function names resolved as identifiers).

Gate: 15 fixtures green both targets. `SUMMARY phase=6ao target=<c|rust> passed=15 failed=0 total=15`.

Notes / semantics:

**SUBSTR(s, start, length?)** — 1-based indexing; byte-level (not codepoint).
- `SUBSTR(s, 1, 5)` — first 5 bytes.
- `SUBSTR(s, start)` without length — from `start` to end of string.
- Negative `start`: index from end. `-1` = last byte; `-3` = third from end.
- `start > length(s)` → empty string.
- `length` longer than remaining → truncated.
- Any arg NULL → NULL.

**REPLACE(s, from, to)** — replace all non-overlapping occurrences of `from` in `s` with `to`.
- Byte-level, case-sensitive.
- `from = ""` → returns `s` unchanged (matches SQLite convention).
- Any arg NULL → NULL.

**INSTR(s, needle)** — 1-based index of first byte of needle in s; 0 if not found.
- Byte-level, case-sensitive.
- Any arg NULL → NULL.

**ROUND(x, digits?)** — round-half-away-from-zero (NOT banker's rounding).
- `digits` defaults to 0.
- Result is always REAL.
- Negative `digits`: round to power of 10 (e.g. `ROUND(1234.5, -1)` → 1230.0).
- Integer arg is accepted and returned as REAL.
- Any arg NULL → NULL.
- TEXT arg that can't parse as number → returns 0.0 (matches SQLite; not explicitly tested in v1 fixtures).

Implementation discipline:
- SUBSTR and REPLACE need a 3-argument opcode variant. Introducing `Scalar3` is the cleanest addition; reuse the same dispatcher shape as `Scalar2` with an additional register.
- SUBSTR with 2 args compiles through the same 3-arg opcode with length = i64::MAX or a sentinel that means "to end"; OR via a separate Scalar2::Substr kind and both forms dispatch via a discriminator. Implementation choice.
- ROUND with 1 arg: use `Scalar::Round` single-operand; ROUND with 2 args: `Scalar2::Round`. Both should reuse the same `round_half_away_from_zero(x, digits)` core routine.
- Floating-point precision: use the target language's built-in `round()` (C: `round()` from math.h; Rust: `f64::round()`). Both produce round-half-away-from-zero. For non-zero `digits`, scale by `10^digits`, round, divide back. Be aware of representation drift on large `digits`; fixtures keep `|digits| ≤ 4` to avoid stressing this.
