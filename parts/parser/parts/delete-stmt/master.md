---
name: delete-stmt
kind: leaf
emits:
  rust: { path: src-rust/parser/delete_stmt.rs }
  c:    { path: src-c/parser/delete_stmt.c, headers: [src-c/parser/delete_stmt.h] }
---

# DELETE statement parser

Parses `DELETE FROM <table> [USING <other_table> [AS alias]]
[WHERE <expr>] [RETURNING <result_columns>]`.

## Scope

Admitted:
- `DELETE FROM <ident>` — delete all rows.
- `DELETE FROM <ident> WHERE <expr>` — delete filtered rows.
- `DELETE FROM <ident> USING <other_ident> [AS alias] WHERE <expr>` —
  cross-table delete (single-table USING stub; multi-table joins land
  when select-stmt's FromClause is wide enough to import).
- Optional trailing `RETURNING <result_columns>`.

Deferred:
- Schema-qualified table.
- Alias on DELETE target.
- `WITH ... DELETE ...` (CTE prefix).

## Algorithm (sketch)

```
parse_delete(tokens, i):
    expect KwDelete; expect KwFrom
    table = ident
    reject Dot/KwAs as before
    using = optional KwUsing -> ident [AS ident]
    where_ = optional KwWhere expr
    returning = optional KwReturning <result_columns>
    return Ok
```

## Correctness pins

1. No-WHERE — same as before.
2. With WHERE — same as before.
3. Missing FROM, missing table — same errors as before.
4. **USING** — `DELETE FROM t USING other WHERE t.id = other.id`
   parses with `using == Some({table:"other", alias:None})`.
5. **USING AS alias** — admitted.
6. **RETURNING** — `... RETURNING t.id` parses one Expr ResultColumn.
7. **RETURNING star** — admitted.
8. Embedded WHERE expression errors propagate.
9. Owned strings.
10. Statement terminator — parser stops BEFORE `;` / Eof.
11. No inline tests, no invented helpers.
12. **Reuse of ResultColumn** — imported from insert-stmt.

## Regeneration envelope

- Line budget: ~200-320 lines of Rust / ~350-650 lines of C.
- Public items: `DeleteUsingStub`, `DeleteStmt`, `DeleteParseOk`,
  `parse_delete`.
