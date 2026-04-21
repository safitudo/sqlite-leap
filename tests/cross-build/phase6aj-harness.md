# Phase 6aj harness — column alias visible in GROUP BY / ORDER BY / HAVING

Compiler-only phase. No new opcodes. Extends name-resolution scope so that an `AS <alias>` defined in the projection list is visible in GROUP BY, ORDER BY, and HAVING — matching SQLite semantics.

Gate: 7 fixtures green both targets. `SUMMARY phase=6aj target=<c|rust> passed=7 failed=0 total=7`.

Notes:
- WHERE is evaluated before projection → aliases are NOT in WHERE scope. `COMPILE_UNKNOWN_COLUMN` is the correct error for alias-in-WHERE.
- GROUP BY / ORDER BY / HAVING resolution order: try alias first (projection-scope), then fall through to underlying table columns.
- When an alias shadows a real column name, the alias wins in post-projection scopes.
- Two projections with the same alias → resolving that alias from ORDER BY is ambiguous → `COMPILE_AMBIGUOUS_ALIAS` at compile time (do NOT silently pick one).
- Alias can reference any projection expression (not just column refs): `SELECT a*10 AS scaled ... ORDER BY scaled`.
- No runtime cost — alias substitution happens at compile time by rewriting the GROUP BY / ORDER BY / HAVING expression to reference the projection's expression or the output-row register.
