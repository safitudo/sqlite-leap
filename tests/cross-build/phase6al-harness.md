# Phase 6al harness — DEFAULT in CREATE TABLE

Parser + compile extension. `column-def` accepts optional `DEFAULT <literal-or-paren-expr>`. INSERT evaluates default when column omitted. New `INSERT INTO t DEFAULT VALUES;` form. No new opcodes.

Gate: 8 fixtures green both targets. `SUMMARY phase=6al target=<c|rust> passed=8 failed=0 total=8`.

Notes:
- Default expression MUST be constant-time (literal or paren'd constant expression). Column refs in DEFAULT → `COMPILE_INVALID_DEFAULT_EXPRESSION` at compile time.
- Signed numeric literal form (`DEFAULT -1`) must parse as a literal (not a UnaryOp) — store the negated integer/real directly.
- `INSERT ... DEFAULT VALUES` form: no VALUES keyword followed by tuples; just `DEFAULT VALUES`.
