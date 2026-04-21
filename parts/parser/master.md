# Part: parser

Consumes a token sequence and produces an AST node for a single SQL statement per `spec/sql-grammar.spec.md` (Phase 1 grammar + "Phase 2a grammar" sections).

## Contract

- **Input:** a token sequence conforming to `schema/tokens.schema.json`. The sequence is produced by the `tokenizer` part but the parser MUST NOT assume anything about its provenance beyond schema conformance.
- **Output on success:** a single AST node conforming to `schema/ast.schema.json` — one of `CreateTable`, `Insert`, `SelectLiteral`, `SelectFrom`.
- **Output on failure:** the single error condition `PARSE_UNEXPECTED_TOKEN`, carrying `kind` (the offending token's kind, as a string literal matching one of the token kinds in `schema/tokens.schema.json`), `pos` (the offending token's `pos`), and `expected` (a non-empty set of token kinds the parser would have accepted at that position).

Each language target represents "success or failure" in its own idiomatic way.

## Required behaviour

The parser MUST:

- Accept one statement per call, terminated by `SEMICOLON` (optional) then `EOF`
- Match the grammar in `spec/sql-grammar.spec.md` exactly (Phase 1 + Phase 2a sections)
- Use one-token lookahead where the grammar specifies it (e.g. after `SELECT` to choose `SelectLiteral` vs `SelectFrom`)
- Produce AST nodes whose strings (`table` field, `name` fields inside `ColumnDef`, projection `columns`) preserve the case of the source `IDENTIFIER`'s `name` field exactly
- Terminate unsuccessfully with `PARSE_UNEXPECTED_TOKEN` when the grammar does not match — carrying the offending token's `kind`, its `pos`, and a set of one or more `expected` token kinds. The `expected` set is order-insensitive and target-defined in representation (array, bitmask, hashset, etc.); the harness compares it as a set.
- Be pure: no I/O, no global state, no mutation of the input token sequence

The parser MUST NOT:

- Re-tokenize the input (it operates on tokens, not text)
- Evaluate literals, coerce types, or touch storage — all that is the executor's job
- Accept any statement form outside the Phase 1 + Phase 2a grammar
- Import or reference any other part's generated code

## Duplicate column names in source

Phase 2a detection of duplicate column names in a `CREATE TABLE` declaration is NOT the parser's job; it lives in the storage layer (`STORAGE_DUPLICATE_COLUMN`). The parser accepts any syntactically-valid column list and emits it as an AST; the executor calls into storage, which enforces uniqueness. Similarly for duplicate names inside `INSERT`'s column list.

## Part independence

The parser depends only on:

- `spec/sql-grammar.spec.md`
- `schema/tokens.schema.json` (input)
- `schema/ast.schema.json` (output)

## Implementation freedom

The parser MAY use recursive descent, an explicit state machine, a table-driven approach, or any equivalent; each target picks what reads best in its language. Internal state (cursor, lookahead buffer, depth counters) is implementation detail — not part of the public contract.

## Phase 2c-1 note

Phase 2c-1 restructures the SELECT AST: `SelectLiteral` and `SelectFrom` are retired and unified into a single `Select` kind with `{kind, projection, table}` where `table` is nullable and `projection` is either `Star` or `Expressions` (a list of `Expression` records). See `schema/ast.schema.json` and `spec/sql-grammar.spec.md` § "Phase 2c-1 grammar".

Expression parsing uses the standard precedence ladder (`comparison > additive > multiplicative > unary > primary`). Comparison is non-chaining: `1 < 2 < 3` is a parse error after the second `<` (the parser expects `SEMICOLON`, `EOF`, or `COMMA` after the first comparison).

The `STAR` token is overloaded: after `SELECT`, it is "star projection" iff the next token is `KEYWORD_FROM`; otherwise entering `STAR` in expression position is a parse error (no prefix `STAR`).

Parser errors in 2c-1 remain under the single `PARSE_UNEXPECTED_TOKEN` name; only the `expected` sets expand to include new operator tokens.

## Phase 2c-2 note

Phase 2c-2 extends the grammar with an optional `WHERE` clause on SELECT and three new logical operators (`AND`, `OR`, `NOT`). The `Select` AST kind gains a `where` field (`Expression | null`); the `BinOp` enum gains `"AND"`, `"OR"`; the `UnaryOp` enum gains `"NOT"`.

The expression precedence ladder extends BELOW Phase 2c-1's comparison layer:

```
expression  := logical-or
logical-or  := logical-and (KEYWORD_OR  logical-and)*
logical-and := logical-not (KEYWORD_AND logical-not)*
logical-not := KEYWORD_NOT logical-not | comparison
```

`NOT` is right-associative (so `NOT NOT x` parses as `NOT (NOT x)`). `AND` and `OR` are left-associative. `AND` binds tighter than `OR` (so `x OR y AND z` parses as `x OR (y AND z)`).

`WHERE` without a preceding `FROM` is a parse error; the `WHERE` keyword only appears after `FROM IDENTIFIER` in the grammar. After a bare `SELECT expression-list`, the parser's expected set at end-of-projection remains `[SEMICOLON, EOF, COMMA, KEYWORD_FROM]` (NOT including `KEYWORD_WHERE`).

The identifier-vs-keyword precedence rule still holds: `and`, `or`, `not`, `where` (case-insensitive) are now reserved and cannot be used as `IDENTIFIER`.

## Phase 2c-3 note

Phase 2c-3 adds two top-level statement alternatives: `UPDATE` and `DELETE`. The parser now discriminates among 5 forms at the start of a statement, using one-token lookahead:

- `KEYWORD_SELECT` → select-statement
- `KEYWORD_CREATE` → create-statement
- `KEYWORD_INSERT` → insert-statement
- `KEYWORD_UPDATE` → update-statement
- `KEYWORD_DELETE` → delete-statement
- anything else → `PARSE_UNEXPECTED_TOKEN` with `expected = [KEYWORD_SELECT, KEYWORD_CREATE, KEYWORD_INSERT, KEYWORD_UPDATE, KEYWORD_DELETE]`.

New AST kinds:

- `Update { kind: "Update", table: string, assignments: [{column: string, value: Expression}], where: Expression | null }`
- `Delete { kind: "Delete", table: string, where: Expression | null }`

Grammar:
```
update-statement := KEYWORD_UPDATE IDENTIFIER KEYWORD_SET assignment (COMMA assignment)* [KEYWORD_WHERE expression]
assignment       := IDENTIFIER EQ expression
delete-statement := KEYWORD_DELETE KEYWORD_FROM IDENTIFIER [KEYWORD_WHERE expression]
```

The identifier-vs-keyword precedence rule still holds: `update`, `delete`, `set` (case-insensitive) are reserved keywords and cannot be used as `IDENTIFIER`.

## Output location

Generated code lives in `src-{lang}/parser/`. Exposes exactly one public entry point that accepts a token sequence and returns an AST node or the named error.
