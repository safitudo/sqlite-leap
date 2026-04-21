# Phase 6ap harness — GROUP_CONCAT + TOTAL aggregates

Two new aggregate functions resolved by name (identifier), like Phase 6c's `COUNT`/`SUM`/etc. Reuses the existing AggStep opcode infrastructure — each function has its own accumulator semantics. No new VDBE opcode kind required. `max_invariant=45` unchanged. No new keywords (function names are identifiers).

Gate: 10 fixtures green both targets. `SUMMARY phase=6ap target=<c|rust> passed=10 failed=0 total=10`.

### GROUP_CONCAT semantics

- `GROUP_CONCAT(expr)` — default separator `","`. Concatenates the string-coerced values of expr across the group.
- `GROUP_CONCAT(expr, sep)` — explicit separator (constant TEXT expression).
- Skip NULL values silently (like other aggregates).
- Empty input (or all-NULL input) → NULL (standard aggregate semantics).
- Non-text values are coerced to text using SQLite's standard text-coercion (integers → decimal string, reals → `%!.15g` format from 6r).
- Order of concatenation is **implementation-defined** per SQLite — typically insertion / scan order. v1 uses insertion order (matches the scan order); fixtures use small inputs where order is deterministic.

### TOTAL semantics

- Numerically-equivalent to SUM, with ONE CRITICAL DIFFERENCE: empty input or all-NULL input returns `0.0` (not NULL). Always returns REAL.
- `TOTAL(v)` where v is integer column → result is REAL `sum`.
- Skip NULL values; empty after skipping → 0.0.

### Implementation

- Extend the aggregate-function name dispatcher to recognize `GROUP_CONCAT` (and its snake-case alias if any) and `TOTAL` (case-insensitive).
- `GROUP_CONCAT` accumulator state: `Option<String> + separator: String`. On AggStep: if skip-NULL, skip; else coerce to string, if acc is None, set to string; else append separator + string.
- `TOTAL` accumulator state: `f64` (default 0.0). On AggStep: if NULL, skip; else add f64-coerced value to accumulator. On finalize: always return `Value::Real(acc)`.
- Non-string-separator in `GROUP_CONCAT(expr, sep)` where sep is non-TEXT: coerce to text (matches SQLite).
- `GROUP_CONCAT(DISTINCT x)` (dedup) inherits from 6ai's DISTINCT machinery but is NOT fixture-tested in 6ap — reserved for 6ap extension if needed.

### Cross-corroboration watch

- The separator argument in `GROUP_CONCAT(expr, sep)` requires the 2-arg aggregate parse path. If the parser previously only accepted 1-arg aggregates, both targets will need to extend. The extension should be straightforward (aggregate-call grammar already allows multiple expressions in the inner parens per 6ai's DISTINCT support).
