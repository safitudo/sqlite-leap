---
name: update-stmt
kind: leaf
emits:
  rust: { path: src-rust/parser/update_stmt.rs }
  c:    { path: src-c/parser/update_stmt.c, headers: [src-c/parser/update_stmt.h] }
---

# UPDATE statement parser

Parses `[UPDATE OR <action>] UPDATE <table> SET col=expr[, ...]
[FROM <other_table> [AS alias]] [WHERE <expr>] [RETURNING <result_columns>]`.

## Scope

Admitted:
- OR-action prefix: REPLACE / IGNORE / ABORT / FAIL / ROLLBACK.
- `UPDATE <ident> SET <ident> = <expr>` (one or more assignments).
- Optional FROM clause — single bare table (`FromClauseStub`) for the
  scope-B push. Richer FROM (multi-table + JOINs) lands when select-stmt's
  FromClause stabilizes; this leaf re-imports then.
- Optional `WHERE <expr>`.
- Optional `RETURNING <result_columns>`.

Deferred:
- Schema-qualified table.
- Alias on UPDATE target.
- `WITH ... UPDATE ...` (CTE prefix).
- Tuple-assign `(c1, c2) = (e1, e2)`.

## Algorithm (sketch)

```
parse_update(tokens, i):
    expect KwUpdate; i += 1
    or_action = parse_or_action_opt(tokens, i)
    table = ident; i += 1
    reject Dot/KwAs as before
    expect KwSet
    assignments = parse `col = expr [, ...]`
    from_clause = parse_from_stub_opt(KwFrom -> ident [AS ident])
    where_      = parse_where_opt
    returning   = parse_returning_opt
    return Ok
```

## Correctness pins

1. Single assignment, no WHERE — same as before.
2. Multiple assignments — same as before.
3. With WHERE — same as before.
4. Expression RHS — same as before.
5. **OR-action** — `UPDATE OR REPLACE t SET a = 1` sets
   `or_action == Some(Replace)`; same for IGNORE/ABORT/FAIL/ROLLBACK.
6. **FROM clause** — `UPDATE t SET a = 5 FROM other WHERE t.id = other.id`
   parses with `from_clause == Some({table: "other", alias: None})`.
7. **FROM AS alias** — `... FROM other AS o ...` sets alias.
8. **RETURNING** — `... RETURNING t.a` parses with returning.len() == 1
   (Expr with col-ref).
9. **RETURNING star** — `RETURNING *` parses to single `Star`.
10. Missing SET, missing column, missing `=` — same errors as before.
11. Expression errors propagate.
12. Owned strings — table, assignment.column, alias, returning aliases.
13. Statement terminator — parser stops BEFORE `;` / Eof.
14. No inline tests, no invented helpers.
15. **Reuse of OrAction / ResultColumn** — both imported from insert-stmt
    so the wire shape is identical across DML.

## Regeneration envelope

- Line budget: ~300-450 lines of Rust / ~500-800 lines of C.
- Public items: `UpdateAssignment`, `FromClauseStub`, `UpdateStmt`,
  `UpdateParseOk`, `parse_update`.
