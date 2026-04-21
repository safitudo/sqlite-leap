# Phase 6ai harness — COUNT(DISTINCT) / SUM(DISTINCT) + MIN/MAX on strings

Adds per-aggregate dedup machinery (DISTINCT modifier inside aggregate-function calls) and fills in MIN/MAX coverage for string values. No new opcodes; extends existing aggregate step-state with an optional dedup set keyed by the input value.

Gate: 10 fixtures green both targets. `SUMMARY phase=6ai target=<c|rust> passed=10 failed=0 total=10`.

Notes:
- `COUNT(DISTINCT expr)` and `SUM(DISTINCT expr)` both use the same dedup machinery; `DISTINCT` is accepted inside any aggregate call.
- Per-aggregate dedup set is a hash table keyed by the NORMALIZED value (integer/real/text — never NULL; NULL skips as before).
- With GROUP BY: the dedup set is reset per group (same lifetime as the group's accumulator).
- MIN/MAX on strings uses byte-lexicographic comparison (already in spec 6c; 6ai ensures the implementation actually supports TEXT operands).
- Type-mixed input to MIN/MAX follows existing ordering rule: INTEGER < REAL < TEXT (pre-existing spec, not new in 6ai).
- No new error kinds.
