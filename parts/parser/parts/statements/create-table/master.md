---
name: parser/statements/create-table
kind: leaf
inherits:
  - /parts/parser/parts/expressions/master.md
emits:
  c: { path: src-c/parser/statements/create_table.c, headers: [src-c/parser/statements/create_table.h] }
  rust: { path: src-rust/src/parser/statements/create_table.rs }
---

# Part: parser/statements/create-table

Parses CREATE TABLE [IF NOT EXISTS] name (column_defs, table_constraints) [STRICT | WITHOUT ROWID].

## Column def grammar

```
ColumnDef := name [TypeName [(params)]]
             (ColumnConstraint)*
             [DEFAULT Expression]
             [GENERATED ALWAYS AS (Expression) [STORED | VIRTUAL]]
ColumnConstraint := NOT NULL | UNIQUE | PRIMARY KEY [AUTOINCREMENT]
                  | CHECK (Expression) | COLLATE name | REFERENCES ...
```

## Table constraint grammar

```
TableConstraint := PRIMARY KEY (col_list)
                | UNIQUE (col_list)
                | CHECK (Expression)
                | FOREIGN KEY (col_list) REFERENCES ...
```

## Phase pins

- **Phase 6af** — VARCHAR(N) type params.
- **Phase 6al** — DEFAULT.
- **Phase 6am** — NOT NULL.
- **Phase 6at** — CHECK.
- **Phase 6au** — multi-column constraints.
- **Phase 6ar** — INTEGER PRIMARY KEY AUTOINCREMENT.
- **Phase 6bi** — STRICT.
- **Phase 6bj** — GENERATED.

## Regeneration envelope

- Target leaf size: 300–500 lines per target.
- Spec < 100 lines.
