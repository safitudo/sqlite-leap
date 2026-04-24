---
name: compiler/subqueries
kind: leaf
inherits:
  - /parts/compiler/parts/expressions/master.md
  - /parts/compiler/parts/name-resolution/master.md
  - /parts/compiler/parts/statements/select/master.md
emits:
  c: { path: src-c/compiler/subqueries.c, headers: [src-c/compiler/subqueries.h] }
  rust: { path: src-rust/src/compiler/subqueries.rs }
---

# Part: compiler/subqueries

Compiles subqueries in their four forms:

- **Scalar** — `(SELECT col FROM …)` returning exactly one row,
  one column. Embedded in an expression.
- **IN (subquery)** — `x IN (SELECT …)`. Embedded in an
  expression.
- **EXISTS (subquery)** — boolean test.
- **Derived table** — `FROM (SELECT …) AS t`. A FROM source, not
  an expression embed.

## Public interface

```
compile_scalar_subquery(select, ctx, dest_reg, program_out) -> Result<()>
compile_in_subquery(select, ctx, left_reg, result_reg, program_out) -> Result<()>
compile_exists_subquery(select, ctx, dest_reg, program_out) -> Result<()>
compile_derived_table(select, ctx, program_out) -> Result<DerivedSource>
```

## Correlated subqueries

A subquery that references outer-scope columns is **correlated**.
This sub-part:

1. Detects correlation by walking the inner AST with the outer
   scope's name-resolution. If name-resolution falls back to outer
   scope for any ColumnRef, the subquery is correlated.
2. For correlated subqueries, compiles into a nested-loop inner
   program that re-runs per outer row. The outer loop re-binds
   the outer-scope register slots; the inner program reads them
   via `Column` opcodes against the outer cursor.
3. For uncorrelated subqueries, compiles once and either
   materializes (IN, EXISTS) or substitutes the single result
   (scalar).

## Phase 6n sentinel

When a subquery appears inside an expression, the expression
compiler emits a placeholder register reference with a high-bit
sentinel encoding the subquery ID. After outer compilation, a
resolution pass walks the emitted opcodes and replaces each
placeholder with the concrete dest_reg allocated to that subquery.
This is the v1 "Phase 6n" mechanism, carried into v2 unchanged.

## Phase pins

- **Phase 6ag** — correlated subqueries.
- **Phase 6ah** — IN (subquery) form.
- **Phase 6ae** — EXISTS / NOT EXISTS.
- **Phase 6br** — subquery-in-FROM (derived tables).

## Regeneration envelope

- Target leaf size: 500–800 lines per target.
- Spec < 200 lines.
