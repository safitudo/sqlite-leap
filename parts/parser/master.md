---
name: parser
kind: inner
inherits:
  - /spec/memory-discipline.spec.md
  - /schema/tokens.schema.json
  - /schema/ast.schema.json
  - /parts/tokenizer/master.md
emits:
  c:
    path: src-c/parser/mod.h
  rust:
    path: src-rust/src/parser/mod.rs
---

# Part: parser

Consumes a token stream from `tokenizer`. Produces an AST node per
`/schema/ast.schema.json`. The parser is **inner**: it decomposes
into per-statement parsers, a shared expressions parser, and a
shared clauses parser.

## Public interface

- **Input:** a token iterator/stream (parser decides which idiom
  per target, but the contract is ordered-consume-one-then-peek).
- **Output on success:** an `Ast<'src>` where `'src` is the
  tokenizer's source-buffer lifetime. Identifier-bearing AST fields
  are borrowed slices; value-bearing fields are owned.
- **Output on failure:** named condition `PARSE_ERROR` with
  `{offset, expected, got}`. Subtype conditions per statement type
  (e.g. `PARSE_ERROR_SELECT_MISSING_FROM`) where helpful for
  diagnostics.

## Dispatch contract (top-level)

The top-level parser examines the first significant token and
dispatches to a child statement parser. The dispatch table:

| First token (upper-cased) | Dispatch to |
|---|---|
| `SELECT` / `WITH` / `VALUES` | `parts/statements/select` |
| `INSERT` / `REPLACE` | `parts/statements/insert` |
| `UPDATE` | `parts/statements/update` |
| `DELETE` | `parts/statements/delete` |
| `CREATE TABLE` | `parts/statements/create-table` |
| `CREATE INDEX` / `CREATE UNIQUE INDEX` | `parts/statements/create-index` |
| `CREATE VIEW` / `CREATE TEMPORARY VIEW` | `parts/statements/create-view` |
| `DROP` | `parts/statements/drop` |
| `ALTER TABLE` | `parts/statements/alter-table` |
| `PRAGMA` | `parts/statements/pragma` |
| `BEGIN` / `COMMIT` / `ROLLBACK` / `SAVEPOINT` / `RELEASE` | (transaction control, absorbed here) |
| `ANALYZE` / `VACUUM` / `REINDEX` / `ATTACH` / `DETACH` | (low-priority, stubbed) |

Statement terminator `;` is optional at EOF, required between
statements in a batch.

## Shared parsers

`parts/expressions/` and `parts/clauses/` are reused across
statement parsers. When a statement parser needs to parse an
expression (for WHERE, SET, SELECT list, etc.) it calls the shared
expressions parser via the interface declared in
`parts/expressions/master.md`.

Clauses (WHERE, GROUP BY, HAVING, ORDER BY, LIMIT/OFFSET, JOIN,
FROM-source) are specified in `parts/clauses/master.md` and
instantiated per-statement with statement-specific legality rules.

## Cross-statement invariants

- Operator precedence is declared once in `parts/expressions/` and
  followed everywhere an expression is parsed.
- Identifier resolution (table.column vs column, schema.table.column,
  quoting rules) is uniform across all statements.
- Trailing comma in a column list or tuple is rejected, mirroring
  mainline SQLite.
- Reserved keyword vs identifier: context-sensitive fallback — some
  reserved words (e.g. `OFFSET`, `PARTITION`) are parsed as
  identifiers when they appear in column/table positions.

## Memory discipline

All AST nodes carry the source-buffer lifetime `'src`. Identifier
fields are borrowed; literal value fields are owned (so Value::Text
survives the source buffer for emitted rows).

## What this part does NOT own

- Name resolution (column → table.column, alias scoping): owned by
  `parts/compiler/parts/name-resolution/`. Parser emits raw
  identifier references; the compiler resolves them.
- Type checking: owned by the compiler.
- Semantic legality beyond grammar: owned by the compiler.

## Composition (inner part default)

Each statement sub-part emits its own module; this part's generator
produces a `mod.rs` (Rust) or `parser.h` aggregator (C) that
exposes `parse(tokens) -> Ast` and dispatches to statement parsers.
