---
name: parser/statements/select
kind: leaf
inherits:
  - /parts/parser/parts/expressions/master.md
  - /parts/parser/parts/clauses/master.md
emits:
  c: { path: src-c/parser/statements/select.c, headers: [src-c/parser/statements/select.h] }
  rust: { path: src-rust/src/parser/statements/select.rs }
---

# Part: parser/statements/select

Parses SELECT / VALUES / WITH [RECURSIVE] ... SELECT. Produces a
`SelectCore<'src>` AST.

## Grammar (informal)

```
Select      := [With] SelectCore (CompoundOp SelectCore)* [OrderBy] [Limit]
CompoundOp  := UNION | UNION ALL | INTERSECT | EXCEPT
SelectCore  := SELECT [DISTINCT | ALL] ProjectionList
              [FROM FromList]
              [WHERE Expression]
              [GROUP BY ExpressionList [HAVING Expression]]
              [WINDOW WindowSpecList]
            | VALUES TupleList
Projection  := * | tablename.* | Expression [AS? alias]
```

## Phase pins

- **Phase 6aa** — non-recursive CTEs.
- **Phase 6bl** — WITH RECURSIVE.
- **Phase 6bd** — SELECT ALL keyword.
- **Phase 6as** — UNION ALL.
- **Phase 6bp** — no-FROM SELECT.

## Regeneration envelope

- Target leaf size: 300–500 lines per target.
- Spec < 100 lines.
