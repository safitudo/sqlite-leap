# Phase 6ad harness — GLOB / NOT GLOB pattern matching

Adds the GLOB operator (Unix-glob-style wildcards) as a byte-level match over UTF-8 strings. Case-SENSITIVE (unlike LIKE which is ASCII-case-insensitive). One new VDBE opcode `Scalar2::Glob` pinning invariant 44; `max_invariant=44`. One new reserved keyword `KEYWORD_GLOB`.

Gate: 9 fixtures green both targets. `SUMMARY phase=6ad target=<c|rust> passed=9 failed=0 total=9`.

Notes:
- Wildcards: `*` (any sequence, zero-or-more bytes), `?` (exactly one byte), `[abc]` (character class), `[a-z]` (range), `[!abc]` / `[!a-z]` (negated class).
- `*` and `?` match ANY byte, but a byte-level matcher: for multi-byte UTF-8, `?` matches one byte, not one codepoint. (Matches SQLite behavior.)
- Case-sensitive — `'A' GLOB 'a'` → 0.
- 3VL: NULL on either operand → NULL result (like LIKE).
- `NOT GLOB` desugars at compile time to `NOT (x GLOB y)` with the 3VL NULL rule: `NULL NOT GLOB x` → NULL.
- No ESCAPE clause (deferred; GLOB rarely uses escapes).
- Char-class syntax matches POSIX glob: `[!...]` is the negation marker (not `[^...]` like regex).
- Empty char-class `[]` and unbalanced `[` → `RUNTIME_INVALID_GLOB_PATTERN`.
