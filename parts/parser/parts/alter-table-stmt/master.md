---
name: alter-table-stmt
kind: leaf
emits:
  rust: { path: src-rust/parser/alter_table_stmt.rs }
  c:    { path: src-c/parser/alter_table_stmt.c, headers: [src-c/parser/alter_table_stmt.h] }
---

# ALTER TABLE statement parser

Parses an `ALTER TABLE` statement. Reuses `ColumnDef` from
`/parts/parser/parts/create-table-stmt` for the ADD COLUMN form. This
is the first DDL leaf to share an AST sub-type across statement
parsers and validates that cross-leaf type re-use works without
duplicating the parser.

## Scope

Admitted:
- `ALTER TABLE <name> RENAME TO <new_name>`.
- `ALTER TABLE <name> RENAME [COLUMN] <old> TO <new>`.
- `ALTER TABLE <name> ADD [COLUMN] <col_def>`.
- `ALTER TABLE <name> DROP [COLUMN] <name>`.

Deferred (flag ParseError `deferred: <construct>`):
- Schema-qualified `<schema>.<table>`.
- Multiple comma-separated alterations in one statement (SQLite
  doesn't admit this either; we make the rejection explicit).

## Algorithm

```
parse_alter_table(tokens, i):
    expect tokens[i] == KwAlter; i += 1
    expect tokens[i] == KwTable; i += 1
    if tokens[i] != Ident: error("expected table name")
    name = tokens[i].text; i += 1
    if tokens[i] == Dot: error("deferred: schema-qualified table")
    op = parse_alter_op(tokens, i)
    return Ok({ name, op: op.op }, next: op.next)

parse_alter_op(tokens, i):
    match tokens[i]:
        KwRename:
            i += 1
            if tokens[i] == KwTo:
                i += 1
                if tokens[i] != Ident: error("expected new table name")
                new_name = tokens[i].text; i += 1
                return RenameTable { new_name }, i
            if tokens[i] == KwColumn: i += 1
            if tokens[i] != Ident: error("expected column name")
            old = tokens[i].text; i += 1
            expect tokens[i] == KwTo; i += 1
            if tokens[i] != Ident: error("expected new column name")
            new = tokens[i].text; i += 1
            return RenameColumn { old, new }, i
        KwAdd:
            i += 1
            if tokens[i] == KwColumn: i += 1
            def, i = parse_column_def(tokens, i)
            return AddColumn { def }, i
        KwDrop:
            i += 1
            if tokens[i] == KwColumn: i += 1
            if tokens[i] != Ident: error("expected column name")
            n = tokens[i].text; i += 1
            return DropColumn { name: n }, i
        else: error("expected RENAME / ADD / DROP after table name")
```

The ADD COLUMN branch invokes the ColumnDef parser. Because rust
modules don't expose private fns across files, the column-def parsing
is re-implemented here in a minimal form (NotNull / PrimaryKey /
Unique / Default only — Check, References, Generated, Collate are
**explicitly deferred** on the ALTER ADD COLUMN path; SQLite itself
restricts the column constraints admitted in ALTER ADD). This is
flagged in pin 7. The generator should NOT recurse into the
create-table-stmt source file; the ColumnDef *type* is imported but
the *parser* is locally re-emitted in a reduced form.

## Correctness pins

1. **RENAME TO** — `ALTER TABLE t RENAME TO t2` →
   `{ name: "t", op: RenameTable { new_name: "t2" } }`.
2. **RENAME COLUMN with keyword** — `ALTER TABLE t RENAME COLUMN a TO b`
   → `RenameColumn { old: "a", new: "b" }`.
3. **RENAME COLUMN without keyword** — `ALTER TABLE t RENAME a TO b`
   produces the same `RenameColumn` AST. The COLUMN token is
   optional.
4. **ADD COLUMN with keyword** — `ALTER TABLE t ADD COLUMN d REAL` →
   `AddColumn { def: { name: "d", type_name: Some("REAL"), constraints: [] } }`.
5. **ADD COLUMN without keyword** — `ALTER TABLE t ADD d REAL`
   produces the same AST.
6. **DROP COLUMN** — `ALTER TABLE t DROP COLUMN c` →
   `DropColumn { name: "c" }`. `DROP c` (no keyword) also valid.
7. **ADD COLUMN constraint scope** — only `NOT NULL`, `PRIMARY KEY`,
   `UNIQUE`, and `DEFAULT <literal>` are admitted in the ALTER path.
   `CHECK`, `REFERENCES`, `GENERATED`, `COLLATE` produce a
   `deferred: ALTER ADD <construct>` ParseError. (SQLite imposes
   similar restrictions; keeping this surface tight avoids cloning
   the full constraint dispatch.)
8. **Statement terminator** — stops BEFORE `;` / Eof; `next` points
   at the terminator.
9. **Owned strings** — every string field in the AST is owned.
10. **Deferred constructs are explicit** — schema-qualified table,
    extended ADD COLUMN constraints each emit a
    `deferred: <construct>` message.
11. **No inline tests, no invented helpers** — exports only
    `parse_alter_table` and the declared AST types.

## Regeneration envelope

- Line budget: **~250-380 lines** of Rust. The volume comes from the
  reduced inline column-def parser plus the four-arm op dispatch.
- No dependencies beyond std and the `ColumnDef` /
  `ColumnConstraint` types from `create_table_stmt`.
- Public items: `AlterTableStmt`, `AlterOp`, `AlterTableParseOk`,
  `parse_alter_table`.

## Smoke probe

Covered in `src-rust/examples/ddl_parse_smoke.rs`:
`ALTER TABLE t RENAME COLUMN b TO c` and
`ALTER TABLE t ADD COLUMN d REAL`.
