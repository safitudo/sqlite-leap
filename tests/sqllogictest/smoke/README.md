# sqllogictest smoke suite

Six hand-authored `.test` files exercising the canonical record types, every rendering rule, and the grammar productions currently shipping (through Phase 9g). This is the bootstrap corpus for the sqllogictest runner (`spec/sqllogictest-runner.spec.md`). The runner itself is gated by these passing on both C and Rust builds.

| File | Coverage |
|---|---|
| `01-literals.test` | Integer / real / text / NULL literals, empty string, multi-column results, `query` type-string tokens (I/R/T). |
| `02-create-insert-select.test` | CREATE TABLE, INSERT, SELECT, COUNT, `nosort` vs `rowsort` record modes. |
| `03-where-clauses.test` | Equality, inequality, range, BETWEEN, AND, OR. |
| `04-errors.test` | `statement error` for missing table/column, duplicate CREATE, parse errors. |
| `05-aggregates.test` | COUNT, SUM, AVG, MIN, MAX; with and without GROUP BY; REAL result from AVG. |
| `06-index.test` | CREATE INDEX, index-backed equality + range, DROP INDEX, UNIQUE rejection. |

Not a substitute for the full sqllogictest corpus — this is the smoke gate for the runner, per § "Test authority" of the runner spec. The full `select1..5.test` etc. porting lands in a later phase.

When adding a new feature to the engine, add a matching smoke file here FIRST (before porting mainline `.test` files) to lock in the behavioural contract of the new feature in the sqllogictest format.
