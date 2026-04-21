# SQL grammar — language-neutral spec

This spec is consumed by every language target (C, Rust, WASM). No language idioms.
See `CLAUDE.md` for the dual-target discipline rules.

## Scope — Phase 1 only

Phase 1 recognises exactly one statement form:

```
SELECT <literal>
```

with an optional trailing semicolon and arbitrary inter-token whitespace.
No tables, no FROM, no expressions beyond a single literal, no clauses.

Later phases extend this document; this section is authoritative for Phase 1.

## Character classes

- `DIGIT`       — one of the ten ASCII code points `0`..`9` (U+0030..U+0039)
- `ALPHA`       — ASCII letters `A`..`Z` (U+0041..U+005A) or `a`..`z` (U+0061..U+007A)
- `ALPHANUM`    — `ALPHA` or `DIGIT`
- `WHITESPACE`  — any of the four ASCII code points space (U+0020), tab (U+0009), line-feed (U+000A), carriage-return (U+000D)
- `SQUOTE`      — the ASCII code point U+0027 (`'`)

## Tokens

Tokens are produced left-to-right by longest match. Whitespace between tokens is consumed and discarded. Every token carries a `pos` field equal to the 0-based index of its first character in the input string.

| Token kind          | Rule                                                                                                                                                             |
|---------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `KEYWORD_SELECT`    | The six letters `S`, `E`, `L`, `E`, `C`, `T` (ASCII, case-insensitive), NOT followed by an `ALPHANUM` or underscore (U+005F). The following character (if any) is not consumed. |
| `KEYWORD_NULL`      | The four letters `N`, `U`, `L`, `L` (ASCII, case-insensitive), bounded the same way.                                                                             |
| `INTEGER_LITERAL`   | One or more `DIGIT`, NOT followed by an `ALPHA` or underscore. Carries a numeric `value` equal to the decimal integer represented by those digits.                |
| `STRING_LITERAL`    | `SQUOTE`, followed by zero or more characters where each is either a non-`SQUOTE` character or the two-character sequence `SQUOTE SQUOTE`, followed by a closing `SQUOTE`. Carries a textual `value` equal to the characters between the opening and closing `SQUOTE`, with each two-`SQUOTE` sequence collapsed to one `SQUOTE`. |
| `SEMICOLON`         | The single ASCII character `;`.                                                                                                                                  |
| `EOF`               | Emitted exactly once, at a position equal to the length of the input, after all other tokens. Consumes no characters.                                            |

### Integer range

The `value` carried by an `INTEGER_LITERAL` is an integer. Phase 1 assumes it fits in a 64-bit signed range (−2^63 .. 2^63−1). If the literal overflows that range the tokenizer terminates unsuccessfully with error `LEX_INTEGER_OVERFLOW` (see "Error conditions").

Note: the lower bound −2^63 is not reachable in Phase 1 — the tokenizer only recognises non-negative magnitudes because unary minus is out of scope. The symmetric bound is stated to document the intended range; later phases introduce unary minus and the full negative range becomes reachable. A generator MUST NOT infer from this section that the literal `-9223372036854775808` is accepted in Phase 1.

### Error conditions (tokenizer)

The tokenizer terminates in one of two ways:

- **Successfully**, yielding a sequence of tokens ending with a single `EOF`.
- **Unsuccessfully**, with one named error condition:
  - `LEX_UNEXPECTED_CHARACTER` — no token rule applies at the current input position. Carries `pos` (0-based, the offending character's index).
  - `LEX_UNTERMINATED_STRING` — a `STRING_LITERAL` started but the input ended before its closing `SQUOTE`. Carries `pos` of the opening `SQUOTE`.
  - `LEX_INTEGER_OVERFLOW` — an integer literal's value is outside the 64-bit signed range. Carries `pos` of the literal's first digit.

Each language target decides how to represent these outcomes idiomatically (e.g. tagged return values in C, `Result<Tokens, LexError>` in Rust). The spec MUST NOT assume either representation.

### Target-defined conditions

Conditions that are NOT specific to SQL semantics — notably memory exhaustion, and (in later phases) OS-level I/O failures — are TARGET-DEFINED. Each language target surfaces them through its idiomatic mechanism (e.g. allocator-failure return + out-pointer in C, panic or `Result` at the boundary in Rust, thrown exception in a hypothetical JavaScript target). These conditions are NOT exercised by the cross-build test suite and are NOT specified as named SQL-level errors. Generators MUST NOT invent new LEX_* / PARSE_* names to surface them.

## Grammar

```
statement         := select-statement [ SEMICOLON ] EOF
select-statement  := KEYWORD_SELECT literal
literal           := INTEGER_LITERAL | STRING_LITERAL | KEYWORD_NULL
```

### Error conditions (parser)

The parser terminates in one of two ways:

- **Successfully**, yielding exactly one `select-statement` derivation.
- **Unsuccessfully**, with one named error condition:
  - `PARSE_UNEXPECTED_TOKEN` — the next token does not match the grammar. Carries `kind` (the offending token's kind), `pos` (its position), and `expected` (a set of one or more token kinds the parser would have accepted).

### The `expected` set — construction rule (applies to ALL phases)

When the parser raises `PARSE_UNEXPECTED_TOKEN` at position `p`, the `expected` field is defined as:

> **The set of token kinds that, if placed at position `p` instead of the offending token, would allow the parser to make progress from the current grammar state.**

"Make progress" means: the token matches a terminal in the currently-active production (or a production reachable via any already-entered, not-yet-closed non-terminal). This is inherently position-dependent and computed per grammar state, not per phase.

Concretely, this implies two constructive sub-rules the parser MUST follow:

1. **At expression-start position** (after `SELECT` introducing a projection, after a binary operator, after a prefix unary `-`, after `LPAREN` in an expression context, after a `COMMA` separating list elements): `expected` contains exactly the tokens that can start a primary (`INTEGER_LITERAL`, `STRING_LITERAL`, `KEYWORD_NULL`, `IDENTIFIER`), plus tokens that can open a parenthesised sub-expression (`LPAREN`), plus tokens that can introduce a prefix unary operator (`MINUS`). Phase 1 (pre-identifier, pre-expression) naturally omits the identifier, paren, and minus entries; Phase 2a introduces them lazily as its grammar grows.

2. **At expression-continuation position** (immediately after a fully-reduced expression has been produced at the current precedence level): `expected` contains exactly the tokens whose appearance would keep the containing construct alive. In detail:
   - The currently-active expression-parsing frame contributes its valid binary-operator continuations (e.g. inside an `additive` frame: `PLUS`, `MINUS`; inside a `comparison` frame: none, since comparison is non-chaining — see Phase 2c-1).
   - The enclosing non-terminal contributes its own continuations (e.g. projection-list contributes `COMMA`, `KEYWORD_FROM`; top-level statement contributes `SEMICOLON`, `EOF`; parenthesised expression contributes `RPAREN`).
   - Because an expression-parsing frame is greedy — it absorbs every operator at its precedence level before returning — no binary-operator token at the offending position can be "expected" at that position unless the test stray-token reasoning finds one that matches a still-open frame. In practice: if the offending token is itself a binary operator of a precedence already closed by the greedy pass, it is NOT in the `expected` set of the enclosing non-terminal; only the enclosing non-terminal's continuations appear.

Equality with `expect.expected` in test cases is **order-insensitive** (set equality). Generators MUST produce a set whose members exactly match the test case's set at every error position the test exercises.

**Canonical examples** (names refer to test cases in the cross-build suite):

| Situation (offending token position) | Minimal expected set |
|---|---|
| After `KEYWORD_SELECT`, non-primary-starter arrives | `[STAR, IDENTIFIER, INTEGER_LITERAL, STRING_LITERAL, KEYWORD_NULL]` — Phase 2a-pinned 5-element form-discriminator set; does NOT widen to include MINUS/LPAREN/KEYWORD_NOT even though those legally start an expression. This is a frozen spec-legacy narrow set. |
| After a completed top-level expression in projection-list, any stray (Phase 2a and later era) | `[SEMICOLON, EOF, COMMA, KEYWORD_FROM]` — uniform 4-element set regardless of stray-token kind. Phase 1's `trailing-garbage` test was widened in Phase 2c-2 to this form. |
| Inside parens, unmatched RPAREN missing, completed sub-expression (arithmetic/comparison frame) | `[RPAREN, PLUS, MINUS, STAR, SLASH, EQ, NEQ, LT, LE, GT, GE]` — phase2c1 `parse-error-missing-rparen`. Does NOT include `KEYWORD_AND` / `KEYWORD_OR` because logical operators are outside the arithmetic/comparison frame; the frame is closed at comparison and logical-ops apply at a higher layer. |
| Prefix `STAR` with no left operand | `[IDENTIFIER, INTEGER_LITERAL, STRING_LITERAL, KEYWORD_NULL, MINUS, LPAREN]` — phase2c1 `parse-error-prefix-star`. Excludes `KEYWORD_NOT` because the frame is `unary` / `primary`, not `logical-not`. |
| Expression-start at a logical-layer position (after `WHERE`, after `AND`, after `OR`, after `NOT`) | `[INTEGER_LITERAL, STRING_LITERAL, KEYWORD_NULL, IDENTIFIER, MINUS, LPAREN, KEYWORD_NOT]` — phase2c2. Includes `KEYWORD_NOT` because the frame is `logical-not`. |
| `signed-literal`-start position inside `INSERT VALUES` (after the opening `LPAREN` or after a `COMMA` between values) | `[MINUS, INTEGER_LITERAL, STRING_LITERAL, KEYWORD_NULL]` — phase3a. Narrow 4-element set: the `signed-literal` frame is strictly tighter than full expression (no `IDENTIFIER`, no `LPAREN`, no `KEYWORD_NOT`), but widens from the Phase 2a `literal`-only set to include `MINUS`. |

The rule is language-neutral: both a recursive-descent parser and a table-driven parser, correctly implemented, MUST produce the same set at every error position because the set is defined by the grammar state, not by the parser recipe.

## Evaluation

A matched `select-statement` produces exactly one result row with exactly one column. The column value derives from the `literal`:

- `INTEGER_LITERAL` → the token's numeric `value`, typed as a 64-bit signed integer.
- `STRING_LITERAL`  → the token's textual `value`, typed as UTF-8 text (Phase 1 assumes ASCII-only input).
- `KEYWORD_NULL`    → the SQL NULL value.

The evaluator performs NO type coercion in Phase 1.

### Error conditions (evaluator)

The evaluator in Phase 1 terminates successfully iff the parser succeeded. It does not introduce new error conditions beyond those propagated from earlier stages.

## Non-goals for Phase 1

The following are intentionally out of scope and MUST NOT be implemented (their presence in generated code is a spec-leak and a Phase 1 gate failure):

- Negative or floating-point literals
- Unary or binary operators
- Any keyword other than `SELECT` and `NULL`
- `FROM`, `WHERE`, `ORDER BY`, `LIMIT`, or any other clause
- Multi-statement batches
- Named parameters, identifiers, column references
- Type affinity or coercion

## Test authority

`tests/cross-build/phase1.json` is the executable specification of correctness for Phase 1. If this document and the tests disagree, the tests win. Same convention applies for later phases with their respective test files.

---

## Phase 2a — extended grammar and stateful execution

This section layers on top of Phase 1. Every Phase 1 token, every Phase 1 grammar rule, every Phase 1 error, and every Phase 1 semantic remains valid unchanged in Phase 2a. Phase 2a only ADDS new productions and new error conditions.

### Phase 2a tokens (additions)

New character class:

- `UNDERSCORE` — the ASCII code point U+005F (`_`)
- `IDENT_START` — `ALPHA` or `UNDERSCORE`
- `IDENT_CONT`  — `ALPHA`, `DIGIT`, or `UNDERSCORE`

New tokens:

| Token kind          | Rule                                                                                                                                                                                                                                             |
|---------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `KEYWORD_CREATE`    | `C R E A T E`, ASCII case-insensitive, NOT followed by `IDENT_CONT`.                                                                                                                                                                              |
| `KEYWORD_TABLE`     | `T A B L E`, ASCII case-insensitive, NOT followed by `IDENT_CONT`.                                                                                                                                                                               |
| `KEYWORD_INSERT`    | `I N S E R T`, case-insensitive, bounded.                                                                                                                                                                                                         |
| `KEYWORD_INTO`      | `I N T O`, case-insensitive, bounded.                                                                                                                                                                                                             |
| `KEYWORD_VALUES`    | `V A L U E S`, case-insensitive, bounded.                                                                                                                                                                                                         |
| `KEYWORD_FROM`      | `F R O M`, case-insensitive, bounded.                                                                                                                                                                                                             |
| `KEYWORD_INTEGER`   | `I N T E G E R`, case-insensitive, bounded.                                                                                                                                                                                                       |
| `KEYWORD_TEXT`      | `T E X T`, case-insensitive, bounded.                                                                                                                                                                                                             |
| `IDENTIFIER`        | One `IDENT_START` followed by zero or more `IDENT_CONT`. Carries a `name` field equal to the exact source substring (case-preserved). MUST NOT match a keyword (see precedence below).                                                           |
| `LPAREN`            | The single ASCII character `(`.                                                                                                                                                                                                                    |
| `RPAREN`            | The single ASCII character `)`.                                                                                                                                                                                                                    |
| `COMMA`             | The single ASCII character `,`.                                                                                                                                                                                                                    |
| `STAR`              | The single ASCII character `*`.                                                                                                                                                                                                                    |

### Keyword-vs-identifier precedence

When the tokenizer reads an `IDENT_START` followed by zero or more `IDENT_CONT`, it has a maximal word. If the word (matched case-insensitively, ASCII only) is one of the keywords listed above OR one of the Phase 1 keywords (`SELECT`, `NULL`), the token emitted is that keyword's kind. Otherwise the token is `IDENTIFIER` and its `name` field carries the word exactly as it appears in source (case preserved).

This rule subsumes the Phase 1 rule for `KEYWORD_SELECT` / `KEYWORD_NULL` — it is a strict generalisation, not a change.

### Phase 2a grammar

```
statement         := ( create-statement | insert-statement | select-statement )
                     [ SEMICOLON ] EOF

create-statement  := KEYWORD_CREATE KEYWORD_TABLE IDENTIFIER
                     LPAREN column-def ( COMMA column-def )* RPAREN
column-def        := IDENTIFIER column-type
column-type       := KEYWORD_INTEGER | KEYWORD_TEXT

insert-statement  := KEYWORD_INSERT KEYWORD_INTO IDENTIFIER
                     [ LPAREN IDENTIFIER ( COMMA IDENTIFIER )* RPAREN ]
                     KEYWORD_VALUES LPAREN signed-literal ( COMMA signed-literal )* RPAREN
signed-literal    := ( MINUS )? INTEGER_LITERAL | STRING_LITERAL | KEYWORD_NULL

select-statement  := KEYWORD_SELECT ( literal | projection KEYWORD_FROM IDENTIFIER )
projection        := STAR | IDENTIFIER ( COMMA IDENTIFIER )*
```

The Phase 1 `literal` production is unchanged.

**`signed-literal` semantics.** The `signed-literal` production appears only inside `INSERT VALUES (…)`. It yields a Value as follows:

- `INTEGER_LITERAL(v)` (no leading MINUS) → `Value::Integer(v)`. The tokenizer's existing `LEX_INTEGER_OVERFLOW` already rejects magnitudes outside `[0, 2^63 − 1]`, so `v` always fits in i64.
- `MINUS INTEGER_LITERAL(v)` → `Value::Integer(-v)`. Because `v ∈ [0, 2^63 − 1]`, the negated value lies in `[−(2^63 − 1), 0]`, which fits in i64 without overflow. The signed lower bound `i64::MIN = −2^63` is therefore NOT representable via `signed-literal` in Phase 3a; tests that need it must construct it via other means (deferred — would require widening the tokenizer's integer range to `[0, 2^63]` and adding a parser bounds check).
- `STRING_LITERAL(s)` → `Value::Text(s)`.
- `KEYWORD_NULL` → `Value::Null`.

No new `LEX_*` or `PARSE_*` error names are introduced. A bare `MINUS` followed by a non-`INTEGER_LITERAL` in INSERT VALUES produces `PARSE_UNEXPECTED_TOKEN` at the offending token's position with `expected = [INTEGER_LITERAL]`.

The disambiguation between `SELECT literal` (Phase 1 form) and `SELECT projection FROM …` (Phase 2a form) uses one-token lookahead after `SELECT`:

- If the next token is `STAR`, take the projection form.
- If the next token is `IDENTIFIER`, take the projection form.
- If the next token is `INTEGER_LITERAL`, `STRING_LITERAL`, or `KEYWORD_NULL`, take the literal form.
- Else: `PARSE_UNEXPECTED_TOKEN` with `expected = [STAR, IDENTIFIER, INTEGER_LITERAL, STRING_LITERAL, KEYWORD_NULL]`.

### Phase 2a error conditions — parser

The parser's only error kind remains `PARSE_UNEXPECTED_TOKEN`. Its `expected` field may now list Phase 2a token kinds. No new parser-level error names are introduced.

### Phase 2a semantics — execution

Phase 2a introduces stateful execution against in-memory storage. See `spec/storage.spec.md` for the storage data model, operations, and storage-level error conditions.

Every Phase 2a statement produces a Result conforming to `schema/result.schema.json`:

- `CREATE TABLE …`  — on success, produces `{"rows": []}`. Side-effect: a new empty table is stored in the database.
- `INSERT INTO … VALUES (…)` — on success, produces `{"rows": []}`. Side-effect: one new row is appended to the named table.
- `SELECT <literal>` (Phase 1 form) — on success, produces `{"rows": [[<value>]]}`. No side-effects. Identical to Phase 1.
- `SELECT * FROM <ident>` — on success, produces `{"rows": [ …rows in insertion order, columns in declared order ]}`.
- `SELECT <cols> FROM <ident>` — on success, produces `{"rows": [ …rows in insertion order, columns in the order named in `projection` ]}`.

If a statement's execution fails, the failure is one of the storage-level `STORAGE_*` error conditions defined in `spec/storage.spec.md`. Execution-level errors are carried through by the executor without introducing new names.

### Phase 2a non-goals (must not be implemented yet)

Implementing any of the following is a spec-discipline violation and a Phase 2a gate failure:

- WHERE, ORDER BY, LIMIT, OFFSET, GROUP BY, HAVING
- Any expression beyond a bare literal (no arithmetic, no string concat, no comparisons)
- UPDATE, DELETE
- Multiple statements per call (the grammar already forbids this via the trailing EOF)
- Quoted identifiers (`"x"`, `` `x` ``, `[x]`)
- Column constraints (`NOT NULL`, `PRIMARY KEY`, `DEFAULT …`)
- Schema alteration (`ALTER TABLE`, `DROP TABLE`)
- Table aliases, joins, subqueries
- Type affinity / implicit coercion
- VDBE bytecode (that is Phase 2b's job)

### Test authority (Phase 2a)

`tests/cross-build/phase2a.json` is the executable specification for Phase 2a. If this document and those tests disagree, the tests win.

---

## Phase 2b — VDBE compilation

Phase 2b changes how execution is implemented without changing what is executed. The Phase 1 + Phase 2a grammar, the Phase 2a execution semantics, and every observable error name and field remain identical. The new rule is that execution now flows through:

```
(AST, storage) → compiler.compile() → Program → vdbe.run(program, storage) → Result
```

instead of direct AST interpretation.

See `spec/vdbe-opcodes.spec.md` for the opcode ISA and `spec/vdbe-interpreter.spec.md` for the execution model. The compiler part (`parts/compiler/`) produces well-formed programs; the vdbe part (`parts/vdbe/`) interprets them.

### Phase 2b error-propagation guarantee

Every Phase 2a-visible error name / field combination continues to be emitted for the same SQL inputs under Phase 2b. The location in the pipeline MAY shift — for example, `STORAGE_COLUMN_NOT_FOUND` in a `SELECT b FROM t` (with no column `b`) is raised at compile time under Phase 2b (during schema resolution) rather than at execution time. The `name` and `fields` a test observes are identical; the internal stage differs.

Error precedence across the pipeline:

1. Tokenizer errors (`LEX_*`) — raised first.
2. Parser errors (`PARSE_UNEXPECTED_TOKEN`) — next.
3. Compiler errors (`STORAGE_TABLE_NOT_FOUND`, `STORAGE_COLUMN_NOT_FOUND`, `STORAGE_DUPLICATE_COLUMN` for schema-lookup failures) — next.
4. VDBE-runtime errors (any `STORAGE_*` from a storage op called by an opcode) — last.

A single SQL input's error surface picks the earliest applicable stage.

### Phase 2b non-goals

Beyond the Phase 2a non-goals, Phase 2b additionally forbids (any of these is a gate failure):

- Expressions beyond a bare literal (no arithmetic, no concat, no comparison) — deferred to Phase 2c
- WHERE, ORDER BY, LIMIT, GROUP BY, HAVING, OFFSET
- UPDATE, DELETE
- Index-based seek opcodes (only full scans via `OpRewind` + `OpNext` in 2b)
- JIT compilation, non-trivial register allocation, peephole optimisation
- On-disk file format / paging / WAL
- VDBE subroutines (single linear code path per program)

### Test authority (Phase 2b)

`tests/cross-build/phase2b.json` validates VDBE-specific behaviour via the compiler + vdbe parts directly. `tests/cross-build/phase2a.json` remains the full behavioural regression (executed via the Phase-2b-updated executor); it MUST stay green on every Phase 2b generation.

---

## Phase 2c-1 — expressions in SELECT projection

Phase 2c-1 introduces SQL expressions in the SELECT projection. The tokenizer gains arithmetic / comparison operators; the grammar gains recursive expressions with standard precedence; the AST is restructured to unify the SELECT forms. Execution introduces arithmetic, comparison, and new named error conditions. WHERE, UPDATE, DELETE remain out of scope (Phase 2c-2 / 2c-3).

### Phase 2c-1 tokens (additions)

| Token kind | Rule |
|---|---|
| `PLUS`  | The single ASCII character `+`. |
| `MINUS` | The single ASCII character `-`. |
| `SLASH` | The single ASCII character `/`. |
| `EQ`    | The single ASCII character `=`. |
| `NEQ`   | The two-character sequence `!=` OR the two-character sequence `<>`. Both spellings tokenize to the SAME kind `NEQ`; downstream (parser / compiler / VDBE) cannot distinguish which spelling was used. (SQL-89 standard alias; cross-corroboration pin 2026-04-18 — both C and Rust sqllogictest runner implementations flagged this gap.) |
| `LT`    | The single ASCII character `<`, NOT followed by `=` or `>`. |
| `LE`    | The two-character sequence `<=`. |
| `GT`    | The single ASCII character `>`, NOT followed by `=`. |
| `GE`    | The two-character sequence `>=`. |

Multi-character tokens follow maximal-munch: `<=` produces `LE`, not `LT` followed by `EQ`; `<>` produces `NEQ`, not `LT` followed by `GT`. At `<`, `>`, and `!`, the tokenizer peeks one character ahead. A bare `!` (not followed by `=`) raises `LEX_UNEXPECTED_CHARACTER` at the `!`'s position.

The existing `STAR` token (`*`) is **overloaded**: in projection-position following `SELECT` (with `FROM` immediately after), it means "all columns"; as an infix operator inside an expression, it means "multiplication". Disambiguation is at the grammar level (see below).

### Phase 2c-1 grammar

The `select-statement` production is replaced:

```
select-statement := KEYWORD_SELECT ( star-projection | expression-list [ KEYWORD_FROM IDENTIFIER ] )
star-projection  := STAR KEYWORD_FROM IDENTIFIER
expression-list  := expression ( COMMA expression )*
```

`expression` is a new recursive production with standard SQL precedence:

```
expression     := comparison
comparison     := additive [ cmp-op additive ]
cmp-op         := EQ | NEQ | LT | LE | GT | GE
additive       := multiplicative (( PLUS | MINUS ) multiplicative)*
multiplicative := unary (( STAR | SLASH | PERCENT ) unary)*
unary          := MINUS unary | primary
primary        := literal | IDENTIFIER | LPAREN expression RPAREN
```

Precedence high→low: parens, unary `-`, `* /`, `+ -`, comparison. Binary operators are left-associative. **Comparison does NOT chain**: `1 < 2 < 3` is a parse error after the second comparison attempt (`expected SEMICOLON or EOF or COMMA`).

The `IDENTIFIER` primary produces a `ColumnRef` expression; the compiler resolves the name at compile time against the table in scope.

### STAR-vs-multiplication disambiguation

When the parser sees `KEYWORD_SELECT` followed immediately by `STAR`:

- If the next-after-`STAR` token is `KEYWORD_FROM`, the parse takes the `star-projection` branch.
- Otherwise: `PARSE_UNEXPECTED_TOKEN` at the `STAR` position with `expected = [IDENTIFIER, INTEGER_LITERAL, STRING_LITERAL, KEYWORD_NULL, MINUS, LPAREN]`. A prefix `STAR` (multiplication with no left operand) is never a valid expression.

Once the parser has entered the `expression-list` branch, `STAR` inside an expression is always multiplication.

### Phase 2c-1 AST (restructuring)

The Phase 2a `SelectLiteral` and `SelectFrom` AST kinds are **retired and unified** into a single `Select` kind:

```
Select      := { kind: "Select", projection: Projection, table: string | null }
Projection  := { kind: "Star" } | { kind: "Expressions", expressions: Expression[] }
```

`Expression` is a new union used in projections (and, later phases, in WHERE / SET clauses):

```
Expression  := Literal | ColumnRef | BinaryOp | UnaryOp
ColumnRef   := { kind: "ColumnRef", name: string }
BinaryOp    := { kind: "BinaryOp", op: BinOp, left: Expression, right: Expression }
UnaryOp     := { kind: "UnaryOp",  op: "-",  operand: Expression }
BinOp       := "+" | "-" | "*" | "/" | "=" | "!=" | "<" | "<=" | ">" | ">="
```

Backward-compat check: Phase 1 `SELECT 42;` now parses as `Select(projection=Expressions([Literal(42)]), table=null)`; Phase 2a `SELECT a FROM t;` as `Select(projection=Expressions([ColumnRef("a")]), table="t")`; Phase 2a `SELECT * FROM t;` as `Select(projection=Star, table="t")`. Observable behaviour is unchanged for every Phase 1, 2a, 2b test.

### Phase 2c-1 evaluation semantics

Expressions evaluate to Values (integer / text / NULL).

**NULL propagation.** Every binary or unary operator with any NULL operand yields NULL in the destination. No error is raised for NULL operands.

**Integer arithmetic (`+ - * /`).** On two INTEGER operands, produces an INTEGER. Overflow is target-defined (two's-complement wrap is acceptable; trapping is acceptable; no named error is assigned). Integer division truncates toward zero (both operands are 64-bit signed).

**Division by zero.** `/` with a zero right operand (INTEGER 0) and a non-NULL left operand of INTEGER type evaluates to NULL. This matches mainline SQLite semantics: integer `x / 0` is not an error but yields NULL (SQLite-compat quirk; same rule applies to `x % 0` — see modulo section). Real division is unaffected (see "Arithmetic and type promotion" below): IEEE-754 governs `5.0 / 0` → `+inf`, etc. The error kind `EVAL_DIVISION_BY_ZERO` remains defined for symmetry across generators, but the integer-divide-by-zero trigger has been removed; the kind is retained because code paths elsewhere may still produce it (or may be unreached — treat as defense-in-depth, not live behaviour).

**Unary minus (`-`).** On INTEGER yields numeric negation. On NULL yields NULL. On TEXT raises `EVAL_TYPE_ERROR`.

**Arithmetic type errors.** `+`, `-`, `*`, `/` with any TEXT operand raises `EVAL_TYPE_ERROR`. Fields: `op` (one of `"+"`, `"-"`, `"*"`, `"/"`), `left_type`, `right_type` (each `"INTEGER"`, `"TEXT"`, or `"NULL"`).

**Comparison (`= != < <= > >=`).** Returns an INTEGER: `1` for true, `0` for false. Either-side NULL yields NULL (not false).

- INTEGER vs INTEGER: numeric comparison.
- TEXT vs TEXT: byte-by-byte lexicographic comparison (ASCII in Phase 2c-1).
- Mixed INTEGER / TEXT (either direction): raises `EVAL_TYPE_ERROR`. Fields: `op` (the comparison op name), `left_type`, `right_type`.

**Column references in no-FROM SELECT.** If `Select.table == null` and the projection contains any `ColumnRef`, the compiler raises `EVAL_COLUMN_WITHOUT_TABLE` at compile time. Fields: `column` (the referenced name).

### Phase 2c-1 new error conditions

- `EVAL_DIVISION_BY_ZERO` — VDBE-runtime. No fields. (Defined; retained for symmetry, but as of the SQLite-compat revision the integer `x/0` and `x%0` triggers yield NULL and no longer raise. The kind may remain unreachable in practice; keep the definition so generators do not diverge on enum shape.)
- `EVAL_TYPE_ERROR` — VDBE-runtime. Fields:
  - For binary ops: `op` (string), `left_type` (`"INTEGER"` / `"TEXT"` / `"NULL"`), `right_type` (same set).
  - For unary ops: `op` (always `"-"` in 2c-1), `operand_type` (`"INTEGER"` / `"TEXT"` / `"NULL"`).
- `EVAL_COLUMN_WITHOUT_TABLE` — compile-time. Fields: `column` (string).

These propagate through the VDBE and executor unchanged (same `name`, same `fields`).

### Error precedence (Phase 2c-1 addition)

In the overall pipeline the precedence becomes:

1. `LEX_*` (tokenizer)
2. `PARSE_UNEXPECTED_TOKEN` (parser)
3. `STORAGE_*` / `EVAL_COLUMN_WITHOUT_TABLE` (compiler; schema + scope resolution)
4. `STORAGE_*` / `EVAL_*` (VDBE runtime)

The earliest applicable stage wins.

### Phase 2c-1 non-goals

- Boolean operators `AND` / `OR` / `NOT` — deferred to Phase 2c-2
- WHERE clause — deferred to Phase 2c-2
- UPDATE / DELETE — deferred to Phase 2c-3
- String concatenation (`||`) — deferred
- `IS NULL` / `IS NOT NULL` — deferred
- `BETWEEN` / `LIKE` / `IN` — deferred
- Type coercion between INTEGER and TEXT — remains strict
- Expressions in `INSERT … VALUES` — deferred; INSERT values widened to `signed-literal` (a leading `MINUS` may prefix `INTEGER_LITERAL`) but full expressions (arithmetic, column refs, etc.) remain out of scope
- Qualified column references (`t.a`) — deferred
- Aliases (`SELECT a AS x`) — deferred

### Test authority (Phase 2c-1)

`tests/cross-build/phase2c1.json` is the executable specification for Phase 2c-1. Phase 1, 2a, 2b fixtures remain in force and MUST stay green.

---

## Phase 2c-2 — WHERE clause and logical operators

Phase 2c-2 layers row filtering on top of Phase 2c-1 expressions. The tokenizer gains one clause keyword (`WHERE`) and three logical-operator keywords (`AND`, `OR`, `NOT`). The grammar gains an optional `WHERE` clause on SELECT and extends the expression grammar with logical operators. Execution introduces four new opcodes, a truthiness convention, and SQL three-valued logic (3VL) for the logical operators.

### Phase 2c-2 tokens (additions)

| Token kind       | Rule |
|------------------|------|
| `KEYWORD_WHERE`  | `W H E R E`, case-insensitive, NOT followed by `IDENT_CONT`. |
| `KEYWORD_AND`    | `A N D`, case-insensitive, NOT followed by `IDENT_CONT`. |
| `KEYWORD_OR`     | `O R`, case-insensitive, NOT followed by `IDENT_CONT`. |
| `KEYWORD_NOT`    | `N O T`, case-insensitive, NOT followed by `IDENT_CONT`. |

These participate in the existing keyword-vs-identifier precedence rule (Phase 2a § "Keyword-vs-identifier precedence"): the case-insensitive words `where`, `and`, `or`, `not` are now reserved keywords and can no longer be used as `IDENTIFIER`.

### Phase 2c-2 grammar

The `select-statement` production gains an optional trailing `WHERE` clause that attaches to every form that has a `FROM`:

```
select-statement := KEYWORD_SELECT ( star-projection | expression-list [ from-and-where ] )
star-projection  := STAR from-and-where
from-and-where   := KEYWORD_FROM IDENTIFIER [ KEYWORD_WHERE expression ]
expression-list  := expression ( COMMA expression )*
```

The `expression` production is extended with three lower-precedence layers (logical-or below everything new; logical-and above or; logical-not above and; all still above the comparison layer from 2c-1):

```
expression     := logical-or
logical-or     := logical-and ( KEYWORD_OR  logical-and )*
logical-and    := logical-not ( KEYWORD_AND logical-not )*
logical-not    := KEYWORD_NOT logical-not | comparison
comparison     := additive [ cmp-op additive ]
...
```

Precedence high→low (full ladder after 2c-2): parens, unary `-`, `* /`, `+ -`, comparison, `NOT`, `AND`, `OR`. Binary logical operators are left-associative. `NOT` is right-associative (allowing `NOT NOT x`).

`WHERE` without a preceding `FROM` is a parse error: after a bare `SELECT expression-list`, the parser's only valid continuations remain `SEMICOLON`, `EOF`, `COMMA`, `KEYWORD_FROM` (see Phase 2c-1's expected-set rule). `KEYWORD_WHERE` at that position produces `PARSE_UNEXPECTED_TOKEN` with exactly that expected set.

### Phase 2c-2 AST changes

The `Select` AST kind gains an optional `where` field:

```
Select := { kind: "Select", projection: Projection, table: string | null, where: Expression | null }
```

`where` is `null` when the statement has no `WHERE` clause (every Phase 1, 2a, 2b, 2c-1 statement parses with `where: null`). It is present only when the grammar took the `KEYWORD_WHERE expression` branch of `from-and-where`.

The `BinOp` enum is extended with two logical operators:

```
BinOp := "+" | "-" | "*" | "/" | "=" | "!=" | "<" | "<=" | ">" | ">=" | "AND" | "OR"
```

The `UnaryOp` enum is extended with `NOT`:

```
UnaryOp := "-" | "NOT"
```

Thus `NOT x` parses as `UnaryOp(op="NOT", operand=x)`; `x AND y` parses as `BinaryOp(op="AND", left=x, right=y)`; `x OR y` as `BinaryOp(op="OR", ...)`.

### Phase 2c-2 evaluation semantics

**Truthiness.** A Value is:

- **TRUE** iff it is an `INTEGER` with a non-zero value.
- **FALSE** iff it is an `INTEGER` with value `0`.
- **UNKNOWN** iff it is `NULL`.
- A truthiness error iff it is `TEXT` (raises `EVAL_TYPE_ERROR`).

**WHERE clause.** For each row the cursor visits, evaluate `where` in the per-row register context. If the result is TRUE, include the row in the result; if FALSE or UNKNOWN, skip it; if TEXT, raise `EVAL_TYPE_ERROR` with `op = "WHERE"`, `operand_type = "TEXT"`. The standard Phase 2c-1 expression evaluation still applies inside the `WHERE` expression, so a sub-expression type error raises the usual arithmetic/comparison error shape (with that operator's `op`) — the WHERE-level error is only emitted when the top-level WHERE result itself is TEXT.

**Logical AND (SQL 3VL, no short-circuit on the error path).** Evaluates both operands always. Truth table (result value in the dest register):

| left \ right | TRUE (`1`) | FALSE (`0`) | NULL |
|---|---|---|---|
| TRUE  | `1` | `0` | NULL |
| FALSE | `0` | `0` | `0`  |
| NULL  | NULL | `0` | NULL |

Informal: AND yields FALSE if either operand is FALSE; TRUE if both are TRUE; NULL otherwise. Any TEXT operand raises `EVAL_TYPE_ERROR` with `op = "AND"`, `left_type`, `right_type`.

**Logical OR (SQL 3VL).** Evaluates both operands always. Truth table:

| left \ right | TRUE (`1`) | FALSE (`0`) | NULL |
|---|---|---|---|
| TRUE  | `1` | `1` | `1`  |
| FALSE | `1` | `0` | NULL |
| NULL  | `1` | NULL | NULL |

Informal: OR yields TRUE if either operand is TRUE; FALSE if both are FALSE; NULL otherwise. Any TEXT operand raises `EVAL_TYPE_ERROR` with `op = "OR"`, `left_type`, `right_type`.

**Logical NOT.** `NOT INTEGER 0 → 1`; `NOT INTEGER non-zero → 0`; `NOT NULL → NULL`; `NOT TEXT` raises `EVAL_TYPE_ERROR` with `op = "NOT"`, `operand_type = "TEXT"`.

**Non-short-circuit evaluation rule.** Both AND and OR evaluate their right operand even when the left operand has determined the result (e.g. `FALSE AND anything` still evaluates the right operand). This matches the Phase 2c-1 postorder expression-compilation strategy (evaluate all sub-expressions, then combine) and keeps the VDBE dispatch simple. A TEXT operand on the "ignored" side still raises the type error. A division-by-zero on the ignored side yields NULL under the SQLite-compat quirk (the row value is NULL, the AND/OR table handles NULL as documented; no error is raised). SQLite's real behavior short-circuits; later phases MAY introduce short-circuiting if it becomes observable to tests, but Phase 2c-2 does not.

### Phase 2c-2 new error conditions

No new error **names**. `EVAL_TYPE_ERROR` gains four new `op` values:

- `"AND"` (binary) — left_type, right_type
- `"OR"`  (binary) — left_type, right_type
- `"NOT"` (unary)  — operand_type
- `"WHERE"` (unary, semantically a truthiness coercion) — operand_type (always `"TEXT"` in practice)

`EVAL_DIVISION_BY_ZERO` is reachable from within a WHERE expression only via non-integer-divide paths (e.g., future cases may still emit it); integer `x/0` and `x%0` in WHERE yield NULL (which the WHERE gate treats as "not TRUE", i.e. the row is skipped). No field change.

### Phase 2c-2 non-goals

- `IS NULL` / `IS NOT NULL` — deferred
- `BETWEEN` / `LIKE` / `IN` — deferred
- Short-circuit evaluation of `AND` / `OR` — deferred
- UPDATE / DELETE — deferred to Phase 2c-3
- HAVING, GROUP BY, ORDER BY, LIMIT, OFFSET — deferred
- Qualified column references inside `WHERE` (`t.a`) — deferred (bare identifiers only, matching projection)
- `CASE` expressions — deferred

### Test authority (Phase 2c-2)

`tests/cross-build/phase2c2.json` is the executable specification for Phase 2c-2. Phase 1, 2a, 2b, 2c-1 fixtures remain in force and MUST stay green.

---

## Phase 2c-3 — UPDATE and DELETE

Phase 2c-3 introduces the two mutation statements SQL needs beyond INSERT: row-wise updates and deletes. Both accept an optional `WHERE` clause (reusing the Phase 2c-2 expression surface). Storage gains two mutation operations; the VDBE gains two opcodes; the compiler gains two recipes; no new error names are introduced.

### Phase 2c-3 tokens (additions)

| Token kind | Rule |
|------------|------|
| `KEYWORD_UPDATE` | `U P D A T E`, case-insensitive, bounded (NOT followed by `IDENT_CONT`). |
| `KEYWORD_DELETE` | `D E L E T E`, case-insensitive, bounded. |
| `KEYWORD_SET`    | `S E T`, case-insensitive, bounded. |

These reserve the identifiers `update`, `delete`, `set` (case-insensitive) — they can no longer be used as table or column names.

### Phase 2c-3 grammar

The top-level `statement` production gains two alternatives:

```
statement          := ( create-statement | insert-statement | select-statement
                      | update-statement | delete-statement ) [ SEMICOLON ] EOF

update-statement   := KEYWORD_UPDATE IDENTIFIER KEYWORD_SET
                      assignment ( COMMA assignment )*
                      [ KEYWORD_WHERE expression ]
assignment         := IDENTIFIER EQ expression

delete-statement   := KEYWORD_DELETE KEYWORD_FROM IDENTIFIER
                      [ KEYWORD_WHERE expression ]
```

The `expression` production is unchanged — the full Phase 2c-2 expression grammar (logical-or layer at the top) applies.

### Phase 2c-3 AST (additions)

Two new top-level AST kinds:

```
Update := { kind: "Update", table: string,
            assignments: [{column: string, value: Expression}],
            where: Expression | null }

Delete := { kind: "Delete", table: string, where: Expression | null }
```

`assignments` is a non-empty ordered list. Duplicate `column` names within the list (case-sensitive) are a compile-time error (`STORAGE_DUPLICATE_COLUMN`). The `value` in each assignment is an arbitrary `Expression` — including `ColumnRef` to reference the row's existing values (e.g. `SET x = x + 1`).

### Phase 2c-3 evaluation semantics

**UPDATE statement** walks the rows of `table` in insertion order. For each live row:

1. If `where` is present, evaluate it in the row's context (its `ColumnRef`s resolve to the current row's column values). If the result is NOT TRUE (i.e. it is `INTEGER 0`, NULL, or raises an error), skip this row. TRUE (INTEGER non-zero) means proceed. TEXT raises `EVAL_TYPE_ERROR` with `op = "WHERE"`, `operand_type = "TEXT"` (same shape as Phase 2c-2's WHERE gate).
2. For each assignment `(col_i, expr_i)` in list-order: evaluate `expr_i` in the CURRENT row's context (reading original column values — all assignments evaluate against the pre-update row snapshot, not against partially-updated state). Collect the resulting values.
3. Apply all collected `(col_i, value_i)` pairs atomically to the row — all updates to the row take effect together. Non-listed columns retain their existing values.
4. The `STORAGE_TYPE_MISMATCH` check happens per-assignment when writing back (a TEXT value written to an INTEGER column raises it; cross-build tests may exercise this). The check is at storage level and halts the whole statement on the first offending row × column (leftmost in list, earliest row in iteration order).

The UPDATE statement produces `{"rows": []}` on success. No columns, no rows — it is a mutation, not a query.

**DELETE statement** walks the rows of `table` in insertion order. For each live row:

1. If `where` is present, evaluate it as above. If not TRUE, skip. (WHERE absent = delete every row.)
2. Mark the row for deletion in storage. After the scan completes, the affected rows are not visible to any subsequent query.

DELETE produces `{"rows": []}` on success.

**Iteration mid-mutation.** The cursor walks live rows in insertion order. UPDATE mutates in place without altering row visibility, so the cursor's iteration is unaffected. DELETE marks the current row as tombstoned; the cursor's subsequent `Next` advances past the (now-tombstoned) current row to the next live row. The VDBE opcodes treat this transparently; storage's cursor abstraction handles the tombstone-skipping.

**Post-DELETE INSERT.** After a row has been deleted, a subsequent `INSERT` appends a new row to the end in the usual insertion-order position. The tombstone slot is NOT reused (simpler model; later disk-format phases may revisit for compaction). Insertion order still means "order of INSERT operations on live rows", so after `DELETE`, `INSERT`, a `SELECT * FROM t` returns the live pre-delete rows followed by the newly-inserted one.

### Phase 2c-3 compile-time checks

Performed in this precedence order (first match wins):

1. Table existence — `STORAGE_TABLE_NOT_FOUND`.
2. For UPDATE: each `column` in `assignments` must be a column of the table, checked left-to-right — `STORAGE_COLUMN_NOT_FOUND` on the first offending name.
3. For UPDATE: duplicate `column` names in `assignments` — `STORAGE_DUPLICATE_COLUMN` on the first repeated name (leftmost of the repeated pair).
4. For UPDATE and DELETE: `ColumnRef` resolution in `where` and (UPDATE only) in each `assignment.value` — `STORAGE_COLUMN_NOT_FOUND`, leftmost offending name in source-order traversal (assignments before WHERE; within each, in-order traversal of the expression tree).

`EVAL_COLUMN_WITHOUT_TABLE` is NOT raisable by UPDATE or DELETE at the AST level because both statements always have a table; a `ColumnRef` is therefore always resolvable against the table schema.

### Phase 2c-3 runtime error surface

Unchanged error names. UPDATE may raise, at VDBE runtime:

- `EVAL_TYPE_ERROR` — for any expression inside `where` or any `assignment.value`. Same shape as Phase 2c-1 / 2c-2.
- `EVAL_DIVISION_BY_ZERO` — defined but no longer triggered by integer `x/0` or `x%0` (those yield NULL). Retained for shape symmetry across generators; UPDATE's WHERE / assignment expressions follow the same SQLite-compat quirk.
- `STORAGE_TYPE_MISMATCH` — if a computed assignment value's type is incompatible with the column's declared type. Fields: `table`, `column`, `expected_type`, `got_type`.

DELETE may raise only the two `EVAL_*` errors from the WHERE expression; no storage error can arise (tombstoning a live row never fails).

### Phase 2c-3 non-goals

- `UPDATE ... FROM` (join in UPDATE) — deferred
- `DELETE ... USING` — deferred
- `UPDATE ... SET (col1, col2) = (...)` tuple form — deferred
- `RETURNING` clauses — deferred
- Ordered DELETE / LIMIT on DELETE — deferred
- Triggers (no Phase has them) — deferred
- Tombstone compaction / autovacuum — deferred (on-disk phase)
- Rowid reuse after delete — deferred

### Test authority (Phase 2c-3)

`tests/cross-build/phase2c3.json` is the executable specification for Phase 2c-3. Phase 1, 2a, 2b, 2c-1, 2c-2 fixtures remain in force and MUST stay green.

---

## Phase 6a — LIMIT and OFFSET

Phase 6a adds row-count capping to `SELECT`. Two new keywords, a small grammar extension, no new VDBE opcodes needed (the compiler lowers LIMIT/OFFSET to counter arithmetic + conditional jumps using existing opcodes).

### Phase 6a tokens (additions)

| Token kind       | Rule |
|------------------|------|
| `KEYWORD_LIMIT`  | `L I M I T`, case-insensitive, NOT followed by `IDENT_CONT`. |
| `KEYWORD_OFFSET` | `O F F S E T`, case-insensitive, NOT followed by `IDENT_CONT`. |

These participate in the keyword-vs-identifier precedence rule. The case-insensitive words `limit` and `offset` are reserved and may no longer be used as `IDENTIFIER`.

### Phase 6a grammar

The `select-statement` production gains an optional trailing `LIMIT` clause. LIMIT only attaches to forms with a `FROM` (it is meaningless on a FROM-less `SELECT literal`, which produces exactly one row by construction):

```
select-statement := KEYWORD_SELECT ( star-projection | expression-list [ from-and-where-limit ] )
star-projection  := STAR from-and-where-limit
from-and-where-limit := KEYWORD_FROM IDENTIFIER
                        [ KEYWORD_WHERE expression ]
                        [ KEYWORD_LIMIT INTEGER_LITERAL [ KEYWORD_OFFSET INTEGER_LITERAL ] ]
```

LIMIT and OFFSET accept only bare non-negative `INTEGER_LITERAL` tokens in Phase 6a (NOT `signed-literal`, NOT expressions). A negative LIMIT or OFFSET is a parse error (`PARSE_UNEXPECTED_TOKEN` at the `MINUS`). OFFSET without preceding LIMIT is a parse error.

The FROM-less `SELECT literal` form remains unchanged (no LIMIT allowed — the grammar simply never reaches a LIMIT-eligible position).

### Phase 6a semantics — execution

- **LIMIT `N`**: after all other filtering (WHERE), emit at most `N` rows. If fewer rows pass WHERE, all of them are emitted. `LIMIT 0` is legal and emits zero rows even if rows pass WHERE.
- **OFFSET `K`**: skip the first `K` rows that would otherwise be emitted (i.e. post-WHERE), then start emitting. Combined with LIMIT, OFFSET is applied BEFORE LIMIT's cap (standard SQL semantics: `LIMIT N OFFSET K` means "skip K then take N").
- **OFFSET without LIMIT**: not permitted by the grammar — a parse error as noted above.
- **Row ordering**: unchanged (insertion order). Phase 6a does not add ORDER BY; LIMIT without ORDER BY returns the first-by-insertion-order rows. This matches mainline SQLite's observable behaviour for tables without an explicit ORDER BY.

### Phase 6a compilation

The compiler lowers LIMIT `N` [OFFSET `K`] to a pre-loop register init + two in-loop checks, using only existing opcodes:

1. Allocate registers: `reg_remain = N`, `reg_skip = K` (default 0 if OFFSET absent), plus two constant-holding registers `reg_zero = 0` and `reg_one = 1` pre-loaded before the loop starts.
2. AFTER the WHERE gate passes (and BEFORE projection/ResultRow emission):
   - If `reg_skip > 0`: decrement `reg_skip`, `Next` the cursor, skip the rest of this row's body. **OFFSET is applied POST-WHERE — rows that fail WHERE do not consume the skip budget.** Pinned by the `limit-offset-with-where` test case in `phase6a.json`. A practical recipe given the existing ISA (no `JumpIfNonZero`, no `IsZero`): `JumpIfFalse reg_skip, <after-offset-block>` (falls through only while `reg_skip > 0`); inside the block, `Subtract reg_skip, reg_skip, reg_one`; then jump unconditionally past the rest of the row body. Unconditional jump is realised by `JumpIfFalse reg_zero, <target>` (always taken because `reg_zero` is `Integer(0)`). Exact opcode recipe is target-defined; the contract is that no row is emitted and no ResultRow runs while `reg_skip > 0` (pre-decrement).
3. After the OFFSET gate falls through, BEFORE emitting the ResultRow:
   - If `reg_remain == 0`: jump to Halt. (Realised via `JumpIfFalse reg_remain, <halt>`.)
   - Emit ResultRow.
   - Decrement `reg_remain` via `Subtract reg_remain, reg_remain, reg_one`.
   - If `reg_remain == 0` after decrement: jump to Halt (short-circuit rather than re-running the cursor for no benefit).

A compiler MAY combine the two `reg_remain` checks into one if it tracks the invariant carefully. The test suite only asserts observable row emissions; it does not peek into opcode sequences.

### Phase 6a error conditions

No new error names. The only new parse errors are narrow cases of `PARSE_UNEXPECTED_TOKEN`:

- `LIMIT` followed by a non-INTEGER_LITERAL token (including MINUS) → `PARSE_UNEXPECTED_TOKEN` at that token's position with `expected = [INTEGER_LITERAL]`.
- `OFFSET` same rule.
- `OFFSET` appearing without a preceding `LIMIT` clause → `PARSE_UNEXPECTED_TOKEN` at the OFFSET token; the expected set at that position is the set of tokens that would otherwise continue the statement (`SEMICOLON`, `EOF`).

### Phase 6a non-goals

- LIMIT on UPDATE / DELETE — deferred
- Expression-valued LIMIT (e.g. `LIMIT :p`) — deferred (no bind parameters yet)
- Signed-literal LIMIT (negative) — spec-rejected (parse error)
- `LIMIT a, b` (MySQL/SQLite alternate syntax for `LIMIT b OFFSET a`) — deferred
- ORDER BY — deferred (separate later phase)

### Test authority (Phase 6a)

`tests/cross-build/phase6a.json` is the executable specification for Phase 6a. All prior phase fixtures MUST stay green.

## Phase 6b — ORDER BY

Phase 6b adds deterministic row ordering to `SELECT`. Four new keywords, a grammar extension, and a small set of sorter-oriented VDBE opcodes (see `vdbe-opcodes.spec.md` § Phase 6b).

### Phase 6b tokens (additions)

| Token kind      | Rule |
|-----------------|------|
| `KEYWORD_ORDER` | `O R D E R`, case-insensitive, NOT followed by `IDENT_CONT`. |
| `KEYWORD_BY`    | `B Y`, case-insensitive, NOT followed by `IDENT_CONT`. |
| `KEYWORD_ASC`   | `A S C`, case-insensitive, NOT followed by `IDENT_CONT`. |
| `KEYWORD_DESC`  | `D E S C`, case-insensitive, NOT followed by `IDENT_CONT`. |

Keyword-vs-identifier precedence applies as before: the case-insensitive words `order`, `by`, `asc`, `desc` are reserved.

### Phase 6b grammar

The `select-statement`'s trailing clauses are extended to include ORDER BY, which sits BETWEEN WHERE and LIMIT:

```
select-statement := KEYWORD_SELECT ( star-projection | expression-list [ from-and-where-order-limit ] )
star-projection  := STAR from-and-where-order-limit
from-and-where-order-limit :=
    KEYWORD_FROM IDENTIFIER
    [ KEYWORD_WHERE expression ]
    [ KEYWORD_ORDER KEYWORD_BY order-by-list ]
    [ KEYWORD_LIMIT INTEGER_LITERAL [ KEYWORD_OFFSET INTEGER_LITERAL ] ]

order-by-list := order-by-term ( COMMA order-by-term )*
order-by-term := expression [ KEYWORD_ASC | KEYWORD_DESC ]
```

The `expression` in an `order-by-term` is the same production used in projections/WHERE (Phase 2c-1), so it may be an `IDENTIFIER` (column reference), a literal, a unary/binary op, or parenthesised. Direction is optional and defaults to `ASC`.

`ORDER BY` without `KEYWORD_BY` is a parse error (`PARSE_UNEXPECTED_TOKEN` at the token following `KEYWORD_ORDER`, with `expected = [KEYWORD_BY]`).

An empty `order-by-list` (e.g. `ORDER BY` followed immediately by `LIMIT`) is a parse error (`PARSE_UNEXPECTED_TOKEN` at the LIMIT/SEMICOLON/EOF token).

ORDER BY is only legal after a `FROM`. A FROM-less `SELECT literal` may not have ORDER BY (the grammar never reaches an ORDER-BY-eligible position).

### Phase 6b AST (additions)

The `Select` AST node gains an optional `order_by` field:

```
Ast::Select {
    projection,
    table,
    where_expr,
    order_by,         // NEW: Option<Vec<OrderByTerm>>
    limit,
    offset,
}

OrderByTerm {
    expr: Expression,
    direction: SortDirection,   // Asc | Desc, default Asc when omitted
}
```

Absent `ORDER BY` is encoded as `order_by: None` (or its language-equivalent absence marker). An empty list is NEVER a valid AST value — the parser must reject empty lists at parse time.

### Phase 6b semantics — execution

- ORDER BY sorts the rows that pass WHERE, BEFORE LIMIT/OFFSET apply. That is: the evaluation order is WHERE → ORDER BY → OFFSET → LIMIT.
- Each `order-by-term` is evaluated per-row against the same row scope used by WHERE / projection. The key values form a tuple `(k1, k2, …, kN)`. Rows are then sorted lexicographically by that tuple, with per-term direction.
- Comparison of two values for sort-key ordering:
  - NULL is less than any non-NULL. (NULLS FIRST for ASC; NULLS LAST for DESC — consistent with mainline.)
  - INTEGER vs INTEGER: numeric.
  - TEXT vs TEXT: byte-lexicographic (raw UTF-8 byte comparison; no collation other than BINARY).
  - INTEGER vs TEXT: INTEGER < TEXT (type order: NULL < INTEGER < TEXT).
- Sort is stable: rows comparing equal on every key preserve insertion order (i.e., the order in which they were emitted by the source scan).
- After sort, OFFSET skips from the sorted front; LIMIT caps the remaining tail. Both apply to the sorted rows, not the pre-sort rows.
- If no `ORDER BY`, behaviour is unchanged from Phase 6a (insertion order).

### Phase 6b compilation

The compiler lowers ORDER BY via the sorter opcode family (see `vdbe-opcodes.spec.md` § Phase 6b). The emitted shape is two loops:

1. **Accumulation loop** (first cursor pass): for every row that passes WHERE, evaluate the order-by key expressions, evaluate the projection expressions, and call `SorterInsert` with both. No `ResultRow` in this loop.
2. **`SorterSort`** after the accumulation loop.
3. **Drain loop** (second pass, over the sorter): re-emit each sorted row as a `ResultRow`, with LIMIT/OFFSET gates applied in the drain loop (not in the accumulation loop).

The drain loop's OFFSET/LIMIT gates work identically to Phase 6a, just over the sorter instead of the table cursor.

Key/value counts for the sorter are the number of ORDER BY terms and the number of projection outputs, respectively. A key expression that happens to also be in the projection is still counted separately in the sorter — the compiler does not attempt to deduplicate.

### Phase 6b error conditions

No new runtime error names. New parse errors are narrow cases of `PARSE_UNEXPECTED_TOKEN`:

- `ORDER` not followed by `BY` → `PARSE_UNEXPECTED_TOKEN` at the offending token, `expected = [KEYWORD_BY]`.
- `ORDER BY` with no terms → `PARSE_UNEXPECTED_TOKEN` at the next token, `expected = <expression-start-tokens>`.
- A direction token (`ASC`/`DESC`) appearing outside an `order-by-term` → the normal "unexpected token" applies in whatever context it's mis-placed.

At runtime, evaluating an order-by-term may raise `VDBE_TYPE_MISMATCH` in the same way WHERE does — e.g. `ORDER BY a + b` where `a` is text and `b` is integer raises the same error the arithmetic would. See Phase 2c-2 `error-arith-type-mismatch` precedent.

### Phase 6b non-goals

- `ORDER BY <integer-literal>` (referring to projection by position) — deferred to Phase 6ba.
- `COLLATE`, `NULLS FIRST`/`NULLS LAST` explicit syntax — deferred.
- ORDER BY in UPDATE/DELETE — deferred.
- ORDER BY with subqueries / compound SELECTs — deferred.
- Aggregate / GROUP BY — deferred to a later sub-phase.

### Test authority (Phase 6b)

`tests/cross-build/phase6b.json` is the executable specification for Phase 6b. All prior phase fixtures MUST stay green.

## Phase 6c — Aggregate functions (no GROUP BY)

Phase 6c adds four aggregate functions — `COUNT`, `SUM`, `MIN`, `MAX` — callable in SELECT projection. No GROUP BY, no HAVING yet (that's Phase 6d). `AVG` is deferred because it requires REAL-type support, not yet in scope.

### Phase 6c parsing — aggregate calls are NOT reserved keywords

Unlike ORDER/BY/ASC/DESC/LIMIT/OFFSET, the aggregate names are NOT promoted to distinct token kinds. Instead, an `IDENTIFIER` followed by `LPAREN` is parsed as a function-call production; the compiler then dispatches on the identifier text (case-insensitive) against the fixed set {`count`, `sum`, `min`, `max`}. Any other identifier used in call position is a compile-time `COMPILE_UNKNOWN_FUNCTION` error.

This avoids reserving four more words that users might want as column names. The tradeoff is that a malformed aggregate call (e.g., `COUNT` without parens in projection position) is parsed as a bare column reference, and the resulting error is `COMPILE_COLUMN_NOT_FOUND` rather than a syntax error — acceptable.

### Phase 6c grammar

The `expression` production gains one alternative:

```
expression := ... (unchanged alternatives) ... | function-call
function-call := IDENTIFIER LPAREN function-args RPAREN
function-args := STAR | expression
```

`STAR` as the argument is only valid for `COUNT(*)`; enforced at compile time. Other aggregate names require an `expression` argument.

Multi-argument calls (e.g., `FOO(a, b)`) are NOT in the 6c grammar. Zero-argument calls (`FOO()`) are NOT in the 6c grammar.

`function-call` is allowed in projection expressions. Aggregate calls are FORBIDDEN in WHERE and ORDER BY; this is enforced at compile time (not parse time) and raises `COMPILE_AGGREGATE_IN_NON_PROJECTION_CONTEXT`.

### Phase 6c AST

New expression alternative:

```
Expression::AggregateCall {
    kind: AggregateKind,      // Count | Sum | Min | Max
    arg: AggregateArg,        // Star (only for Count) | Expr(boxed Expression)
}

enum AggregateKind { Count, Sum, Min, Max }
enum AggregateArg { Star, Expr(<boxed Expression>) }
```

The parser emits a generic `FunctionCall { name: Identifier, arg: ... }` form during parsing, then the compiler (not the parser) lowers it to either an `AggregateCall` AST node or rejects it with `COMPILE_UNKNOWN_FUNCTION`. Generators MAY collapse this into a single parser-emitted `AggregateCall` if that's cleaner — the harness doesn't inspect the AST shape, only the observable execution.

### Phase 6c semantics

An SELECT is **aggregated** iff any of its projection expressions contains an `AggregateCall`. In an aggregated SELECT:

1. The scan runs once over WHERE-filtered rows. No ResultRow emitted per row.
2. Per row, each `AggregateCall` argument is evaluated, and the accumulator is updated per the rules below.
3. After the scan, each aggregate's final value is computed, then the projection is evaluated ONCE — with each `AggregateCall` substituted by its final value — to produce exactly ONE result row.
4. An aggregated SELECT always emits **exactly one row**, even if the input is empty.

Restrictions in an aggregated SELECT (enforced at compile time):

- A bare column reference (outside any aggregate call) in a projection expression is an error: `COMPILE_COLUMN_IN_AGGREGATED_SELECT_WITHOUT_GROUP_BY`. Example: `SELECT x, SUM(y) FROM t` is illegal in 6c (legal only in 6d once GROUP BY lands).
- `*` as a whole-row projection (`SELECT * FROM t`) is unchanged — it is not aggregated.
- `ORDER BY`, `LIMIT`, `OFFSET` are FORBIDDEN on aggregated SELECT in 6c (the result is one row; these clauses are degenerate and their semantics with GROUP BY belong to 6d). Violation: `COMPILE_AGGREGATE_WITH_ORDER_OR_LIMIT`.

### Aggregate semantics per kind

- **COUNT(*)**: counts every row that passed WHERE, regardless of column values (including all-NULL rows). Starts at `INTEGER(0)`. Increments by 1 per row. Final value: `INTEGER(N)`.
- **COUNT(expr)**: evaluates `expr`; if result is NULL, skips. Else increments. Starts at `INTEGER(0)`. Final value: `INTEGER(N)` where N is the non-NULL count. Empty input: `INTEGER(0)`.
- **SUM(expr)**: evaluates `expr`; if NULL, skips. Else, if acc is NULL, sets acc to the value; else integer-adds. Starts as NULL. Type rule: non-INTEGER argument values (TEXT) raise `VDBE_TYPE_MISMATCH` at the first such row. Empty input or all-NULL input: `NULL`.
- **MIN(expr)**: evaluates `expr`; if NULL, skips. Else, if acc is NULL, sets acc to the value; else updates acc to the smaller of acc and value using the same ordering as ORDER BY (INTEGER < TEXT, numeric within INTEGER, byte-lex within TEXT). Starts as NULL. Empty input or all-NULL input: `NULL`.
- **MAX(expr)**: symmetric to MIN with "larger of".

Rationale for mixed-type MIN/MAX: the ORDER BY ordering was already pinned in 6b and is the only well-defined total order over our type system. Using the same rule keeps the spec coherent.

### Phase 6c compilation

Compile-time analysis:

1. Walk each projection expression once, collecting all `AggregateCall` subexpressions. Assign each a 1-based ordinal `i` and an accumulator register `acc_i`.
2. Reject if the SELECT is aggregated AND any projection expression contains a bare column reference outside any aggregate call.
3. Reject if ORDER BY / LIMIT / OFFSET is present on an aggregated SELECT.

Code emission (aggregated path):

```
(1)  Initialize accumulators:
       For COUNT or COUNT(*): LoadConst acc_i = Integer(0)
       For SUM/MIN/MAX:        LoadConst acc_i = Null
(2)  Scan loop:
       OpenRead c, table
       Rewind c, jump_if_empty = POST_LOOP
       LOOP_TOP:
         [WHERE gate, unchanged from Phase 2c-2]
         For each AggregateCall i (left-to-right projection order):
           If arg is Star:
             AggStep acc_i, kind=CountStar, arg_reg=ignored
           Else:
             [emit code to evaluate arg into reg_arg_i]
             AggStep acc_i, kind=<Count|Sum|Min|Max>, arg_reg=reg_arg_i
         Next c, jump_if_more = LOOP_TOP
       POST_LOOP:
         Close c
(3)  Finalize:
       For each AggregateCall i:
         AggFinal acc_i, kind=<Count|CountStar|Sum|Min|Max>, dest=reg_final_i
(4)  Emit projection using reg_final_i in place of each AggregateCall,
     then ResultRow.
(5)  Halt.
```

For COUNT(*) with the same `kind` field as COUNT but a distinct `Star` argument shape, implementations MAY choose whether to use one AggStep kind (`Count`) with a per-step "always increment" flag, or a separate `CountStar` kind. The spec uses `CountStar` as the opcode-level kind to keep the AggStep handler branch-free per kind. This is reflected in `vdbe-opcodes.spec.md` § Phase 6c.

For a mix of aggregate kinds in the same projection (e.g. `SELECT COUNT(*), SUM(x), MIN(x) FROM t`), the compiler emits one AggStep per aggregate inside the same loop body. Execution is `O(rows × aggregates)` per step, which is the expected shape.

### Phase 6c error conditions

New compile-time errors (raised during the compile pass; surfaced as `{"error": {"name": "...", "fields": {...}}}`):

- `COMPILE_UNKNOWN_FUNCTION { name: <text> }` — an IDENTIFIER in function-call position whose (lowercased) name is not in `{count, sum, min, max}`.
- `COMPILE_AGGREGATE_ARG_MISMATCH { function: <NAME>, reason: "star-only-for-count" | "expression-required" }` — e.g. `SUM(*)` or `MIN()`. The `function` field is the UPPERCASE canonical name (`"SUM"`, `"MIN"`, `"MAX"`, `"COUNT"`) regardless of how the user wrote it. This contrasts with `COMPILE_UNKNOWN_FUNCTION.name`, which preserves the user's original casing (since the function is unknown, there IS no canonical form). Cross-corroboration pin from Phase 6c dual-regen: both generators saw the ambiguity and resolved differently; spec now mandates uppercase for canonical, case-preserved for unknown.
- `COMPILE_COLUMN_IN_AGGREGATED_SELECT_WITHOUT_GROUP_BY { column: <name> }` — a bare column at projection scope in an aggregated SELECT.
- `COMPILE_AGGREGATE_IN_NON_PROJECTION_CONTEXT { location: "where" | "order-by" }` — an aggregate call in WHERE or ORDER BY.
- `COMPILE_AGGREGATE_WITH_ORDER_OR_LIMIT { clause: "order-by" | "limit" | "offset" }` — aggregated SELECT with any of those clauses.

Runtime errors reuse existing names (`VDBE_TYPE_MISMATCH` on SUM over a TEXT argument, etc.).

### Phase 6c non-goals

- `AVG` — deferred until REAL-type support lands.
- `GROUP BY` / `HAVING` — deferred to Phase 6d.
- `DISTINCT` inside aggregate calls (`COUNT(DISTINCT x)`) — deferred.
- Aggregate calls in subqueries — deferred (no subqueries yet).
- Function-call syntax for non-aggregate functions (e.g. `LENGTH(x)`) — deferred.
- ORDER BY / LIMIT on aggregated SELECT — spec-rejected (single-row result).

### Test authority (Phase 6c)

`tests/cross-build/phase6c.json` is the executable specification for Phase 6c. All prior phase fixtures MUST stay green.

## Phase 6d — GROUP BY and HAVING

Phase 6d adds `GROUP BY <expression-list>` and `HAVING <expression>` to aggregated SELECT. It also removes the Phase 6c restriction forbidding ORDER BY / LIMIT / OFFSET on aggregated SELECT — with GROUP BY producing multiple group-rows, these clauses make sense.

### Phase 6d tokens (additions)

| Token kind       | Rule |
|------------------|------|
| `KEYWORD_GROUP`  | `G R O U P`, case-insensitive, NOT followed by `IDENT_CONT`. |
| `KEYWORD_HAVING` | `H A V I N G`, case-insensitive, NOT followed by `IDENT_CONT`. |

`KEYWORD_BY` is already reserved (Phase 6b). Two new reserved words in this phase: `group`, `having`.

### Phase 6d grammar

The `select-statement`'s trailing clauses grow to include GROUP BY (after WHERE, before ORDER BY) and HAVING (immediately after GROUP BY):

```
from-and-where-group-having-order-limit :=
    KEYWORD_FROM IDENTIFIER
    [ KEYWORD_WHERE expression ]
    [ KEYWORD_GROUP KEYWORD_BY expression-list ]
    [ KEYWORD_HAVING expression ]
    [ KEYWORD_ORDER KEYWORD_BY order-by-list ]
    [ KEYWORD_LIMIT INTEGER_LITERAL [ KEYWORD_OFFSET INTEGER_LITERAL ] ]

expression-list := expression ( COMMA expression )*
```

`HAVING` without a preceding `GROUP BY` is a parse error: `PARSE_UNEXPECTED_TOKEN` at the HAVING token.

`GROUP` not followed by `BY` is a parse error: `PARSE_UNEXPECTED_TOKEN` at the offending token, `expected = [KEYWORD_BY]`.

An empty GROUP BY list (e.g. `GROUP BY` followed immediately by ORDER BY, HAVING, LIMIT, SEMICOLON, or EOF) is a parse error.

### Phase 6d AST (additions)

```
Ast::Select {
    projection,
    table,
    where_expr,
    group_by,         // NEW: Option<Vec<Expression>>
    having,           // NEW: Option<Expression>
    order_by,
    limit,
    offset,
}
```

Absent GROUP BY / HAVING is `None` in both.

### Phase 6d semantics — grouped aggregated SELECT

When an SELECT is aggregated AND has GROUP BY:

1. WHERE filters input rows (unchanged).
2. Rows are PARTITIONED by GROUP-BY-key tuple. Each partition is a "group".
3. For each group, evaluate all aggregate calls over its rows. Evaluate all non-aggregate projection expressions using the group-key values (each bare column reference must be in GROUP BY keys).
4. If HAVING is present, evaluate it for each group using the group's aggregate + group-key context. Groups where HAVING evaluates to TRUE are kept; others dropped (including NULL results per SQL 3VL).
5. The surviving groups form the pre-ORDER-BY rowset. ORDER BY / LIMIT / OFFSET apply on top, in the usual order.

An aggregated SELECT WITHOUT GROUP BY continues to emit exactly one row (Phase 6c behaviour unchanged).

### Phase 6d compile-time checks

For an aggregated SELECT WITH GROUP BY:

- Every bare column reference in the projection MUST be one of the GROUP BY key expressions (equivalence by AST-shape match on a bare-column-reference; more complex expressions like `a + 1` in GROUP BY matching `a + 1` in projection is supported via the same AST match).  Violation: `COMPILE_COLUMN_NOT_IN_GROUP_BY { column: <name> }`.
- Every bare column reference in HAVING MUST be either a GROUP BY key expression or inside an aggregate call. Violation: same error name.
- Aggregate calls inside HAVING are allowed (HAVING is explicitly a post-aggregation filter). Aggregate calls inside GROUP BY expressions are FORBIDDEN: `COMPILE_AGGREGATE_IN_NON_PROJECTION_CONTEXT { location: "group-by" }`.
- Aggregate calls inside WHERE remain forbidden (unchanged from 6c).
- The Phase 6c rejection of ORDER BY / LIMIT / OFFSET on aggregated SELECT is LIFTED when GROUP BY is present. An aggregated SELECT without GROUP BY retains the Phase 6c restriction (`COMPILE_AGGREGATE_WITH_ORDER_OR_LIMIT`).
- If GROUP BY is present but no aggregate calls appear in projection/HAVING, the SELECT is still considered aggregated — each group emits one row whose projection values are the group-key values (or any GROUP-BY-bound expressions). This is standard SQL.

### Phase 6d compilation recipe

Informal sketch (exact opcode sequence is target-defined — the harness tests observable row emissions only):

1. Open sorter 0 configured with `key_count = |GROUP BY keys|`, `direction_mask = 0` (ASC — any stable direction works since grouping only needs partitioning). Values stored per-row are those needed to evaluate the aggregates + project bare group-key values (the compiler chooses the minimal register layout).
2. Scan loop: WHERE gate, then for each passing row, evaluate group-by key expressions and aggregate-argument expressions, `SorterInsert` into sorter 0.
3. `SorterSort sorter=0`.
4. Drain loop over sorter 0 with explicit group-break detection:
   - Initialize "previous group key" registers from the first row (special-case when sorter is empty: no groups at all — emit zero rows and jump to the post-all-groups stage).
   - Initialize accumulators from the first row.
   - For each subsequent sorter row: compare current group keys (via `SorterReadKey` — see `vdbe-opcodes.spec.md` § Phase 6d) to previous keys. If equal, `AggStep` the aggregates using the row's values and continue. If different, **emit the previous group** (see step 5), then reset accumulators and previous-key registers, and step the current row into the fresh group.
   - After the sorter is exhausted, **emit the final pending group**.
5. "Emit group" sub-routine:
   - `AggFinal` each aggregate into its projection register.
   - Bare group-key values come from the previous-key registers.
   - Evaluate HAVING (if present) using those registers. If HAVING is not TRUE (FALSE or NULL), skip the emission.
   - If ORDER BY is present, `SorterInsert` into sorter 1 (configured for ORDER BY). Otherwise emit `ResultRow` directly (still subject to LIMIT/OFFSET if those apply — which only happens without ORDER BY in this case).
6. If ORDER BY is present: after all groups are processed, `SorterSort` sorter 1 and drain it with `SorterRead` + `ResultRow` + LIMIT/OFFSET gates (identical to Phase 6b's ORDER BY drain).
7. Halt.

The number of sorters a Phase 6d program uses is:
- 0, if not aggregated and no ORDER BY (unchanged from 6a);
- 1, if aggregated + GROUP BY but no ORDER BY (group-sorter);
- 1, if ORDER BY but not aggregated or aggregated-without-GROUP-BY (Phase 6b shape);
- 2, if aggregated + GROUP BY + ORDER BY.

### Phase 6d error conditions

New compile-time errors:

- `COMPILE_COLUMN_NOT_IN_GROUP_BY { column: <name> }` — a bare column in projection or HAVING that is not a GROUP BY key.
- `COMPILE_HAVING_WITHOUT_GROUP_BY` — HAVING on a non-aggregated or no-GROUP-BY SELECT (in our 6d scope, HAVING requires GROUP BY).
- `COMPILE_AGGREGATE_IN_NON_PROJECTION_CONTEXT { location: "group-by" }` — aggregate call in GROUP BY keys.

Reused:
- `COMPILE_AGGREGATE_IN_NON_PROJECTION_CONTEXT { location: "where" }` — as in 6c.
- `COMPILE_AGGREGATE_WITH_ORDER_OR_LIMIT { clause }` — now fires only when aggregated WITHOUT GROUP BY.

Runtime errors unchanged from 6c.

### Phase 6d non-goals

- GROUP BY by ordinal / integer literal position — deferred.
- `ROLLUP`, `CUBE`, `GROUPING SETS` — deferred.
- `DISTINCT` inside aggregate calls — deferred.
- Window functions — deferred.
- AVG — still deferred until REAL lands.

### Test authority (Phase 6d)

`tests/cross-build/phase6d.json` is the executable specification for Phase 6d. All prior phase fixtures MUST stay green.

## Phase 6e — JOINs (INNER, LEFT)

Phase 6e adds two-table joins: `INNER JOIN ... ON ...` (or just `JOIN ... ON ...`) and `LEFT JOIN ... ON ...` (or `LEFT OUTER JOIN ... ON ...`). Two-table only in 6e scope; multi-table joins are straightforward to generalise later but deferred.

Joins are compiled as naive nested-loop joins — no query planner, no index use. The outer table is the first listed; the inner is the second.

### Phase 6e tokens (additions)

| Token kind       | Rule |
|------------------|------|
| `KEYWORD_JOIN`   | `J O I N`, case-insensitive, NOT followed by `IDENT_CONT`. |
| `KEYWORD_INNER`  | `I N N E R`, case-insensitive, NOT followed by `IDENT_CONT`. |
| `KEYWORD_LEFT`   | `L E F T`, case-insensitive, NOT followed by `IDENT_CONT`. |
| `KEYWORD_OUTER`  | `O U T E R`, case-insensitive, NOT followed by `IDENT_CONT`. |
| `KEYWORD_ON`     | `O N`, case-insensitive, NOT followed by `IDENT_CONT`. |
| `DOT`            | `.` — qualified column reference separator. |

5 new reserved keywords, 1 new punctuation token. The words `join`, `inner`, `left`, `outer`, `on` are reserved.

### Phase 6e grammar

The `from-and-where-...` production gains optional join-suffixes after the initial table name:

```
from-clause := KEYWORD_FROM table-ref ( join-clause )*
table-ref   := IDENTIFIER                                        -- single table (in 6e: no aliases yet)
join-clause :=
    ( KEYWORD_INNER KEYWORD_JOIN
    | KEYWORD_JOIN                                               -- plain JOIN = INNER JOIN
    | KEYWORD_LEFT [ KEYWORD_OUTER ] KEYWORD_JOIN )
    table-ref KEYWORD_ON expression
```

`ON` is required in 6e (no `NATURAL JOIN`, no `USING`, no comma-joins / cross-joins).

The `expression` production grows one alternative for qualified column references:

```
expression := ... | qualified-column
qualified-column := IDENTIFIER DOT IDENTIFIER
```

`qualified-column` denotes `<table-name> DOT <column-name>`. In joined queries, unqualified `IDENTIFIER` column references remain legal IF the column name is unambiguous (present in exactly one joined table). Ambiguous unqualified references raise `COMPILE_AMBIGUOUS_COLUMN { column: <name> }`.

### Phase 6e AST

```
enum FromSource {
    SingleTable { name: ... },
    Joined {
        left: <boxed FromSource>,           -- left side (itself may be Joined — left-deep tree)
        join_kind: JoinKind,                -- Inner | Left
        right_table: ...,                   -- single table only in 6e
        on: Expression,
    }
}

enum JoinKind { Inner, Left }

enum Expression {
    ...existing...,
    QualifiedColumn { table: <text>, column: <text> }
}

Ast::Select {
    projection,
    from: FromSource,                        -- was `table: String`, now FromSource
    where_expr,
    group_by,
    having,
    order_by,
    limit,
    offset,
}
```

Generators MAY internally keep `FromSource::SingleTable` for backwards-compat of the existing single-table path; as long as the observable behaviour is unchanged, nothing in the prior fixtures needs to differ.

### Phase 6e semantics

INNER JOIN: produces the cross product of outer × inner filtered by the ON expression. A row from the outer table that matches zero inner rows is not emitted.

LEFT JOIN: produces the INNER JOIN result, plus for each outer row that matched ZERO inner rows, emits one row where all inner-side columns are NULL.

ON expression evaluation: uses SQL 3VL — a NULL ON result is treated as FALSE for filtering (row not emitted for INNER; counted as "no match" for LEFT).

Column reference resolution:
- A bare `IDENTIFIER` in WHERE / ORDER BY / projection / HAVING / GROUP BY binds to whichever joined table has a column of that name, IF unambiguous; otherwise `COMPILE_AMBIGUOUS_COLUMN`.
- A `qualified-column` binds to the named table's column; error if the table isn't in scope (`COMPILE_TABLE_NOT_IN_SCOPE { table }`) or the column isn't on that table (`COMPILE_COLUMN_NOT_FOUND { table, column }`).

`*` projection on a joined SELECT expands to the concatenation of all joined tables' columns in FROM-clause order.

### Phase 6e compilation

Naive nested loop — no new VDBE opcodes are needed. The existing `OpenRead`, `Rewind`, `Next`, `Column`, `Close` suffice. New compile-time complexity is entirely in register allocation (two cursor contexts) and conditional gates.

Two-table INNER JOIN recipe:

```
OpenRead c0, outer_table
OpenRead c1, inner_table
Rewind c0, jump_if_empty = END
OUTER_LOOP:
  Rewind c1, jump_if_empty = INNER_EXHAUSTED_NO_MATCH  -- or for INNER, just continue to INNER_NEXT
  INNER_LOOP:
    [evaluate ON expression over c0.cols + c1.cols into reg_cond]
    JumpIfFalse reg_cond, AFTER_INNER_BODY
    [evaluate WHERE and/or projection over c0.cols + c1.cols]
    [WHERE gate]
    ResultRow ...
  AFTER_INNER_BODY:
    Next c1, INNER_LOOP
  Next c0, OUTER_LOOP
END:
  Close c1
  Close c0
  Halt
```

LEFT JOIN adds a "saw-any-match" scratch register. The inner-loop body, when it passes the ON filter, sets that register to `Integer(1)`. After the inner loop exhausts, if the register is still `Integer(0)`, emit a ResultRow with inner-side columns replaced by `Null`. The register is reset at the start of each outer-row iteration.

Integration with GROUP BY / HAVING / ORDER BY / LIMIT / aggregates is unchanged in shape — those clauses run on the projected rows, and the earlier phases' recipes still apply with the join just feeding more rows.

Phase 6e deliberately keeps the opcode set unchanged. This is the cleanest cross-check of whether our opcode design generalises.

### Phase 6e error conditions

New compile-time errors:

- `COMPILE_AMBIGUOUS_COLUMN { column: <name> }` — unqualified column name that exists on multiple joined tables.
- `COMPILE_TABLE_NOT_IN_SCOPE { table: <name> }` — qualified column whose table isn't a joined source.

`COMPILE_COLUMN_NOT_FOUND` (which already existed since Phase 2b as `ERR_COMPILE_UNKNOWN_COLUMN` or similar — generators reuse their existing name; fixture uses the string `"COMPILE_COLUMN_NOT_FOUND"`) now fires for qualified references too, with `{ table, column }` fields rather than just `{ column }`.

Runtime errors unchanged.

### Phase 6e non-goals

- Three-or-more-table joins — deferred.
- `CROSS JOIN`, `NATURAL JOIN`, `USING (col)` — deferred.
- `RIGHT JOIN`, `FULL OUTER JOIN` — deferred.
- Table aliases (`FROM t AS x`, `FROM t x`) — deferred.
- Self-joins (same table on both sides) — deferred (requires alias support to disambiguate).
- Index-backed join algorithms — deferred.

### Test authority (Phase 6e)

`tests/cross-build/phase6e.json` is the executable specification for Phase 6e. All prior phase fixtures MUST stay green.

## Phase 6f — SELECT DISTINCT

Phase 6f adds the `DISTINCT` quantifier to SELECT. One new keyword, one grammar extension, compile-time shape change; reuses Phase 6b sorter and Phase 6d `SortValueEq` / `Jump` opcodes for the dedup drain.

### Phase 6f tokens (additions)

| Token kind        | Rule |
|-------------------|------|
| `KEYWORD_DISTINCT`| `D I S T I N C T`, case-insensitive, NOT followed by `IDENT_CONT`. |

### Phase 6f grammar

The `select-statement` prefix grows an optional quantifier immediately after `SELECT`:

```
select-statement := KEYWORD_SELECT [ KEYWORD_DISTINCT ] select-body
```

Legal positions for the quantifier:
- Before any projection form (`STAR` or expression-list).
- Before any FROM clause.

An explicit `KEYWORD_ALL` (the SQL default) is NOT supported in 6f (parse error on `SELECT ALL ...`). Only DISTINCT adds a token; absence defaults to ALL semantically.

`DISTINCT` on an aggregated SELECT (e.g. `SELECT DISTINCT COUNT(*) FROM t`) is legal but degenerate — the result is one row either way, so DISTINCT is a no-op there. We accept the syntax for consistency.

### Phase 6f AST

`Ast::Select` grows `distinct: bool` (default false). The flag is set iff the `KEYWORD_DISTINCT` token appeared.

### Phase 6f semantics

For a SELECT with `DISTINCT`:

1. All prior phases run as usual: FROM → (joins) → WHERE → GROUP BY / HAVING → projection expression evaluation — producing the same rowset a non-DISTINCT SELECT would produce.
2. The projected rowset is deduplicated. Two projection rows are considered EQUAL iff, for every projected value, the pair compares equal under sort-order equality (NULL == NULL yields EQUAL; cross-type is UNEQUAL as the sort order defines).
3. ORDER BY, LIMIT, OFFSET apply on the deduplicated rowset.

Formally: DISTINCT filters the pre-ORDER-BY rowset to retain exactly one representative per projection-equivalence-class. The representative is the FIRST occurrence in the pre-DISTINCT iteration order (for stable semantics; relevant when DISTINCT is combined with ORDER BY, where the dedup happens BEFORE the ORDER BY sort).

### Phase 6f compilation recipe

The compiler lowers DISTINCT by:

1. Routing projection-result rows through a sorter (call it `dedup_sorter`) keyed by all projection values. Direction is ASC on every key (arbitrary — the dedup scan only needs adjacent-equal grouping). `value_count` is 0 (we don't need to store anything besides the keys, since keys ARE the row).
2. Calling `SorterSort dedup_sorter` after the pre-dedup pipeline completes.
3. Draining the sorter with a group-break-style loop that emits the key as a result row only when it differs from the previous key:
   - Load first row's keys into prev-regs; emit it. Subsequent: load current keys, compare to prev via `SortValueEq` + `And` chain, emit only if different, copy current to prev.

Interaction with ORDER BY: DISTINCT's sort already produces an ORDER — if that order happens to match the ORDER BY, the compiler MAY elide the second sort. For 6f, generators are NOT required to optimise this — emitting the two sorters independently is compliant. Observable behaviour is identical.

**Cross-corroboration pin (Phase 6f dual-regen):** ORDER BY terms on a DISTINCT SELECT may only reference projected expressions. Both 6f generators hit this and resolved identically: each ORDER BY term is matched by AST-shape equality against a projection slot; the ORDER BY sort then reads from the corresponding dedup-sorter key register. For `SELECT DISTINCT *`, ORDER BY may reference any column of the single FROM table (expanded as part of `*`). Arbitrary post-dedup expressions over projected values (e.g. `ORDER BY x + 1` when the projection is just `x`) are NOT required in Phase 6f — targets MAY raise `COMPILE_UNSUPPORTED_FEATURE` or evaluate the expression using the projected slot values; test fixtures exercise only shape-matched ORDER BY terms.

Interaction with GROUP BY: the grouped-aggregated pipeline produces one row per group; DISTINCT then dedups the group-result rows. Emission goes through TWO sorters (group-by's + distinct's), and an ORDER BY would add a third.

Interaction with LIMIT/OFFSET: applied AFTER DISTINCT (and AFTER ORDER BY, if present).

No new VDBE opcodes. The dedup scan uses `SorterReadKey` (6d), `SortValueEq` (6d), `And` (2c-2), `JumpIfFalse` (2c-2), `Copy` (6d), and the existing sorter lifecycle opcodes.

### Phase 6f error conditions

No new errors. Reuses:

- `PARSE_UNEXPECTED_TOKEN` on invalid grammar positions.
- The Phase 6c aggregate rules still apply (e.g. bare col in aggregated-no-GROUP-BY SELECT still rejected even with DISTINCT).

### Phase 6f non-goals

- `DISTINCT` inside aggregate calls (`COUNT(DISTINCT x)`) — deferred. This needs per-aggregate dedup machinery; not in 6f scope.
- `ALL` keyword as the explicit "not DISTINCT" form — deferred.
- UNION / INTERSECT / EXCEPT — deferred (these are compound SELECTs, a separate phase).

### Test authority (Phase 6f)

`tests/cross-build/phase6f.json` is the executable specification for Phase 6f. All prior phase fixtures MUST stay green.

## Phase 6g — REAL type

Phase 6g adds IEEE-754 double-precision floating-point as a third storage and result type alongside INTEGER and TEXT. This is the biggest type-system extension since Phase 1. It touches the tokenizer, value representation, comparison/arithmetic, aggregate semantics, CREATE TABLE type parsing, and the on-disk serialization (SQLite serial type 7).

### Phase 6g tokens (additions)

| Token kind      | Rule |
|-----------------|------|
| `FLOAT_LITERAL` | A decimal numeric with either (a) a `.` somewhere, or (b) an `e`/`E` exponent. Syntax: `( DIGIT+ "." DIGIT* | "." DIGIT+ | DIGIT+ ) ( [eE] [+-]? DIGIT+ )?` — with the constraint that if neither `.` nor exponent is present, the token is an `INTEGER_LITERAL` instead. A bare `.` (no digits) is not a FLOAT_LITERAL. |
| `KEYWORD_REAL`    | `R E A L`, case-insensitive, not followed by IDENT_CONT. |
| `KEYWORD_FLOAT`   | `F L O A T`, case-insensitive, not followed by IDENT_CONT. |
| `KEYWORD_DOUBLE`  | `D O U B L E`, case-insensitive, not followed by IDENT_CONT. |

The three type-label keywords are accepted as equivalent in CREATE TABLE column-type positions (see below). `real`, `float`, `double` become reserved words — no column named any of them.

Tokenizer disambiguation: at the start of a number lexeme, read digits; if you hit a `.` or `e/E`, it's a FLOAT_LITERAL (consume the rest per the regex above); else it's an INTEGER_LITERAL. `1e5`, `1.5`, `.5`, `1.5e-3` are FLOAT_LITERALs. `-5.3` is `MINUS` + `FLOAT_LITERAL(5.3)` — signed is grammar-level via `signed-literal`, same convention as negatives for INTEGER_LITERAL.

The token's numeric value is parsed as `f64` at tokenize time per Rust/C `strtod`-equivalent rules. A literal that doesn't fit in `f64` (overflows to infinity) is still accepted as `+inf`/`-inf` — these are legal `f64` bit patterns. NaN cannot arise from a literal (no syntax produces NaN from source). Underflow to `0.0` is implicit.

### Phase 6g grammar

`signed-literal` is extended to include FLOAT_LITERAL:

```
signed-literal := ( MINUS )? ( INTEGER_LITERAL | FLOAT_LITERAL )
                | STRING_LITERAL | KEYWORD_NULL
```

`primary-expression` gains `FLOAT_LITERAL` as a literal alternative alongside `INTEGER_LITERAL`.

`column-type` (in CREATE TABLE) gains the three new type-label tokens:

```
column-type := KEYWORD_INTEGER | KEYWORD_TEXT | KEYWORD_REAL | KEYWORD_FLOAT | KEYWORD_DOUBLE
```

`REAL`, `FLOAT`, and `DOUBLE` are treated as three spellings of the same column type. Internally, the schema canonicalises to `REAL` (uppercase) — matches mainline SQLite's CREATE TABLE type affinity rule for "REAL"/"FLOA"/"DOUB" substrings. When emitting `sqlite_schema.sql` for round-trip compatibility, the declared label MAY be the original user-typed spelling preserved verbatim (mainline is lenient on this).

### Phase 6g Value / Literal (AST + runtime)

```
Literal ::= ... | Real(f64)
Value   ::= Null | Integer(i64) | Real(f64) | Text(String)
```

Order axioms for the comparison total order used by ORDER BY / SortValueEq / MIN / MAX / group-by-key equality:

- `NULL < Real < Integer < Text`. But: Real and Integer compare NUMERICALLY across types, not by type-tag. Specifically: between two numeric values (Integer/Real mixed), compare their numeric values using `f64` comparison semantics EXCEPT when both are Integer, in which case integer comparison is used (no precision loss). The effective rule is: to compare `a` numeric and `b` numeric, if both are Integer, compare as i64; else compare as f64 (promoting any Integer to f64).
- NaN values: not producible from literals, but can arise from arithmetic (`0.0 / 0.0`). When a NaN enters the comparison engine, treat it as distinctly GREATER than any non-NaN Real and EQUAL to other NaNs. This is a simplifying convention — SQL standard is under-specified here.

In short for the spec table:
  `cmp(Null, x)` = -1 for any non-Null x; `cmp(x, Null)` = +1.
  `cmp(Text, Text)` = byte-lex.
  `cmp(Text, Integer|Real)` = +1; `cmp(Integer|Real, Text)` = -1.
  `cmp(Integer, Integer)` = i64 compare.
  `cmp(Real, Real)` = f64 compare (with the NaN rule above).
  `cmp(Integer, Real)` = compare as f64 (promote int to f64).
  `cmp(Real, Integer)` = symmetric.

### Arithmetic and type promotion

Binary arithmetic (`+`, `-`, `*`, `/`):
- Integer op Integer → Integer (as before). Division: truncation toward zero. Integer divide-by-zero (`/` or `%` with a non-NULL integer left operand and INTEGER 0 right operand) evaluates to NULL (SQLite-compat quirk — mainline SQLite returns NULL for `5/0` and `5%0`). Real division uses IEEE.
- Real op Real → Real (IEEE 754 semantics; divide-by-zero → `+inf`/`-inf`/`NaN` as per IEEE — no error).
- Integer op Real (or Real op Integer) → Real. The Integer operand is converted to f64 first. Division by zero: same as Real op Real.
- Mixed with NULL: result is NULL (existing rule).
- Mixed with Text: `VDBE_TYPE_MISMATCH { operation, kind: "<non-numeric kind>" }` (existing rule applies to REAL the same way).

Unary minus (`Negate`): preserve type. `-Integer(5)` → `Integer(-5)`; `-Real(5.5)` → `Real(-5.5)`. `-Integer(i64::MIN)` continues to raise `VDBE_INTEGER_OVERFLOW` (existing).

### Aggregates (6c kinds extended)

- **SUM**: accumulator stays NULL until the first non-NULL input. On first input, acc takes that input's type (Integer or Real). Subsequent inputs:
  - Integer + Integer → Integer.
  - Real + Real → Real.
  - Integer + Real (either order) → Real (acc is promoted to Real on first Real input, remains Real thereafter; subsequent Integer inputs promote per-op).
  - Text input → `VDBE_TYPE_MISMATCH` (existing rule).
  - Integer overflow during summation: raises `VDBE_INTEGER_OVERFLOW` (existing rule — we don't auto-promote to Real).
- **MIN / MAX**: cross-type comparison per the order axioms above. Returned value retains its original type (no promotion).
- **COUNT / COUNT(*)**: unchanged.

### CREATE TABLE column-type coercion on INSERT

Existing 6a/6b/6c/6d/6e semantics: INSERT values must match column type OR NULL. Phase 6g keeps this strict, extended:

- Column declared `INTEGER`: accepts Integer + NULL. Rejects Real and Text with `STORAGE_TYPE_MISMATCH { column, expected, got }`.
- Column declared `TEXT`: accepts Text + NULL. Rejects Integer and Real.
- Column declared `REAL` / `FLOAT` / `DOUBLE`: accepts Real + NULL. ALSO accepts Integer (promoted to Real on store). This matches mainline SQLite's REAL affinity: INTEGER values inserted into REAL columns are converted.
- Rejections raise `STORAGE_TYPE_MISMATCH` as before.

When reading back, a REAL column always yields Value::Real (even if it was originally stored from an Integer literal).

### On-disk serialization — SQLite serial type 7

Records (rows) encode each value with a serial type header followed by payload. Existing targets: serial type 0 (NULL), serial types 1–6 (varint-length INTEGER), serial types 12+2k (BLOB), 13+2k (TEXT). Phase 6g enables:

- **Serial type 7**: 8-byte IEEE 754 big-endian double-precision float. Payload is exactly 8 bytes.

Encoding on write: when emitting a record for a Value::Real, write `0x07` as the serial-type varint and 8 bytes big-endian payload.

Encoding on read: when the serial-type varint is 7, read 8 bytes big-endian, decode as f64, yield Value::Real.

Round-trip requirement: mainline-written Real values MUST be read correctly; our-written Real values MUST be read correctly by mainline. A new round-trip fixture exercises this (see "Test authority").

### Phase 6g non-goals

- `AVG` aggregate — deferred to **Phase 6h** (small follow-up phase; adds one aggregate kind using the existing Sum+Count machinery at finalise time).
- `NUMERIC` affinity rules — not implemented (we stay strict).
- Infinity / NaN literal syntax — deferred.
- `CAST(... AS REAL)` expression — deferred.
- SUM auto-promotion to Real on integer overflow — rejected (we raise error instead; simpler).

### Test authority (Phase 6g)

`tests/cross-build/phase6g.json` is the executable specification for Phase 6g engine behaviour. `tests/cross-build/roundtrip_real.py` (new) exercises bidirectional on-disk compatibility for REAL columns between leap-c / leap-rust / mainline sqlite3. All prior phase fixtures MUST stay green.

## Phase 6h — AVG aggregate

Phase 6h adds the AVG aggregate function, now unlocked by Phase 6g's Real type. No new tokens (AVG is an IDENTIFIER in function-call position, per Phase 6c's convention). One new `AggregateKind`, extending the existing `AggStep` / `AggFinal` opcode handlers.

### Phase 6h grammar

Unchanged from 6c. The parser already accepts `IDENTIFIER LPAREN expression RPAREN`; the compiler's `resolve_agg_name` lookup now accepts `avg` (case-insensitive) in addition to `count`, `sum`, `min`, `max`.

### Phase 6h AST

`AggregateKind` gains an `Avg` variant. Argument validation: AVG requires an `expression` argument (not STAR), same as SUM/MIN/MAX. `AVG(*)` raises `COMPILE_AGGREGATE_ARG_MISMATCH { function: "AVG", reason: "star-only-for-count" }` — reuse the existing error.

### Phase 6h semantics

AVG(expr) for an aggregated SELECT:

- Empty input or all-NULL input: AVG returns `NULL`.
- Otherwise: AVG returns `sum_of_non_null_inputs / count_of_non_null_inputs` as a `Real` value (always Real, never Integer — even if all inputs are Integer).
- TEXT input to AVG raises `VDBE_TYPE_MISMATCH { operation: "avg", kind: "TEXT" }`.
- Integer-only input: AVG returns a Real — e.g. `AVG(1, 2, 3)` = `Real(2.0)`, `AVG(1, 2)` = `Real(1.5)`.

### Phase 6h opcode change — `AggregateKind::Avg` paired-register convention

No new opcode. The existing `AggStep { acc_reg, kind: Avg, arg_reg }` and `AggFinal { acc_reg, kind: Avg, dest }` gain an implicit PAIRED-REGISTER convention:

- `acc_reg` holds the running sum (Real, or Null initially).
- `acc_reg + 1` holds the running count (Integer, initialised to 0 by the compiler with a `LoadConst`).
- On `AggStep { kind: Avg }`:
  - If `regs[arg_reg]` is Null → no-op.
  - Else if `regs[arg_reg]` is Text → `VDBE_TYPE_MISMATCH { operation: "avg", kind: "TEXT" }`.
  - Else the input is Integer or Real. Convert to f64. If `regs[acc_reg]` is Null, set it to `Real(v)`; else add v to the Real value already there. Increment `regs[acc_reg + 1]` by 1.
- On `AggFinal { kind: Avg }`:
  - If `regs[acc_reg + 1]` is `Integer(0)` → `regs[dest] = Null`.
  - Else → `regs[dest] = Real(regs[acc_reg].as_f64() / regs[acc_reg + 1].as_i64() as f64)`.

Compilers allocate two consecutive registers for each AVG. The compiler also emits `LoadConst acc_reg = Null` and `LoadConst acc_reg + 1 = Integer(0)` in the aggregate-init phase.

### Well-formedness extensions (Phase 6h)

Invariants 1–23 remain. Phase 6h adds:

- **New 24.** For every `AggStep` or `AggFinal` with `kind: Avg`: `acc_reg + 1 < num_registers`. The count register at `acc_reg + 1` is implicitly claimed and MUST NOT be used by any other AggStep/AggFinal with a different `acc_reg`. (Compilers naturally allocate consecutively — the invariant catches malformed programs.)

### Phase 6h error conditions

- Reused: `COMPILE_UNKNOWN_FUNCTION` (never fires for AVG now), `COMPILE_AGGREGATE_ARG_MISMATCH` (for `AVG(*)`), `VDBE_TYPE_MISMATCH` (for Text input).
- No new error names.

### Phase 6h non-goals

- `AVG` over mixed TEXT+numeric with graceful skip — rejected; we error on first TEXT.
- `AVG(DISTINCT x)` — deferred with other DISTINCT-in-aggregates.

### Test authority (Phase 6h)

`tests/cross-build/phase6h.json` is the executable specification for Phase 6h. All prior phase fixtures MUST stay green.

## Phase 6i — CAST expression

Phase 6i adds the SQL-standard `CAST(expression AS type)` expression. Two new reserved keywords (`CAST`, `AS`), one new grammar production (`cast-expr`), one new VDBE opcode (`Scalar` — see `vdbe-opcodes.spec.md` § Phase 6i) with three cast-kind variants. Scalar function calls (LENGTH, ABS, UPPER, ...) are NOT in this phase — deferred to Phase 6j.

### Phase 6i tokens (additions)

| Token kind        | Rule |
|-------------------|------|
| `KEYWORD_CAST`    | `C A S T`, case-insensitive, NOT followed by `IDENT_CONT`. Reserved. |
| `KEYWORD_AS`      | `A S`, case-insensitive, NOT followed by `IDENT_CONT`. Reserved. |

Both keywords are RESERVED from Phase 6i onward — a column or table named `cast` or `as` raises `PARSE_UNEXPECTED_TOKEN` with `kind: KEYWORD_CAST` / `KEYWORD_AS`, mirroring the REAL/FLOAT/DOUBLE reservation pinned in 6g.

**VARCHAR is deliberately NOT a reserved keyword** — it remains an `IDENTIFIER` at the tokenizer level. Phase 2a's `parse-error-unknown-column-type` fixture depends on `VARCHAR` surfacing as `PARSE_UNEXPECTED_TOKEN { kind: IDENTIFIER }` in `CREATE TABLE` context; reserving VARCHAR would break that frozen fixture. The `cast-type` production below accepts VARCHAR by matching an `IDENTIFIER` token whose text is `"varchar"` case-insensitively, NOT a `KEYWORD_VARCHAR` token. (Cross-corroboration pin: Phase 6i dual-regen confirmed both C and Rust generators independently reach this resolution when given the Phase 2a fixture as a hard constraint.)

### Phase 6i grammar

```
cast-expr := KEYWORD_CAST LPAREN expression KEYWORD_AS cast-type RPAREN
cast-type := KEYWORD_INTEGER | KEYWORD_REAL | KEYWORD_FLOAT | KEYWORD_DOUBLE | KEYWORD_TEXT | IDENTIFIER("varchar")

// IDENTIFIER("varchar") means: an IDENTIFIER token whose text equals "varchar" (case-insensitive ASCII).
// VARCHAR is NOT a reserved keyword — see "Phase 6i tokens (additions)" above for rationale.
```

`cast-expr` is a valid `expression` production — it slots in wherever an expression is accepted: projection, WHERE, ORDER BY key, HAVING, INSERT VALUES, aggregate argument, CAST argument (nestable).

Parser precedence: `KEYWORD_CAST LPAREN` is a peek-ahead cue. When the parser sees `CAST` at the start of a primary expression, it commits to the cast-expr production; anything other than `LPAREN` after it is `PARSE_UNEXPECTED_TOKEN`.

### Phase 6i AST

```
Expr::Cast { expr: Box<Expr>, to_kind: CastTargetKind }
CastTargetKind ∈ { Integer, Real, Text }
```

Alias keywords collapse in the AST: `INTEGER` → `Integer`; `REAL`/`FLOAT`/`DOUBLE` → `Real`; `TEXT`/`VARCHAR` → `Text`. The source keyword is NOT preserved in the AST.

### Phase 6i semantics — evaluation

Let `v` be the runtime value of the inner expression. `CAST(v AS T)` evaluates as:

- **`v = Null`** → `Null`, regardless of `T`.
- **`T = Integer`**:
  - `Integer(i)` → `Integer(i)` (identity).
  - `Real(r)` → `Integer(trunc(r))` with truncation toward zero. If `r` is `NaN`, `+inf`, `-inf`, or `trunc(r)` falls outside `[i64::MIN, i64::MAX]` → `VDBE_CAST_OVERFLOW { from_kind: "Real", to_kind: "Integer" }`.
  - `Text(s)` → longest-valid-prefix integer parse. Grammar of the prefix: optionally a single `-` or `+`, then one or more ASCII digits (`0`–`9`). Zero digits consumed → result `Integer(0)` (lenient — NOT an error). Nonzero digit prefix: interpret as base-10 signed integer; overflow beyond `i64` range → `VDBE_CAST_OVERFLOW { from_kind: "Text", to_kind: "Integer" }`. Whitespace is NOT trimmed.
- **`T = Real`**:
  - `Integer(i)` → `Real(i as f64)`. Exact for `|i| ≤ 2^53`; silent round-to-nearest-even for larger magnitudes (no error).
  - `Real(r)` → `Real(r)` (identity — `NaN`, `±inf` preserved).
  - `Text(s)` → longest-valid-prefix real parse following the FLOAT_LITERAL grammar from Phase 6g (optional sign, digits with optional `.` and/or `e`/`E` exponent with optional sign and one or more digits). Zero characters consumed → `Real(0.0)`. If the parsed prefix represents a value that overflows f64 to `+inf` or `-inf` → `VDBE_CAST_OVERFLOW { from_kind: "Text", to_kind: "Real" }`. Denormal / subnormal results accepted without error.
- **`T = Text`**:
  - `Integer(i)` → `Text(s)` where `s` is the minimal ASCII decimal representation: `-?[0-9]+` with no leading zeros except `0` itself (so `CAST(0 AS TEXT)` → `"0"`, `CAST(-5 AS TEXT)` → `"-5"`).
  - `Text(s)` → `Text(s)` (identity).
  - `Real(r)` → **deferred to Phase 6j** (requires a pinned floating-point-to-string format to guarantee C/Rust bit-identical output; skipped to avoid cross-language divergence in 6i). The `Scalar { kind: CastText }` opcode raises `VDBE_UNSUPPORTED_CAST { from_kind: "Real", to_kind: "Text" }` at runtime when the input is a Real value. `CAST(NULL AS TEXT)` remains `Null`; `CAST(<integer-expr> AS TEXT)` remains supported.

### Phase 6i error conditions

- **`PARSE_UNEXPECTED_TOKEN`** (reused): malformed `cast-expr` — missing `LPAREN`, `KEYWORD_AS`, or `RPAREN`; unrecognized `cast-type` keyword; using `CAST` or `AS` as a column/table identifier.
- **`VDBE_CAST_OVERFLOW { from_kind, to_kind }`** (NEW): (a) Real→Integer where `r` is non-finite or `trunc(r)` is outside i64 range; (b) Text→Integer where the parsed digit prefix overflows i64; (c) Text→Real where the parsed value overflows f64 to ±inf. Carries the source and target kind as snake_case strings (`"Real"`, `"Integer"`, `"Text"`) — same spelling as `VDBE_TYPE_MISMATCH.kind`.
- **`VDBE_UNSUPPORTED_CAST { from_kind, to_kind }`** (NEW): Real→Text, raised at runtime by `Scalar { kind: CastText }` when the input is a Real value. Reserved name for future phases that may add additional unsupported-cast scenarios.

### Phase 6i non-goals

- Real→Text conversion — Phase 6j (needs a pinned shortest-round-trip format).
- Scalar function calls (LENGTH, UPPER, LOWER, ABS, ROUND, SUBSTR, TRIM, ...) — Phase 6j.
- CAST to type names outside the six listed (e.g. `BOOLEAN`, `BLOB`, `NUMERIC`) — deferred.
- Whitespace-trimming of text-to-numeric CAST — deferred; we are strict.
- `NUMERIC` affinity — permanently non-goal.

### Test authority (Phase 6i)

`tests/cross-build/phase6i.json` is the executable specification for Phase 6i. All prior phase fixtures MUST stay green.

## Phase 6j — Scalar functions (LENGTH, ABS)

Phase 6j adds two scalar functions — `LENGTH` and `ABS` — to prove the scalar-function dispatch infrastructure with both a string-domain function and a numeric-domain function. No grammar additions (reuses the existing `IDENTIFIER LPAREN (STAR | expression) RPAREN` function-call shape from Phase 6c). One new compile-time error (`COMPILE_UNKNOWN_FUNCTION`), one new error for STAR-in-scalar (`COMPILE_SCALAR_ARG_MISMATCH`). Extends the `Scalar` opcode's `ScalarKind` enum with `Length` and `Abs`.

### Phase 6j tokens

Unchanged. `LENGTH` and `ABS` are IDENTIFIERS (reserved-keyword machinery stays for CAST/AS/REAL/FLOAT/DOUBLE only). This preserves the ability to have columns named `length` or `abs` in non-function-call positions — same convention as aggregates (`count`, `sum`, `min`, `max`, `avg` are all IDENTIFIERS).

### Phase 6j grammar

Unchanged. The function-call production from Phase 6c is reused:

```
function-call := IDENTIFIER LPAREN ( STAR | expression ) RPAREN
```

### Phase 6j compile-time dispatch

The compiler resolves `IDENTIFIER LPAREN expression RPAREN` function calls by case-insensitive name lookup:

1. **Aggregate names** (`count`, `sum`, `min`, `max`, `avg`): unchanged — compile as aggregate.
2. **Scalar names** (Phase 6j adds `length`, `abs`): compile as `Scalar { kind: <ScalarKind>, arg_reg, dest }` with:
   - `length` → `ScalarKind::Length`
   - `abs` → `ScalarKind::Abs`
3. **Unknown names**: raise `COMPILE_UNKNOWN_FUNCTION { name: "<UPPERCASE_NAME>" }`. Name is uppercased for error reporting (matches the `COMPILE_AGGREGATE_ARG_MISMATCH.function` convention pinned in 6c).

STAR handling: if the parser produces `STAR` as the function argument, the compiler checks:
- For `COUNT(*)`: existing CountStar path (unchanged).
- For any other function name (aggregate or scalar, known or unknown): raise error.
  - If name is a known aggregate other than COUNT: `COMPILE_AGGREGATE_ARG_MISMATCH { function, reason: "star-only-for-count" }` (existing).
  - If name is a known scalar: `COMPILE_SCALAR_ARG_MISMATCH { function, reason: "star-not-allowed" }` (NEW).
  - If name is unknown: precedence is `COMPILE_UNKNOWN_FUNCTION` (unknown-ness detected before STAR-argument validation — STAR just passes through until we know the function category).

Argument-count handling: both LENGTH and ABS take exactly one argument in Phase 6j. The existing function-call grammar enforces exactly one `expression` argument (no support for multi-arg function calls yet). Multi-arg functions are deferred to a later phase that introduces comma-separated argument lists in the grammar.

### Phase 6j semantics — evaluation

Let `v` be the runtime value of the single argument.

**`LENGTH(v)`**:
- `Null` → `Null`.
- `Text(s)` → `Integer(n)` where `n` is the count of UTF-8 CODE POINTS in `s`. For ASCII-only strings, this equals the byte count. For multi-byte UTF-8, count only the bytes that are NOT UTF-8 continuation bytes (i.e. bytes in the range `0x80..=0xBF`). Implementation: `n = bytes.iter().filter(|b| (*b & 0xC0) != 0x80).count()`. Invalid UTF-8 sequences are still counted by the same rule (no error raised — we count leading bytes).
- `Integer(_)` → `VDBE_TYPE_MISMATCH { operation: "length", kind: "Integer" }`.
- `Real(_)` → `VDBE_TYPE_MISMATCH { operation: "length", kind: "Real" }`.

**`ABS(v)`**:
- `Null` → `Null`.
- `Integer(i)` → `Integer(|i|)`. If `i == i64::MIN` → `VDBE_INTEGER_OVERFLOW` (reused existing error; no new name).
- `Real(r)` → `Real(|r|)`. IEEE 754 `fabs`: `NaN` stays `NaN`; `-inf` → `+inf`; `-0.0` → `+0.0` (or `0.0`, target-defined canonicalisation of zero signs; tests do not distinguish).
- `Text(_)` → `VDBE_TYPE_MISMATCH { operation: "abs", kind: "Text" }`.

### Phase 6j error conditions

- **`COMPILE_UNKNOWN_FUNCTION { name }`** (NEW): function-call name is neither an aggregate nor a scalar in the current phase. `name` is the UPPERCASE form of the identifier (ASCII uppercase of each byte).
- **`COMPILE_SCALAR_ARG_MISMATCH { function, reason }`** (NEW): scalar function called with STAR argument. `function` is uppercase. Only defined value of `reason` in Phase 6j is `"star-not-allowed"`.
- **`VDBE_TYPE_MISMATCH { operation, kind }`** (reused): wrong-typed argument at runtime. `operation` values added: `"length"`, `"abs"`. `kind` is the source value's type tag (`"Integer"`, `"Real"`, `"Text"`).
- **`VDBE_INTEGER_OVERFLOW`** (reused): `ABS(i64::MIN)`.

### Phase 6j non-goals

- Multi-argument functions (e.g. `SUBSTR(s, start, length)`, `ROUND(x, digits)`) — deferred; requires grammar extension for comma-separated argument lists and a `Scalar2` opcode family (or relaxation of `Scalar`).
- String functions beyond `LENGTH`: `UPPER`, `LOWER`, `TRIM`, `REPLACE`, `SUBSTR` — deferred to Phase 6k.
- Numeric functions beyond `ABS`: `ROUND`, `CEIL`, `FLOOR` — deferred to Phase 6k.
- Real→Text CAST (the 6i deferral) — still deferred; orthogonal to this phase.
- `LENGTH` on a BLOB value returning byte count — no BLOB type yet.
- Lenient coercion (e.g. `LENGTH(123)` returning `3` by stringifying the integer) — explicitly rejected; we are strict and raise `VDBE_TYPE_MISMATCH`.

### Test authority (Phase 6j)

`tests/cross-build/phase6j.json` is the executable specification for Phase 6j. All prior phase fixtures MUST stay green.

### Phase 6j retroactive spec amendments — pinned by cross-corroboration

The Phase 6j dual-regen surfaced two spec gaps where both the C and Rust generators independently invented the same workaround in order to pass fixtures. Per the cross-corroboration rule, the spec is pinned to the converged behavior.

**Amendment 1 — STRING_LITERAL accepts non-ASCII bytes (UTF-8 passthrough).**

The Phase 1 STRING_LITERAL rule ("zero or more characters where each is either a non-`SQUOTE` character...") was ambiguous on whether "character" meant an ASCII code point or an arbitrary byte. The Phase 1 evaluation note on line 115 further narrowed: "Phase 1 assumes ASCII-only input." Phase 6j fixtures `'café'` and `'中'` force the issue — both contain bytes outside `0x00..=0x7F`.

Pinned resolution: **inside a STRING_LITERAL body, any byte other than `SQUOTE` is legal** — the tokenizer MUST NOT raise `LEX_UNEXPECTED_CHARACTER` for bytes `0x80..=0xFF` inside the quoted body. The body bytes are stored verbatim as the STRING_LITERAL's `value` (no UTF-8 validation, no normalization). The `SQUOTE SQUOTE` escape remains the only in-body transformation. `LEX_UNEXPECTED_CHARACTER` still fires for non-ASCII bytes OUTSIDE string literals (where Phase 1's ASCII assumption still holds for identifiers, keywords, and numeric literals).

Consequence: `LENGTH('中')` returns `1` (one UTF-8 code point), and the stored Text value for `'café'` has 5 bytes / 4 code points. This matches the `LENGTH` semantics in the Phase 6j evaluation table.

**Amendment 2 — INSERT VALUES accepts full `expression`, not just `signed-literal`.**

The Phase 3a grammar pinned `insert-statement := ... KEYWORD_VALUES LPAREN signed-literal ( COMMA signed-literal )* RPAREN`. The Phase 6i CAST section noted in passing that "cast-expr slots in wherever an expression is accepted — projection, WHERE, ORDER BY key, HAVING, INSERT VALUES, aggregate argument, CAST argument" but did not formally amend the 3a production. Phase 6j fixtures `INSERT INTO t VALUES (0 - 3)` and `INSERT INTO t VALUES (0 - 9223372036854775807 - 1)` (the only way to construct `i64::MIN` without enlarging the tokenizer's integer range) force the widening.

Pinned resolution: `insert-statement` values accept full `expression` productions:

```
insert-statement := KEYWORD_INSERT KEYWORD_INTO IDENTIFIER
                   [ LPAREN IDENTIFIER ( COMMA IDENTIFIER )* RPAREN ]
                   KEYWORD_VALUES LPAREN expression ( COMMA expression )* RPAREN
```

The `signed-literal` production is retained for documentary reference (and as a reasoning aid for the Phase 3a expected-token-set in the `expected` construction table) but is no longer the grammar frame for INSERT VALUES from Phase 6i onward. The Phase 3a `expected` set for the "value-start" position broadens accordingly — it now matches the full expression-start set (from phase 2c2, `[INTEGER_LITERAL, STRING_LITERAL, KEYWORD_NULL, IDENTIFIER, MINUS, LPAREN, KEYWORD_NOT]` plus `KEYWORD_CAST` per 6i plus `FLOAT_LITERAL` per 6g). Earlier fixtures that pinned a narrow expected set for this position (if any) remain valid as long as they asserted that those tokens ARE in the set, not that the set is exactly those tokens.

Evaluation at compile time: each `expression` in `INSERT VALUES (...)` is compiled to a register using the standard expression-compilation pipeline; the resulting value is stored into the corresponding column. Arithmetic, CAST, scalar function calls, and even aggregate calls (though aggregate calls with no input rows have no sensible semantics here — a later phase may restrict this) are all accepted at parse/compile time; runtime type-mismatch still raises `STORAGE_TYPE_MISMATCH` as before if the evaluated value's type disagrees with the column's declared type.

Both amendments are retroactive: they apply to Phase 1 (STRING_LITERAL) and Phase 3a (INSERT VALUES) and every phase thereafter. No prior fixture relied on the narrower behavior (verified: no phase1–6i fixture asserts a non-ASCII byte as an error inside a string body, and no phase1–6i fixture exercises INSERT VALUES with something that would parse differently under the wider frame).

## Phase 6k — Scalar functions UPPER and LOWER (ASCII-only case conversion)

Phase 6k extends the scalar-function family with `UPPER` and `LOWER`, both ASCII-only. No grammar changes (reuses the function-call shape from 6c/6j). Two new `ScalarKind` variants. No new opcodes. No new invariants.

### Phase 6k semantics

Let `v` be the runtime value of the argument. Both functions:
- `Null` → `Null`.
- `Integer(_)` → `VDBE_TYPE_MISMATCH { operation: "upper"|"lower", kind: "Integer" }`.
- `Real(_)` → same, `kind: "Real"`.
- `Text(s)` → `Text(s')` where `s'` is obtained by transforming each byte of `s` independently:
  - **UPPER**: byte `b` in `0x61..=0x7A` (ASCII `a`..`z`) → `b - 0x20` (ASCII `A`..`Z`); all other bytes pass through unchanged (including non-ASCII UTF-8 bytes, which are preserved verbatim).
  - **LOWER**: byte `b` in `0x41..=0x5A` (ASCII `A`..`Z`) → `b + 0x20` (ASCII `a`..`z`); all other bytes pass through unchanged.

**Explicitly NOT Unicode case mapping.** `UPPER('café')` yields `'CAFé'`, not `'CAFÉ'`. `UPPER('Straße')` yields `'STRAßE'`, not `'STRASSE'`. The ASCII-only convention avoids cross-language divergence on Unicode case-mapping tables (ICU vs. built-in Rust `char::to_uppercase` vs. C `locale(3)` vary). A future phase may add `UPPER_UNICODE` / `LOWER_UNICODE` or pin one mapping authoritatively; until then, ASCII-only is the spec.

The resulting byte length equals the input byte length (case conversion is in-place per byte).

### Phase 6k dispatch

The compiler extends the case-insensitive name dispatch from Phase 6j:
- `upper` → `ScalarKind::Upper`
- `lower` → `ScalarKind::Lower`
- All other existing entries unchanged.

STAR argument with UPPER/LOWER: `COMPILE_SCALAR_ARG_MISMATCH { function: "UPPER"|"LOWER", reason: "star-not-allowed" }` (reuses 6j error).

### Phase 6k error conditions

- `VDBE_TYPE_MISMATCH { operation, kind }` (reused): new `operation` values `"upper"`, `"lower"`. `kind` is `"Integer"` or `"Real"`.
- `COMPILE_SCALAR_ARG_MISMATCH` / `COMPILE_UNKNOWN_FUNCTION` (reused unchanged from 6j).

### Phase 6k non-goals

- Unicode case mapping — deferred indefinitely (see "Explicitly NOT Unicode case mapping" note above).
- Locale-aware case mapping (`LOWER('I', 'tr_TR')` → Turkish dotless-i) — permanent non-goal.
- TRIM / LTRIM / RTRIM — deferred to a later phase; independent of UPPER/LOWER.

### Test authority (Phase 6k)

`tests/cross-build/phase6k.json` is the executable specification for Phase 6k. All prior phase fixtures MUST stay green.

## Phase 6l — TRIM, LTRIM, RTRIM (ASCII-only whitespace stripping)

Phase 6l adds three more scalar functions — `TRIM`, `LTRIM`, `RTRIM` — all single-argument, all ASCII-only. Same `ScalarKind`-extension pattern as 6j/6k. No new opcodes, no new invariants, no new errors (reuses `VDBE_TYPE_MISMATCH`).

### Phase 6l semantics

The **trim-whitespace set** is the four ASCII bytes: `0x20` (SPACE), `0x09` (TAB), `0x0A` (LF), `0x0D` (CR). NOTE: these are exactly the four bytes in the Phase 1 `WHITESPACE` character class. The set is frozen — future phases may add 2-arg `TRIM(s, chars)` forms with a caller-supplied trim set, but the 1-arg form always uses this exact four-byte set.

Let `v` be the runtime value of the argument:
- `Null` → `Null`.
- `Integer(_)` → `VDBE_TYPE_MISMATCH { operation: "trim"|"ltrim"|"rtrim", kind: "Integer" }`.
- `Real(_)` → same, `kind: "Real"`.
- `Text(s)` → `Text(s')` where:
  - **LTRIM**: strip bytes in the trim-set from the start of `s` (greedy); stop at the first byte NOT in the trim-set. Remaining bytes are the result.
  - **RTRIM**: symmetric — strip from the end. Greedy backward scan.
  - **TRIM**: both leading and trailing. Equivalent to `RTRIM(LTRIM(s))` and to `LTRIM(RTRIM(s))` (order-independent).
  - Empty input stays empty. All-whitespace input becomes the empty string.

Non-ASCII bytes (>= 0x80) are NEVER in the trim-set — they're preserved.

### Phase 6l dispatch

Compiler name dispatch extends 6j/6k:
- `trim` → `ScalarKind::Trim`
- `ltrim` → `ScalarKind::Ltrim`
- `rtrim` → `ScalarKind::Rtrim`

All three respect STAR rejection (`COMPILE_SCALAR_ARG_MISMATCH { function: "TRIM"|"LTRIM"|"RTRIM", reason: "star-not-allowed" }`) and case-insensitive name lookup.

### Phase 6l error conditions

Reused only. `VDBE_TYPE_MISMATCH.operation` values added: `"trim"`, `"ltrim"`, `"rtrim"`.

### Phase 6l non-goals

- Two-argument `TRIM(s, chars)` with a user-supplied trim set — deferred to a later phase that introduces multi-arg function call syntax.
- Leading/trailing modifier syntax (`TRIM(LEADING FROM s)`, `TRIM(TRAILING 'x' FROM s)`) — deferred.
- Unicode-aware whitespace (e.g., U+00A0 NO-BREAK SPACE, U+3000 IDEOGRAPHIC SPACE) — permanent non-goal; ASCII-only.

### Test authority (Phase 6l)

`tests/cross-build/phase6l.json` is the executable specification for Phase 6l. All prior phase fixtures MUST stay green.

## Phase 6m — Compound SELECT with `UNION ALL`

Phase 6m introduces compound SELECTs — combining multiple SELECT result sets into a single result. Phase 6m implements only the `UNION ALL` combinator (row concatenation without deduplication). Future phases add `UNION` (with dedup), `INTERSECT`, `EXCEPT`.

### Phase 6m tokens (additions)

| Token kind       | Rule |
|------------------|------|
| `KEYWORD_UNION`  | `U N I O N`, case-insensitive, NOT followed by `IDENT_CONT`. Reserved from 6m onward. |
| `KEYWORD_ALL`    | `A L L`, case-insensitive, NOT followed by `IDENT_CONT`. Reserved from 6m onward. |

Both reserved: a column / table named `union` or `all` raises `PARSE_UNEXPECTED_TOKEN` with `kind: KEYWORD_UNION` / `KEYWORD_ALL`. Verified no prior phase fixture uses `UNION` or `ALL` as an identifier.

### Phase 6m grammar — structural restructuring

The top-level `select-statement` production is reshaped. Prior phases treated `ORDER BY` and `LIMIT / OFFSET` as clauses directly on the SELECT. Phase 6m lifts them to the compound level:

```
select-statement := compound-select

compound-select  := select-core ( compound-op select-core )*
                    [ order-by-clause ]
                    [ limit-clause ]

compound-op      := KEYWORD_UNION KEYWORD_ALL

select-core      := KEYWORD_SELECT [ KEYWORD_DISTINCT ] projection-list
                    [ KEYWORD_FROM from-clause ]
                    [ KEYWORD_WHERE where-clause ]
                    [ KEYWORD_GROUP KEYWORD_BY group-by-list ]
                    [ KEYWORD_HAVING having-clause ]
```

Key: `select-core` does NOT contain `ORDER BY` or `LIMIT / OFFSET` — those live on the compound envelope. For a single-core compound (the most common case — no `UNION ALL`), this is observably identical to pre-6m behaviour; parsers that currently attach ORDER BY/LIMIT directly to the SELECT AST node need to lift them to the compound-level AST.

### Phase 6m AST (additions)

Generators choose a shape. Canonical form suggested:

```
Statement::Select {
  cores:    Vec<SelectCore>,      // len >= 1
  ops:      Vec<CompoundOp>,      // len == cores.len() - 1
  order_by: Option<Vec<OrderByTerm>>,
  limit:    Option<LimitClause>,
}

enum CompoundOp { UnionAll }
```

Invariant: `cores.len() == ops.len() + 1`. A single-core SELECT has empty `ops`.

### Phase 6m semantics — execution

Given `compound-select` with cores `C_1, C_2, ..., C_n` all joined by `UNION ALL`:

1. **Column count check (compile-time)**: let `k = column_count(C_1)`. Require `column_count(C_i) == k` for all `i > 1`. Mismatch → `COMPILE_COMPOUND_ARITY_MISMATCH { expected: k, got: column_count(C_i), at_core: i }` (1-based).

2. **Execution without ORDER BY / LIMIT**:
   - For each `i` in 1..=n, execute `C_i` independently and emit its result rows in order. The final result stream is `rows(C_1) ++ rows(C_2) ++ ... ++ rows(C_n)` (row concatenation; no dedup).

3. **Execution with ORDER BY**:
   - All cores' rows go into a single shared sorter (same sorter infrastructure as Phase 6b).
   - After all cores finish populating the sorter, drain it per the ORDER BY keys.
   - ORDER BY keys resolve against `C_1`'s projected output schema (column names and positional indices). Column names that are unique to `C_i` for `i > 1` are NOT resolvable here — use positional references (`ORDER BY 1`, `ORDER BY 2`) when core columns differ in naming.

4. **Execution with LIMIT / OFFSET**:
   - Applied on the combined stream (sorter output if ORDER BY is present, else concatenated row stream). Same semantics as Phase 6a / 6b at their respective positions.

5. **Result schema**:
   - Column count = `k` (first core's count).
   - Column names = `C_1`'s projection names. (Subsequent cores' names are discarded.)
   - Column types are NOT statically coerced in 6m — each row carries its own runtime types. Mainline SQLite's type-unification rules are not implemented; if one core produces an Integer in column 1 and another core produces Text, both appear in the output verbatim with their native types. (Sort order for ORDER BY uses the cross-type total order pinned in Phase 6g.)

### Phase 6m compilation

The compiler produces a single VDBE program that, for each core `C_i`:
- Compiles the core's body exactly as a standalone SELECT would, EXCEPT `ResultRow` is replaced with:
  - `SorterInsert` into a shared sorter (if the compound has ORDER BY), OR
  - `ResultRow` directly (if no ORDER BY, LIMIT/OFFSET still applies via counter arithmetic against a shared counter across all cores)

No new VDBE opcodes are required. Existing `ResultRow`, sorter opcodes, and LIMIT/OFFSET counter arithmetic are sufficient.

### Phase 6m error conditions

- **`COMPILE_COMPOUND_ARITY_MISMATCH { expected, got, at_core }`** (NEW): a non-first core has a different column count than the first core. Detected at compile time after each core's projection is resolved.
- **Reused**: `PARSE_UNEXPECTED_TOKEN` for grammar errors; `COMPILE_UNKNOWN_COLUMN` for ORDER BY references that don't match `C_1`'s output schema.

### Phase 6m non-goals

- `UNION` (with dedup), `INTERSECT`, `EXCEPT` — Phase 6o.
- Mixing compound operators in one statement (e.g. `A UNION ALL B INTERSECT C`) — deferred; 6m allows only `UNION ALL` so mixing is N/A, but 6o needs a precedence rule.
- Per-core `ORDER BY` / `LIMIT` (SQLite: `SELECT ... ORDER BY ... LIMIT ... UNION ALL ...` is a syntax error there too in non-extension mode) — not supported.
- Column-name-ambiguity across cores — handled by "first core wins" rule; no error raised.
- Type unification / affinity coercion across cores — permanent non-goal (we stay strict).

### Test authority (Phase 6m)

`tests/cross-build/phase6m.json` is the executable specification for Phase 6m. All prior phase fixtures MUST stay green.

## Phase 6n — Scalar subqueries (uncorrelated)

Phase 6n introduces scalar subqueries: a parenthesized `SELECT` used in place of any expression. Phase 6n allows only **uncorrelated** subqueries (the subquery body cannot reference the outer query's columns). Correlated subqueries are deferred.

### Phase 6n tokens

Unchanged. Grammar uses existing `LPAREN`, `KEYWORD_SELECT`, `RPAREN`.

### Phase 6n grammar

The `primary-expression` production gains a subquery form:

```
primary-expression := ... existing primary forms ...
                    | scalar-subquery

scalar-subquery    := LPAREN compound-select RPAREN
```

**Parser disambiguation**: on encountering `LPAREN` at a primary-expression position, the parser peeks the next token. If it is `KEYWORD_SELECT`, parse a scalar-subquery. Otherwise, parse a parenthesized-expression (existing behaviour). The peek is non-destructive.

### Phase 6n AST

```
Expr::ScalarSubquery { stmt: Box<Select> }
```

The `Select` node is the same one produced by the top-level `compound-select` parser — a subquery can itself be a compound SELECT with UNION ALL, aggregates, WHERE, ORDER BY, LIMIT, etc.

### Phase 6n semantics — evaluation

At runtime, a scalar subquery evaluates to a single value:
- Execute the subquery's compiled body.
- If the body emits **zero rows**, the subquery's value is `Null`.
- If the body emits **exactly one row**, the subquery's value is the row's first column (subsequent columns are N/A — see compile-time arity check below).
- If the body emits **two or more rows**, raise `VDBE_SUBQUERY_MORE_THAN_ONE_ROW` at the moment the second row's `ResultRow`-equivalent opcode fires. The outer query is interrupted (like any VDBE error).

Compile-time arity check: the subquery's projection must have **exactly one** output column. Otherwise raise `COMPILE_SUBQUERY_NOT_SCALAR { got_columns: N }`. For a compound-SELECT subquery, the arity is taken from the first core (consistent with 6m's "first core defines the output schema" rule).

**Uncorrelated restriction**: the subquery's body is compiled in an independent column-resolution scope. A column reference inside the subquery that doesn't resolve within the subquery's own FROM clauses (including joined tables) raises `COMPILE_UNKNOWN_COLUMN` — the existing error. No correlation is performed.

### Phase 6n compilation

Recommended shape: **hoist subqueries to the program preamble**. Since uncorrelated subqueries evaluate to a constant value per outer execution, each subquery can be compiled into a preamble that runs once before the main body starts; the result is cached in a dedicated "subquery result" register that the main body references as a normal input register.

Concretely:
1. Allocate a `dest_reg` for the subquery's cached result, initialised to `Null`.
2. Allocate a `state_reg` (Integer), initialised to `Integer(0)` ("no row seen yet").
3. Emit the subquery's compiled opcodes into the preamble, with cursor/sorter/register namespaces offset to be disjoint from the outer program's.
4. Replace the subquery body's `ResultRow N` opcode with `SubqueryEmit { state_reg, dest: dest_reg, src: proj[0] }`.
5. In the main body, wherever `Expr::ScalarSubquery` appears, emit references to `dest_reg` — the cached value.

Alternative (also acceptable): compile the subquery inline at its reference site. Per-row re-evaluation is correctness-preserving but wasteful for subqueries inside scan loops. Generators choosing inline compilation must still honor the zero-rows-→-Null and ≥2-rows-→-error semantics.

### Phase 6n new VDBE opcode — `SubqueryEmit`

See `vdbe-opcodes.spec.md` § Phase 6n for opcode details. Summary:

```
SubqueryEmit { state_reg: usize, dest: usize, src: usize }
```

Semantics:
- If `regs[state_reg] == Integer(0)`: set `regs[state_reg] = Integer(1)`; set `regs[dest] = regs[src]`.
- Else: raise `VDBE_SUBQUERY_MORE_THAN_ONE_ROW`.

### Phase 6n error conditions

- **`COMPILE_SUBQUERY_NOT_SCALAR { got_columns }`** (NEW): the subquery's projection has a column count != 1.
- **`VDBE_SUBQUERY_MORE_THAN_ONE_ROW`** (NEW): the subquery emitted a second row at runtime. No fields.
- **`COMPILE_UNKNOWN_COLUMN { column }`** (pinned by cross-corroboration in 6n): canonical error for "column reference cannot be resolved in the current scope." Takes precedence over — and at the subquery boundary, SUBSUMES — prior finer-grained variants some targets previously emitted (table-not-in-scope, qualified-column-not-found, bare-column-without-table, storage-column-not-found, evaluation-column-without-table). When a subquery body references a column that doesn't exist in the subquery's own FROM-scope (whether bare or qualified with a table name from the outer query's scope), the compile failure MUST surface as `COMPILE_UNKNOWN_COLUMN`. A generator that internally produces finer-grained column-resolution errors MUST map them to `COMPILE_UNKNOWN_COLUMN` at the subquery boundary (or earlier — mapping at every column-resolution failure site is also acceptable). The `column` field carries the unresolved name (qualified form `"t.x"` preserved verbatim if the user wrote a qualified reference).
- **Reused**: `PARSE_UNEXPECTED_TOKEN` (for grammar errors).

### Phase 6n non-goals

- **Correlated subqueries** — the subquery can reference only its own scope's columns in Phase 6n. A later phase adds column-scope inheritance.
- `EXISTS (SELECT ...)` — deferred.
- `IN (SELECT ...)` — Phase 6p.
- `NOT IN (SELECT ...)` — with 6p.
- `ANY / ALL / SOME (SELECT ...)` — deferred.
- Subquery as FROM-clause source (derived table) — deferred.

### Test authority (Phase 6n)

`tests/cross-build/phase6n.json` is the executable specification for Phase 6n. All prior phase fixtures MUST stay green.

## Phase 6o — Compound SELECT `UNION` (with dedup)

Phase 6o extends compound SELECT with `UNION` (no ALL modifier) — set union with duplicate elimination. `UNION ALL` from 6m is unchanged. `INTERSECT` and `EXCEPT` are deferred to Phase 6p.

### Phase 6o tokens

Unchanged. No new keywords. `UNION` and `ALL` are already reserved from 6m.

### Phase 6o grammar

The `compound-op` production from 6m is broadened:

```
compound-op := KEYWORD_UNION [ KEYWORD_ALL ]
```

Reading:
- `UNION ALL` → `CompoundOp::UnionAll` (from 6m; row concatenation without dedup).
- `UNION` (no ALL) → `CompoundOp::Union` (NEW in 6o; row concatenation WITH dedup).

Mixing operators in one compound is permitted in 6o (e.g. `A UNION ALL B UNION C`). Evaluation is strictly left-to-right — each compound-op combines the running left partial with the next core. There is no precedence between `UNION` and `UNION ALL`; the left-to-right fold produces a well-defined but non-associative semantics.

### Phase 6o AST

Extend `CompoundOp` enum:

```
enum CompoundOp { UnionAll, Union }
```

`cores: Vec<SelectCore>`, `ops: Vec<CompoundOp>` — unchanged shape from 6m.

### Phase 6o semantics — evaluation

For a single `UNION` compound (exactly one op, two cores): the result is the set of **distinct** rows that appear in either `C_1` or `C_2`. Row equality is defined by the cross-type total order from 6b/6g — same rule as `SortValueEq` (NULL == NULL, within-type value equality, across-type unequal).

For multi-op compound with mixed `UNION` and `UNION ALL`: strict left-to-right fold. Example `A UNION ALL B UNION C`:
1. Compute `A UNION ALL B` (concatenation with duplicates).
2. Compute result-of-step-1 UNION C (combined, then dedup the full result).

The fold is well-defined but not associative: `A UNION ALL (B UNION C)` may differ from `(A UNION ALL B) UNION C`. We do NOT implement parenthesized compound forms in 6o; the grammar is flat (left-to-right as written).

Arity rule from 6m unchanged: all cores must have the same column count; mismatch → `COMPILE_COMPOUND_ARITY_MISMATCH`.

Compound-level ORDER BY / LIMIT / OFFSET apply to the final (post-dedup) result, exactly as in 6m.

### Phase 6o compilation

Recommended shape: all cores feed the same shared sorter (as in 6m). If any op in the compound is `UNION` (not ALL), the sorter is a **dedup-sort sorter** — same machinery as Phase 6f DISTINCT. After all cores have populated the sorter, the drain loop emits each distinct row once, applying compound-level ORDER BY / LIMIT / OFFSET.

Mixed-op compound: because the fold is strictly left-to-right and `UNION ALL` is the DEFAULT (preserves duplicates up to the next `UNION`), the simplest correct compile is:
- Accumulate cores into a shared sorter.
- Each `UNION` op at position `i` means: "after inserting cores[0..=i]'s rows, the running set must be deduped before combining with cores[i+1]."

The simplest implementation: compile ALL cores into the shared sorter in sequence, then AFTER all cores are populated, if ANY op is `UNION`, sort-and-dedup the entire sorter. This approximates the semantics for the common case (single UNION or all-UNIONs); for the pathological `A UNION ALL B UNION C UNION ALL D` form, this "collapse-then-dedup-once" approach is INCORRECT (D's duplicates get deduped against the earlier accumulation).

For 6o, generators MAY take the simple approach as long as fixtures pass; the mixed-op case is deliberately under-tested. Pathological mixing is a 6o non-goal; the spec's left-to-right fold is the formal semantics but 6o's fixture set does NOT exercise mixed `UNION ALL` + `UNION` in the same compound.

For pure-`UNION` compounds (most common), the simple approach is correct.

### Phase 6o error conditions

Reused only. `COMPILE_COMPOUND_ARITY_MISMATCH` from 6m; `PARSE_UNEXPECTED_TOKEN` for grammar errors.

### Phase 6o non-goals

- `INTERSECT` and `EXCEPT` — Phase 6p.
- Strict left-to-right mixed-op evaluation for pathological `UNION ALL + UNION` patterns — fixture coverage intentionally excludes this.
- Parenthesized compound forms `(A UNION ALL B) UNION C` — deferred; not in the grammar.
- `INTERSECT ALL` / `EXCEPT ALL` multiplicity-preserving forms — permanent non-goal (rarely used).

### Test authority (Phase 6o)

`tests/cross-build/phase6o.json` is the executable specification for Phase 6o. All prior phase fixtures MUST stay green.

## Phase 6p — Compound SELECT `INTERSECT` and `EXCEPT`

Phase 6p rounds out the SQL set-operator family: `INTERSECT` (set intersection of distinct rows) and `EXCEPT` (set difference of distinct rows). Both are always dedup-semantics (no ALL modifier — deferred indefinitely).

### Phase 6p tokens (additions)

| Token kind            | Rule |
|-----------------------|------|
| `KEYWORD_INTERSECT`   | `I N T E R S E C T`, case-insensitive, not followed by `IDENT_CONT`. Reserved. |
| `KEYWORD_EXCEPT`      | `E X C E P T`, case-insensitive, not followed by `IDENT_CONT`. Reserved. |

Both reserved from 6p onward — using either as a column/table name raises `PARSE_UNEXPECTED_TOKEN` with the matching `kind`.

### Phase 6p grammar

The `compound-op` production from 6o broadens:

```
compound-op := KEYWORD_UNION [ KEYWORD_ALL ]
             | KEYWORD_INTERSECT
             | KEYWORD_EXCEPT
```

No ALL modifier for INTERSECT/EXCEPT in 6p (grammar rejects `INTERSECT ALL` / `EXCEPT ALL` as PARSE_UNEXPECTED_TOKEN on the ALL).

### Phase 6p AST

`CompoundOp` enum extended:

```
enum CompoundOp { UnionAll, Union, Intersect, Except }
```

### Phase 6p semantics — left-to-right fold

For a compound-select with N cores `C_0, C_1, ..., C_{N-1}` and N-1 ops `op_0, op_1, ..., op_{N-2}` (where `op_i` combines the running left partial with `C_{i+1}`):

**Row-inclusion predicate.** For a given row value `R`, define `in_i(R)` = "some row equal to R appears in `C_i`'s output" (dedup semantics; multiplicity within a single core is ignored). The predicate `accum` is built by left-to-right fold:

1. `accum := in_0(R)`
2. For `i = 1..N-1`, given `op_{i-1}` and `in_i(R)`:
   - `UNION` or `UNION ALL` (at the *set* level, same operator after dedup): `accum := accum OR in_i(R)`
   - `INTERSECT`: `accum := accum AND in_i(R)`
   - `EXCEPT`: `accum := accum AND NOT in_i(R)`
3. Emit `R` iff `accum` is true.

**Row equality.** Same as Phase 6o — cross-type total order from 6b/6g, NULL==NULL.

**Compile-time arity rule.** Unchanged from 6m — all cores must have the same column count; mismatch → `COMPILE_COMPOUND_ARITY_MISMATCH`.

**Compound-level ORDER BY / LIMIT / OFFSET.** Applied to the final fold result, same as 6m/6o.

### Phase 6p compilation

Recommended shape: single shared sorter with **side-tag value**. Each core inserts rows into the shared sorter along with its side-tag (core-index `i`). The drain loop groups adjacent equal-projection rows; for each group, it computes the N `has_tag_i` flags (1 if the group contains at least one row from core `i`, else 0), then compiles the fold into a sequence of AND/OR/NOT operations over those flags, then emits the group's row once if the final `accum` is true.

Per-group logic (compile-time lowered):
```
accum := has_tag_0
for i = 1..N-1:
  case op_{i-1}:
    UNION / UNION ALL    → accum := accum OR has_tag_i
    INTERSECT            → accum := accum AND has_tag_i
    EXCEPT               → accum := accum AND NOT has_tag_i
if accum: emit group row
```

Sorter layout:
- Keys: k columns (the projection — same as 6o's dedup sorter).
- Values: 1 column — the side-tag (Integer).
- Drain reads both the key values (via `SorterReadKey`) and the side-tag (via `SorterRead`).

Tag-flag update per row:
- For each `i`: if `side_tag == i`, then `has_tag_i := 1` (saturating OR). Implementation via existing `Eq` + `Or` opcodes: `is_this_core := (side_tag == Integer(i))`; `has_tag_i := has_tag_i OR is_this_core`.

Group-break detection:
- Same as Phase 6o's dedup pattern. Previous-row scratch registers, per-column `SortValueEq` + `And` chain, `JumpIfFalse` to drop into emit-and-init branch.

NOT operator:
- The spec leaves implementation open. Generators MAY use an existing `Not` opcode if one exists, or synthesize negation via `Eq(value_reg, zero_reg)` — both approaches produce `1` for a `0` input and `0` for a `1` input, which is what `NOT` needs over the boolean flags here.

### Phase 6p error conditions

- **`PARSE_UNEXPECTED_TOKEN`** (reused): `INTERSECT ALL` / `EXCEPT ALL` syntax, or malformed compound-op.
- **`COMPILE_COMPOUND_ARITY_MISMATCH`** (reused from 6m).

### Phase 6p non-goals

- `INTERSECT ALL` / `EXCEPT ALL` (multiplicity-preserving variants) — permanent non-goal.
- Parenthesized compound-select — deferred.
- Operator precedence between `UNION` and `INTERSECT` / `EXCEPT` — SQLite gives INTERSECT higher precedence than UNION/EXCEPT; sqlite-leap uses **strict left-to-right** (no precedence), consistent with 6m/6o. This is a documented divergence from SQLite; fixtures do not exercise mixed-op precedence-sensitive queries.

### Test authority (Phase 6p)

`tests/cross-build/phase6p.json` is the executable specification for Phase 6p. All prior phase fixtures MUST stay green.

## Phase 6q — String concatenation operator `||`

Phase 6q adds the binary infix operator `||` (string concatenation). No new AST node shape — reuses `BinaryOp` with a new `BinOp` variant `"||"`. Expression frame gets a new precedence level `concat` between `unary` and `multiplicative` (matching SQLite's documented precedence: `||` binds tighter than `* /`, which bind tighter than `+ -`, which bind tighter than comparison).

### Phase 6q tokens

| Token kind | Rule |
|---|---|
| `CONCAT` | The two-character sequence `||` (two consecutive `|`). |

Tokenizer handling: on encountering `|`, peek one character. If the peek is `|`, consume both and emit `CONCAT`. Otherwise raise `LEX_UNEXPECTED_CHARACTER` at the first `|`'s position. A single bare `|` is not a valid token in Phase 6q (and no existing phase emits a bitwise-OR token).

Maximal-munch interacts correctly with CONCAT: `|||` tokenises as `CONCAT` followed by `LEX_UNEXPECTED_CHARACTER` at the third `|` — because `CONCAT` consumes the first two `|`, then the bare `|` is rejected. Fixtures do not exercise `|||`, but the rule is pinned.

### Phase 6q grammar

The `expression` production gains one level:

```
expression     := comparison
comparison     := additive [ cmp-op additive ]
additive       := multiplicative (( PLUS | MINUS ) multiplicative)*
multiplicative := concat (( STAR | SLASH | PERCENT ) concat)*
concat         := unary ( CONCAT unary )*                          // NEW in 6q
unary          := MINUS unary | primary
primary        := literal | IDENTIFIER | LPAREN expression RPAREN | scalar-subquery | function-call | cast-expression
```

`concat` is **left-associative**, matching all other binary operators in this grammar. `'a' || 'b' || 'c'` parses as `BinaryOp(op="||", left=BinaryOp(op="||", left='a', right='b'), right='c')`.

Precedence (high→low): parens, unary `-`, `||`, `* /`, `+ -`, comparison, NOT, AND, OR.

- `1 || 2 * 3` parses as `(1 || 2) * 3` (concat higher than `*`).
- `1 * 2 || 3` parses as `1 * (2 || 3)` (symmetric).
- `'a' || 'b' = 'ab'` parses as `('a' || 'b') = 'ab'` (concat higher than comparison).
- `'a' || 'b' AND 1` parses as `('a' || 'b') AND 1` (concat higher than AND).

Fixtures exercise only the subset where the mixed-type semantics are well-defined (see § "Non-goals" below).

### Phase 6q AST

The `BinOp` enum is extended:

```
BinOp ∈ { "+", "-", "*", "/", "=", "!=", "<", "<=", ">", ">=", "AND", "OR", "||" }
```

No new AST node shape — `BinaryOp { op: "||", left, right }` carries concat expressions. Test-authoritative AST fixtures in `phase6q.json` pin this form.

### Phase 6q evaluation semantics — Concat operator

Evaluation of `BinaryOp { op: "||", left, right }`:

1. Evaluate `left` to `lv`.
2. Evaluate `right` to `rv`.
3. Apply the following truth table:

| `lv`    | `rv`    | Result |
|---------|---------|--------|
| Null    | (any)   | Null   |
| (any)   | Null    | Null   |
| Text    | Text    | Text — UTF-8 concatenation of `lv.text` followed by `rv.text` (byte-level concatenation; UTF-8 validity is preserved because both operands are already valid UTF-8) |
| Integer | Text    | Text — coerce `lv` to decimal representation (same format as `Scalar { kind: CastText }` on Integer input — signed base-10, no leading zeros, `-` for negatives), then concatenate |
| Text    | Integer | Text — symmetric |
| Integer | Integer | Text — both operands coerced to decimal representation, then concatenated |
| Real    | (any)   | **`VDBE_UNSUPPORTED_CAST { from_kind: "Real", to_kind: "Text" }`** — deferred to Phase 6r together with the pinned f64 shortest-round-trip format |
| (any)   | Real    | Same — deferred |
| Blob    | (any)   | N/A — Blob is not in the Phase 6q value model |

**Null short-circuits over Real rejection.** `NULL || 3.14` evaluates to `Null`, NOT a `VDBE_UNSUPPORTED_CAST`. The rule is: step 3 checks Null first; only when both operands are non-Null does it check for Real. This means a `NULL` propagating up through a concat chain never turns into an error even if a Real value is also involved.

**Operand evaluation order is left-to-right.** For a chain `a || b || c`, evaluated as `(a || b) || c`:
- `a` is evaluated first. If Real, error immediately.
- Then `b`. If Real, error.
- Result of `a || b` computed.
- Then `c`. If Real, error.

No short-circuiting on Null for the *purpose of skipping evaluation*: `NULL || (expression_with_side_effects)` still evaluates the right operand. (Phase 6q expressions are pure; this distinction matters only if side-effecting expressions are later added.)

**Result kind is always `Text` (unless Null).** Even `Integer || Integer` yields `Text`.

### Phase 6q compilation — Concat

`BinaryOp { op: "||", left, right }` compiles to:

1. Allocate register `left_reg`, emit `left`-subtree into `left_reg`.
2. Allocate register `right_reg`, emit `right`-subtree into `right_reg`.
3. Emit `Concat { left_reg, right_reg, dest }` (opcode defined in `vdbe-opcodes.spec.md` § Phase 6q).

The compiler does NOT need to emit separate `Scalar { kind: CastText }` preludes — `Concat` handles the Integer→Text coercion inline. This keeps the opcode count low and avoids spurious temporaries for the common case.

Left-associative chains produce nested `Concat` opcodes: `a || b || c` compiles to
```
Concat { left_reg=reg(a), right_reg=reg(b), dest=t1 }
Concat { left_reg=t1,      right_reg=reg(c), dest=t2 }
```

### Phase 6q error conditions

- **`LEX_UNEXPECTED_CHARACTER`** (reused): bare `|` not followed by another `|`.
- **`PARSE_UNEXPECTED_TOKEN`** (reused): `CONCAT` as a prefix (no left operand); dangling `CONCAT` at end of expression; CONCAT where a keyword is expected.
- **`VDBE_UNSUPPORTED_CAST { from_kind: "Real", to_kind: "Text" }`** (reused from Phase 6i): one or both operands of `||` evaluate to `Real`.

### Phase 6q retroactive spec pin — error-name convention for binary-operator type mismatch

**Pinned by cross-corroboration (both C and Rust agents on Phase 6q independently invented workarounds to reconcile this, indicating a real spec gap):**

The canonical runtime error for type mismatches at **infix binary operators** (`+`, `-`, `*`, `/`, `=`, `!=`, `<`, `<=`, `>`, `>=`, `AND`, `OR`, unary `-`, unary `NOT`, `WHERE`-as-boolean) is:

```
EVAL_TYPE_ERROR { op: <symbol>, left_type: <TYPE>, right_type: <TYPE> }     // infix binary
EVAL_TYPE_ERROR { op: <symbol>, operand_type: <TYPE> }                      // unary / context
```

where:
- `<symbol>` is the operator's source-level symbol: `"+"`, `"-"`, `"*"`, `"/"`, `"="`, `"!="`, `"<"`, `"<="`, `">"`, `">="`, `"AND"`, `"OR"`, `"NOT"`, `"WHERE"`.
- `<TYPE>` is the UPPERCASE type name: `"INTEGER"`, `"TEXT"`, `"REAL"`, `"NULL"`.

`VDBE_TYPE_MISMATCH` is **NOT** used for infix-binary-operator type errors. `VDBE_TYPE_MISMATCH` is reserved for **scalar-function** and **aggregate** argument type errors: `LENGTH`, `ABS`, `UPPER`, `LOWER`, `TRIM`, `LTRIM`, `RTRIM`, `SUM`, `AVG`, `MIN`, `MAX`, etc. Its field shape is `{operation: <function-name-lowercase>, kind?: <type-name-capitalized>}`.

**Legacy note — Phase 6g inconsistency.** `phase6g.json` includes a fixture `SELECT r + s FROM t` (Real + Text) pinned to `VDBE_TYPE_MISMATCH { operation: "add" }`. This is inconsistent with the pinned rule above (which would require `EVAL_TYPE_ERROR { op: "+", left_type: "REAL", right_type: "TEXT" }`). The inconsistency predates Phase 6q and was not revisited here because the mismatch-on-Real path is a generator-specific branch (Real values never reach the legacy Integer-vs-Text arithmetic path that Phase 2c-1 pinned). **Do NOT add new fixtures that use `VDBE_TYPE_MISMATCH` on binary infix operators.** A future cleanup phase MAY reconcile 6g by re-pinning to `EVAL_TYPE_ERROR`; for now, both conventions coexist in test data (but not in new fixtures).

**Implementation guidance.** Generators that added a `numeric-text discriminator` or an `op_strict` compile-time flag to reconcile Phase 6q's original fixture (which erroneously expected `VDBE_TYPE_MISMATCH`) MUST remove those workarounds. The corrected Phase 6q fixture `concat-precedence-vs-additive` pins `EVAL_TYPE_ERROR { op: "+", left_type: "INTEGER", right_type: "TEXT" }`, which flows through the existing Phase 2c-1 arithmetic-type-error path with no new code.

### Phase 6q non-goals

- Real operand support — deferred to Phase 6r (requires pinned f64 shortest-round-trip format).
- Blob operand support — Blob values are not yet in the value model.
- `||` as bitwise-OR (it isn't — SQLite uses `|` for bitwise-OR; sqlite-leap doesn't implement bitwise operators in Phase 6q).
- Mixed-type numeric arithmetic via `||` chains (e.g. relying on `'12' * 2` to produce Integer 24 via implicit Text→Integer coercion). Integer/Text comparison and arithmetic coercion remain out of scope; fixtures avoid these shapes.
- Result-kind-dependent dispatch (e.g. "if both operands are Integer, keep result as Integer"). Rejected — result is always Text (or Null), matching SQLite's documented `||` semantics.

### Test authority (Phase 6q)

`tests/cross-build/phase6q.json` is the executable specification for Phase 6q. All prior phase fixtures MUST stay green.

## Phase 6s — Multi-arg scalar functions (`IFNULL`, `COALESCE`)

Phase 6s generalises the function-call grammar from single-argument to variadic, and introduces the first multi-argument scalar functions: `IFNULL` (exactly 2 args) and `COALESCE` (≥ 2 args, compiled as nested `IFNULL`). One new opcode `Scalar2`. One new invariant (28). `max_invariant = 28`. No new tokens (both function names are IDENTIFIERs in call position, per the existing convention).

Scope-cut: `SUBSTR` (needs UTF-8 byte-vs-codepoint design call), `ROUND` (depends on Real→Text format from Phase 6r), and fixed-2-arg math functions (`POWER`, `MOD`) are deferred. Phase 6s establishes the 2-arg infrastructure; follow-on phases fill in the function roster.

### Phase 6s grammar — variadic function-call

The `function-call` production is widened:

```
function-call := IDENTIFIER LPAREN function-args RPAREN
function-args := STAR
               | expression ( COMMA expression )*
```

Zero-argument function calls (`FOO()`) remain rejected with `PARSE_UNEXPECTED_TOKEN` at the `RPAREN`, expected set = the expression-start set. (SQLite permits zero-arg functions like `RANDOM()`; sqlite-leap does not introduce any in Phase 6s; the empty-arg-list path is deferred.)

STAR continues to be only valid for `COUNT(*)`; presence of STAR with any other function name produces:
- A known aggregate (other than COUNT): `COMPILE_AGGREGATE_ARG_MISMATCH { function, reason: "star-only-for-count" }` (existing, unchanged).
- A known scalar: `COMPILE_SCALAR_ARG_MISMATCH { function, reason: "star-not-allowed" }` (existing, unchanged).
- An unknown name: `COMPILE_UNKNOWN_FUNCTION { name }` (existing).

### Phase 6s compile-time dispatch

Name resolution (case-insensitive) is extended:

1. **Aggregate names** (`count`, `sum`, `min`, `max`, `avg`): unchanged. All take exactly one argument (STAR for COUNT is the only exception). Multi-arg aggregate call → `COMPILE_AGGREGATE_ARG_COUNT_MISMATCH { function, expected: 1, got: <n> }` (NEW, see below).
2. **Single-arg scalars** (`length`, `abs`, `upper`, `lower`, `trim`, `ltrim`, `rtrim`): unchanged. Multi-arg scalar call → `COMPILE_SCALAR_ARG_COUNT_MISMATCH { function, expected: 1, got: <n> }` (NEW).
3. **Two-arg scalars (NEW in 6s)**:
   - `ifnull` → `Scalar2 { kind: Ifnull, arg1_reg, arg2_reg, dest }`. Exactly 2 args. Wrong count → `COMPILE_SCALAR_ARG_COUNT_MISMATCH { function: "IFNULL", expected: 2, got: <n> }`.
4. **Variadic scalars (NEW in 6s)**:
   - `coalesce` → compile-time desugaring to right-nested `IFNULL`. A `COALESCE(a1, a2, ..., an)` call (n ≥ 2) is rewritten at AST-or-compile level to:
     ```
     IFNULL(a1, IFNULL(a2, IFNULL(..., IFNULL(a_{n-1}, a_n)...)))
     ```
     Equivalent to `n - 1` nested `Scalar2 { kind: Ifnull }` emissions. Wrong arg count (n < 2) → `COMPILE_SCALAR_ARG_COUNT_MISMATCH { function: "COALESCE", expected: ">=2", got: <n> }` (where `expected` is a string for the minimum-n case).
5. **Unknown names**: `COMPILE_UNKNOWN_FUNCTION` (unchanged).

**Desugaring is invisible to the VDBE.** There is no `Coalesce` opcode and no coalesce-specific dispatch. The compiler lowers COALESCE to nested IFNULL *before* emitting opcodes. This keeps the VDBE surface minimal.

### Phase 6s evaluation semantics

**`IFNULL(a, b)` semantics** (equivalent to SQL standard):
- If `a` is `Null` → evaluate `b` and return it (any type, including Null).
- Else → return `a` (any type).
- No type coercion. Arguments with incompatible types are not an error at the IFNULL boundary — IFNULL is a pure choice function.

**`COALESCE(a, ...)` semantics** (via desugaring): first non-`Null` argument, or `Null` if all are `Null`. Implemented as nested IFNULL.

**Evaluation order**: strictly left-to-right. Both arguments are evaluated unconditionally at the opcode level (no short-circuit short-cut needed since our expressions are pure). The `Scalar2 { kind: Ifnull }` opcode simply inspects `arg1_reg` and selects either `arg1_reg` or `arg2_reg` for `dest` — both registers have already been populated by the preceding argument-compile.

**No type mismatch is raised by IFNULL itself.** If `a` is `Null` and `b` is `Null`, result is `Null`. If `a` is Integer and `b` is Text, and `a` is non-null, result is Integer. If `a` is Text and `b` is Integer, and `a` is null, result is Integer.

### Phase 6s AST shape

No new AST node kinds. Function-call argument list is already represented as `args: Expression[]` in the existing `FunctionCall` node (widened from single-arg in earlier phases — the AST already supports a list, even if Phase 6j grammar restricted it to length 1; 6s relaxes the grammar check). `COALESCE` desugaring happens at the compile stage and produces nested `FunctionCall { name: "IFNULL", args: [...] }` AST nodes (in-memory transformation; does not affect any persisted AST schema).

Alternatively, generators may desugar COALESCE directly at the emit stage (walk the args list, emit the innermost `Scalar2 Ifnull` first, then fold outward). Both approaches are spec-equivalent; the AST-transform approach is recommended for clarity.

### Phase 6s compilation — IFNULL

`FunctionCall { name: "IFNULL", args: [e1, e2] }` compiles to:

1. Allocate register `arg1_reg`; emit `e1` into `arg1_reg`.
2. Allocate register `arg2_reg`; emit `e2` into `arg2_reg`.
3. Allocate register `dest`; emit `Scalar2 { kind: Ifnull, arg1_reg, arg2_reg, dest }`.

Register aliasing: any pair or triple of {arg1_reg, arg2_reg, dest} may coincide; the VDBE dispatch must inspect `arg1_reg` first and compute the output before overwriting `dest`. For Null values, the "copy" can be a direct register-copy (no buffer allocation).

### Phase 6s error conditions

- **`COMPILE_SCALAR_ARG_COUNT_MISMATCH { function, expected, got }`** (NEW): scalar function called with wrong number of arguments. `function` is UPPERCASE. `expected` is either an integer (for fixed-arity functions like IFNULL=2, LENGTH=1) or a string (`">=2"` for COALESCE). `got` is the actual count.
- **`COMPILE_AGGREGATE_ARG_COUNT_MISMATCH { function, expected, got }`** (NEW): aggregate function called with wrong number of arguments. Mirror of the scalar form. `expected` is always `1` in Phase 6s (no multi-arg aggregates yet).
- **`COMPILE_UNKNOWN_FUNCTION`** (reused).
- **`COMPILE_SCALAR_ARG_MISMATCH { function, reason: "star-not-allowed" }`** (reused).

No runtime errors are specific to 6s. `Scalar2 { kind: Ifnull }` cannot itself raise — the choice is always safe.

### Phase 6s non-goals

- **`SUBSTR`**: deferred. Two open questions: (a) byte-semantics vs codepoint-semantics for `start`/`length`, (b) negative `start` for right-anchored indexing. Spec needs explicit pin before implementation.
- **`ROUND`**: deferred to the phase that pins Real→Text (because ROUND(Real, digits) may produce Real values that flow through `CAST(... AS TEXT)` in downstream tests).
- **`POWER` / `MOD` / `PI` / `RANDOM`**: deferred.
- **Zero-argument function calls** (e.g. `RANDOM()`): grammar does not admit them in 6s.
- **Generic variadic opcode** (`ScalarN { kind, args: usize[], dest }`): rejected for 6s. Desugaring to nested 2-arg opcodes keeps the VDBE ISA fixed-shape and avoids variable-length opcode payloads. If a future phase introduces a function that genuinely benefits from variadic dispatch at runtime, revisit.

### Test authority (Phase 6s)

`tests/cross-build/phase6s.json` is the executable specification for Phase 6s. All prior phase fixtures MUST stay green.

## Phase 6t — Transactions as SQL statements (`BEGIN`, `COMMIT`, `END`, `ROLLBACK`)

Phase 6t adds the SQL surface for transactions: `BEGIN`, `COMMIT`, `END` (COMMIT synonym), and `ROLLBACK` as top-level statements. **Semantic transactions are NOT implemented in Phase 6t** — BEGIN and COMMIT / END are no-ops in the pre-WAL storage model; ROLLBACK raises a runtime error because no journal / WAL backing exists. Genuine transaction isolation and rollback semantics land with the Phase 4 (WAL) rollout.

Phase 6t scope: syntax acceptance and a clean-error story for rollback, so that higher-level test suites (sqllogictest) that wrap blocks of statements in `BEGIN ... COMMIT;` parse and execute, and so that the same suites' ROLLBACK uses surface as clear runtime errors rather than silent corruption.

### Phase 6t tokens

Four new **reserved keywords**:

| Token kind | Rule |
|---|---|
| `KEYWORD_BEGIN`    | The IDENT_START+IDENT_CONT* word matching `begin` (case-insensitive). |
| `KEYWORD_COMMIT`   | The word matching `commit` (case-insensitive). |
| `KEYWORD_ROLLBACK` | The word matching `rollback` (case-insensitive). |
| `KEYWORD_END`      | The word matching `end` (case-insensitive). |

These four join the existing reserved-keyword set (CAST, AS, REAL, FLOAT, DOUBLE, UNION, ALL, INTERSECT, EXCEPT). They are NOT acceptable as column or table identifiers (unlike aggregate and scalar function names, which remain IDENTIFIERs per the convention pinned in Phases 6c / 6j).

**Rationale for reservedness:** `BEGIN` / `COMMIT` / `ROLLBACK` / `END` are statement-starting keywords at the top level. A column named `begin` would be ambiguous at top-level parsing (e.g. `BEGIN INTEGER` — is that a malformed BEGIN statement followed by "INTEGER", or a column declaration?). Reserving these keywords sidesteps the ambiguity.

### Phase 6t grammar

Top-level `statement` production is widened to include the new transaction statements:

```
statement := select-statement
           | insert-statement
           | update-statement
           | delete-statement
           | create-table-statement
           | begin-statement
           | commit-statement
           | rollback-statement

begin-statement    := KEYWORD_BEGIN
commit-statement   := KEYWORD_COMMIT
                    | KEYWORD_END                    -- END is a COMMIT synonym
rollback-statement := KEYWORD_ROLLBACK
```

**No optional modifiers** in Phase 6t. SQLite accepts `BEGIN [DEFERRED|IMMEDIATE|EXCLUSIVE] [TRANSACTION]`; sqlite-leap v1 accepts only the bare keyword. A trailing `TRANSACTION`, `DEFERRED`, etc. raises `PARSE_UNEXPECTED_TOKEN` (the parser expects `SEMICOLON` or EOF after the keyword). These modifiers are deferred to post-v1.

### Phase 6t AST shape

Three new top-level AST kinds:

```
BeginStatement    := { kind: "BeginStatement" }
CommitStatement   := { kind: "CommitStatement" }
RollbackStatement := { kind: "RollbackStatement" }
```

`END` parses into `CommitStatement` (no distinct `EndStatement` — END is lexed as `KEYWORD_END` but the parser collapses it to the same AST node as COMMIT).

### Phase 6t compilation

- **BEGIN** → program with zero body opcodes: `[Init, Halt]`. No effect at runtime.
- **COMMIT** / **END** → identical empty-body program: `[Init, Halt]`.
- **ROLLBACK** → program with a single body opcode: `[Init, TxnRollback, Halt]`. `TxnRollback` raises `VDBE_ROLLBACK_NOT_SUPPORTED` at runtime; control never reaches `Halt`.

### Phase 6t evaluation semantics

- **BEGIN / COMMIT / END execution**: the VDBE runs `[Init, Halt]` with no observable side effects. Result: empty rows list `{rows: []}`. No registers, no cursors allocated.
- **ROLLBACK execution**: the VDBE executes `Init` (no-op), then `TxnRollback`, which raises `VDBE_ROLLBACK_NOT_SUPPORTED` and halts.

**Nested BEGIN / orphan COMMIT / orphan ROLLBACK:**
- A second `BEGIN` while no explicit state exists is still a no-op (we have no "in-transaction" flag because we have no transactions). SQLite would raise `cannot start a transaction within a transaction`; sqlite-leap v1 permits the nested `BEGIN` silently. Documented divergence; Phase 4 (WAL) will revisit.
- `COMMIT` / `END` without a preceding `BEGIN`: no-op. Documented divergence from SQLite (which raises "cannot commit - no transaction is active").
- `ROLLBACK` without a preceding `BEGIN`: still raises `VDBE_ROLLBACK_NOT_SUPPORTED` — the error is about capability, not transaction state. Documented divergence.

These divergences are acceptable in the pre-WAL model because the notion of "active transaction" does not exist yet; re-pinning them to SQLite semantics is Phase 4 / 5 work.

### Phase 6t error conditions

- **`PARSE_UNEXPECTED_TOKEN`** (reused): anything after `BEGIN` / `COMMIT` / `END` / `ROLLBACK` other than `SEMICOLON` or EOF — e.g. `BEGIN TRANSACTION`, `COMMIT DEFERRED`, `ROLLBACK TO savepoint`. Savepoints are a permanent non-goal of Phase 6t.
- **`PARSE_UNEXPECTED_TOKEN { kind: KEYWORD_BEGIN | KEYWORD_COMMIT | KEYWORD_ROLLBACK | KEYWORD_END }`** (reused): any attempt to use one of these reserved words as a column or table identifier (e.g. `CREATE TABLE t (begin INTEGER)`).
- **`VDBE_ROLLBACK_NOT_SUPPORTED`** (NEW): runtime, raised by the `TxnRollback` opcode. No fields. Documentation: "ROLLBACK is not supported in Phase 6t. Semantic transactions require the WAL / journal subsystem (Phase 4+)."

### Phase 6t non-goals

- Transaction isolation (read-committed, repeatable-read, serializable). All Phase 6t statements are pre-WAL no-ops; isolation is undefined.
- Savepoints (`SAVEPOINT name`, `RELEASE name`, `ROLLBACK TO name`). Permanent non-goal of Phase 6t.
- `BEGIN DEFERRED / IMMEDIATE / EXCLUSIVE / TRANSACTION` modifiers. Deferred.
- Actually rolling back uncommitted writes. Impossible without journal / WAL — that's Phase 4.
- Auto-commit-every-statement mode explicit markers. Our model is implicit auto-commit already; there's no mode switch in 6t.

### Test authority (Phase 6t)

`tests/cross-build/phase6t.json` is the executable specification for Phase 6t. All prior phase fixtures MUST stay green.

## Phase 6r — Real→Text coercion (DESIGN-SPIKE, deferred)

Phase 6r was originally scoped to land Real→Text conversion, lifting the Phase 6i / 6q `VDBE_UNSUPPORTED_CAST` restriction that currently blocks `CAST(real AS TEXT)` and `real_value || text_value`. Landing it requires pinning a **byte-identical f64→decimal-string format** that both the C and Rust targets produce verbatim. Without that byte-identical contract, cross-build equivalence — sqlite-leap's central LEAP invariant — breaks on any query that surfaces a Real value.

**Why this is hard** (not a full-phase single-sitting landable item):

1. **Rust's `f64::to_string()` and C's `printf("%.17g", ...)` produce different output** for the same input. Examples:
   - `1.0_f64.to_string()` in Rust → `"1"` (no decimal point, round-trip OK via parse-as-f64).
   - `printf("%.17g", 1.0)` in C → `"1"` (same; but other libc implementations may print `"1.0000000000000000"`).
   - `1.1_f64.to_string()` in Rust → `"1.1"` (shortest-round-trip; Rust uses Grisu3).
   - `printf("%.17g", 1.1)` in C → `"1.1000000000000001"` (full 17 significant digits; libc doesn't do shortest-round-trip).
   - `printf("%.17e", 3.14)` in C → `"3.14000000000000012e+00"`.
   - `format!("{:.17e}", 3.14_f64)` in Rust → `"3.14000000000000012e0"` — note the exponent-padding and sign-on-exponent divergence from C.

2. **Neither stdlib alone produces SQLite's documented `%!.15g`-like format** ("15 significant digits, trim trailing zeros, use scientific notation if exponent < -4 or ≥ 17"). Both targets would need to implement the same formatter from scratch.

3. **Naïve options all have divergence risks:**
   - **A. Pin C stdlib's `%.17g`** — Rust must reimplement C's printf formatting byte-for-byte. libc implementations differ; even pinning glibc's behaviour creates platform divergence (musl, macOS libSystem, Windows CRT all format edge-cases differently).
   - **B. Pin Rust stdlib's Grisu3 output** — C must reimplement Grisu3. ~400 LOC of careful bit manipulation; small off-by-one deviations silently break round-trip.
   - **C. Pin a custom fixed-width format** — e.g. always `±d.DDDDDDDDDDDDDDDDDeSEE` (17-digit mantissa, signed 2-digit exponent, no zero-stripping). Simple to implement identically in both languages; ugly output; loses SQLite compat.
   - **D. Pin SQLite's documented `%!.15g` format** — both sides must implement the SQLite-specific formatter (includes the `!` modifier for "don't strip trailing zeros"). Full algorithm must be spelled out in spec pseudocode.

4. **The only non-blocking path for sqllogictest compatibility (which is where Real→Text actually matters) is Option D** (SQLite-format). Ryu/Grisu is the state of the art algorithm and is ~500 LOC of careful implementation.

### Current status (as of Phase 6t landing)

- `CAST(<real> AS TEXT)` raises `VDBE_UNSUPPORTED_CAST { from_kind: "Real", to_kind: "Text" }` (Phase 6i).
- `<real> || <anything>` raises the same error (Phase 6q).
- No fixture currently requires Real→Text; all Real-producing fixtures terminate in Real-typed output (e.g. `SELECT AVG(x)` returns Real, not Text).

### Recommended next steps (for a design session, not autonomous agent work)

1. Pick the format pin (Option A/B/C/D above) based on whether SQLite compat or ease-of-implementation dominates.
2. If Option D: spell out the full `%!.15g` formatter algorithm in spec pseudocode — including the exact rounding rule (round-half-to-even) and the scientific-notation threshold.
3. Add ~30 pinned input→output fixtures covering: zero, ±small subnormals, ±1.0, 3.14, 1e100, 1e-100, (nearly) minimum positive normal, (nearly) maximum finite, integer-valued reals, fractions with >15 significant digits.
4. Only after the format is pinned in spec: spawn C and Rust agents and expect zero divergence.

### Phase 6r non-goals (deferred until this design question is resolved)

- NaN / Inf handling in CAST (our value model per Phase 6g rejects NaN at value-construction time; Inf handling is a corner case that depends on the same format pin).
- `printf` / `format` in user SQL (not a goal anywhere in v1).
- Locale-dependent decimal separators (permanent non-goal; always `.`).

### Test authority (Phase 6r)

No fixtures. Phase 6r is blocked on design; no `phase6r.json` exists. The existing `VDBE_UNSUPPORTED_CAST` rejection stays authoritative.

## Phase 9a — CREATE INDEX statement + empty-index storage scaffold

Phase 9a introduces `CREATE INDEX` as a top-level statement. Scope is **narrowly scoped as scaffolding**: an index is created, persisted in `sqlite_schema`, and an empty index-leaf B-tree page is allocated — but the index is NOT backfilled from existing table rows, NOT maintained through INSERT/UPDATE/DELETE, and NOT consulted by the query planner. Downstream phases incrementally fill these in:

- **Phase 9b** — backfill CREATE INDEX from existing table rows.
- **Phase 9c** — INSERT/UPDATE/DELETE index maintenance.
- **Phase 9d** — query planner uses indexes for WHERE / ORDER BY.
- **Phase 9e** — PRIMARY KEY auto-indexes.
- **Phase 9f** — DROP INDEX.
- **Phase 9g** — UNIQUE enforcement.

**Why this split.** A single-phase "index-everything" implementation would sprawl across grammar, file format, VDBE ISA, query planner, and DML-maintenance paths simultaneously. 9a isolates the **grammar + storage scaffolding** surface. The output of 9a is a DB file that mainline SQLite can open, see the (empty) index in its schema, and round-trip without complaint.

### Phase 9a tokens

Two new **reserved keywords**:

| Token kind | Rule |
|---|---|
| `KEYWORD_INDEX`  | The word matching `index`  (case-insensitive). |
| `KEYWORD_UNIQUE` | The word matching `unique` (case-insensitive). |

`ON` is already a reserved keyword from Phase 6e (JOIN...ON). No new `CREATE` keyword (already reserved from Phase 2a). No new `DROP` keyword in 9a (DROP INDEX deferred to 9f).

### Phase 9a grammar

Top-level `statement` production is widened:

```
statement := ... (all prior alternatives) ...
           | create-index-statement

create-index-statement := KEYWORD_CREATE [ KEYWORD_UNIQUE ] KEYWORD_INDEX
                            IDENTIFIER                     -- index name
                            KEYWORD_ON IDENTIFIER          -- target table
                            LPAREN
                              IDENTIFIER ( COMMA IDENTIFIER )*
                            RPAREN
```

No optional `IF NOT EXISTS` in 9a (deferred — adding it widens error semantics). No collating sequences, no sort order `ASC/DESC` per-column (valid SQL but out-of-scope; a follow-on phase will relax). No expression indexes (`CREATE INDEX ... ON t(LOWER(x))` — permanent non-goal).

### Phase 9a AST

```
CreateIndexStatement := {
  kind: "CreateIndexStatement",
  name: string,              -- the index's identifier (case-preserved)
  table: string,             -- target table identifier (case-preserved)
  columns: string[],         -- ordered list of column names, non-empty (grammar enforces >= 1 via LPAREN IDENTIFIER ...)
  unique: boolean            -- true iff KEYWORD_UNIQUE appeared
}
```

The `unique` flag is recorded but NOT enforced in 9a (no duplicate rejection on INSERT — deferred to 9g). The flag IS written to the canonical `sqlite_schema.sql` (so mainline reading our DB sees the correct form).

### Phase 9a compile-time validation

Before emitting opcodes:

1. **Table existence.** The target table must exist in the in-memory schema registry. If not: `COMPILE_UNKNOWN_TABLE { table }`.
2. **Column existence.** Each listed column must exist in the target table's column set. First unknown column: `COMPILE_UNKNOWN_COLUMN { table, column }`.
3. **Duplicate columns.** The `columns` list must not contain the same column name twice (case-insensitive comparison). First duplicate: `COMPILE_DUPLICATE_INDEX_COLUMN { index, column }` (NEW).
4. **Name collision.** The index name must not already be present as EITHER a table name OR an index name anywhere in `sqlite_schema`. If it is: raised at runtime by the VDBE's `CreateIndex` opcode as `STORAGE_INDEX_EXISTS { name }` (NEW). (Compile-time cannot always see uncommitted index creations in a statement batch; storage is authoritative.)

### Phase 9a retroactive spec pin — name-collision case-sensitivity asymmetry

**Pinned by cross-corroboration (both C and Rust agents on Phase 9a independently arrived at the same narrow fix):**

Name-collision checks in sqlite_schema are **case-sensitive for table-vs-table** and **case-insensitive for all other pairs** (table-vs-index, index-vs-index, index-vs-table). Specifically:

- `CREATE TABLE t ...` followed by `CREATE TABLE T ...` — both succeed (case-sensitive — pinned by phase2a `create-table-case-preserved-case-sensitive-lookup`).
- `CREATE INDEX idx ...` followed by `CREATE INDEX IDX ...` — second raises `STORAGE_INDEX_EXISTS { name: "IDX" }` (case-insensitive — phase9a `index-name-collision-case-sensitivity`).
- `CREATE INDEX foo ON foo (x)` — raises `STORAGE_INDEX_EXISTS` (case-insensitive index-vs-table — phase9a `create-index-name-collides-with-table`).
- `CREATE TABLE idx ...` after `CREATE INDEX idx ...` — raises `STORAGE_TABLE_EXISTS` (case-insensitive table-vs-index — phase9a `create-table-name-collides-with-index`).

**Rationale:** phase2a pinned table-vs-table case-sensitivity as a feature (user can have `t` and `T` as distinct tables). Generalising to case-insensitive would regress that test, so indexes add case-insensitive checks alongside the existing strict table-vs-table path. Matches SQLite's actual convention.

**Implementation guidance:** generators MUST keep the existing table-vs-table strict byte-comparison path AND add a case-insensitive (ASCII-only) comparison for any pair involving an index. A single "unified case-insensitive sqlite_schema namespace" check would break phase2a.

### Phase 9a compilation — program shape

`CREATE INDEX` compiles to a 3-opcode body:

```
[Init, CreateIndex { name, table, columns, unique }, Halt]
```

No registers, no cursors. `num_registers = 0`, `num_cursors = 0`.

### Phase 9a storage-layer semantics

On `CreateIndex { name, table, columns, unique }` dispatch, the storage layer:

1. Validates `name` does not collide with any existing `sqlite_schema` entry (table or index). If collision: raise `STORAGE_INDEX_EXISTS { name }`.
2. Validates `table` exists (raise `STORAGE_TABLE_NOT_FOUND` otherwise — defensive; compile-time should have caught this).
3. Validates each `column` exists in the named table (raise `STORAGE_COLUMN_NOT_FOUND` otherwise — defensive).
4. Allocates a new page (next free page number = current page count + 1, following the Phase 3a convention).
5. Initializes that page as an **empty index-leaf** (page type `0x0a`, cell count 0, `cell_content_area_start = page_size` — see `file-format.spec.md` § "Index-leaf page (type 0x0a)" [added in 9a]).
6. Inserts a new `sqlite_schema` row with rowid = `K + 1` where `K` is the current sqlite_schema row count:
   - `type = 'index'`
   - `name = <index name>` (as-parsed, case-preserved)
   - `tbl_name = <target table name>` (as-parsed, case-preserved)
   - `rootpage = <newly-allocated page number>`
   - `sql = <canonical CREATE INDEX statement>` (see next subsection)
7. Increments the schema cookie (header offset 40–43).
8. Updates the in-header page count.

### Canonical `CREATE INDEX` writer form (Phase 9a)

When serializing to `sqlite_schema.sql`:

```
CREATE INDEX <name> ON <table> (<col1>, <col2>, ...)
```

or with UNIQUE:

```
CREATE UNIQUE INDEX <name> ON <table> (<col1>, <col2>, ...)
```

One ASCII space between each token; comma-space between column names; no trailing semicolon; no surrounding whitespace. `<name>`, `<table>`, `<colN>` are case-preserved as parsed from the user's input.

### Reader tolerance for `CREATE INDEX` SQL (Phase 9a)

On DB open, when parsing a `sqlite_schema` row with `type='index'`:

- Parse the `sql` column to recover `(name, table, columns, unique)`. The canonical writer form above MUST be accepted. Whitespace tolerance and case-insensitive keyword handling follow the Phase 3a CREATE TABLE convention.
- The resulting index record is stored in the in-memory schema registry. **It is not consulted for query planning in 9a.** (Phase 9d wires it up.)
- **Reader tolerance widening for mainline-written indexes:** mainline's canonical form uses the same template (`CREATE INDEX <name> ON <table> (<cols>)`); minor whitespace or casing variants are accepted. Complex SQLite-only variants (collation specs, partial-index `WHERE` clauses, expression indexes) MUST raise `STORAGE_UNSUPPORTED_FEATURE { feature: "create_index_sql_form" }`.

### Phase 9a error conditions

- **`COMPILE_UNKNOWN_TABLE { table }`** (reused): CREATE INDEX names a table that doesn't exist.
- **`COMPILE_UNKNOWN_COLUMN { table, column }`** (reused): CREATE INDEX names a column that doesn't exist in the target table.
- **`COMPILE_DUPLICATE_INDEX_COLUMN { index, column }`** (NEW): same column appears twice in the column list.
- **`STORAGE_INDEX_EXISTS { name }`** (NEW): runtime — attempted to create an index whose name collides with an existing table or index.
- **`PARSE_UNEXPECTED_TOKEN`** (reused): malformed grammar.

### Phase 9a non-goals

- **Backfill.** 9a creates empty index-leaf pages only. If the target table already has rows, those rows are NOT indexed (deferred to 9b). Tests must not rely on pre-existing rows being queryable through an index (query-planner integration doesn't exist until 9d anyway).
- **DML maintenance.** INSERT / UPDATE / DELETE on indexed tables do NOT touch the index (deferred to 9c). This makes indexes immediately stale after 9a; keep tests's INSERT patterns independent from CREATE INDEX for this phase.
- **UNIQUE enforcement.** The flag is recorded, not enforced (deferred to 9g).
- **DROP INDEX.** Deferred to 9f.
- **IF NOT EXISTS / OR REPLACE** modifiers. Deferred.
- **Partial indexes** (`CREATE INDEX ... WHERE <pred>`). Permanent non-goal.
- **Expression indexes** (`CREATE INDEX ... ON t(LOWER(x))`). Permanent non-goal.
- **Collation / sort order per column** (`CREATE INDEX ... ON t(x DESC, y COLLATE ...)`).  Deferred.
- **Mainline-produced populated indexes** — 9a's file-format read path tolerates mainline's empty indexes only. DBs whose indexes have cells (page 0x0a with cell_count > 0, or page type 0x02 used at all) still raise `STORAGE_UNSUPPORTED_FEATURE`. Phase 9b lifts this for 0x0a with cells; Phase 9d lifts 0x02.

### Test authority (Phase 9a)

`tests/cross-build/phase9a.json` is the executable specification for Phase 9a. All prior phase fixtures MUST stay green.

## Phase 9be — Index backfill + equality-index query planner (FUSED)

Phase 9be is the minimum **publishable** index phase: CREATE INDEX backfills existing rows into the index B-tree, and the query planner uses single-column indexes to accelerate `WHERE indexed_col = <const>` lookups. Everything else (DML maintenance, range, ORDER BY, index splits, UNIQUE enforcement, PRIMARY KEY auto-index) is split into downstream phases.

### Phase 9be scope

**IN:**
- **Backfill on CREATE INDEX**: on `CREATE INDEX`, scan the target table's rows and populate the index tree.
- **Populated index-leaf pages** (type 0x0a, cell count > 0): both writable and readable. Mainline interoperability: our populated empty-for-now → populated indexes are legible by mainline SQLite, and mainline-written populated indexes are legible by us.
- **Equality planner**: compile-time recognition of `WHERE indexed_col = <const>` patterns and emission of an index-seek recipe instead of a full-table scan. Single-column indexes only; multi-column indexes fall back to full-scan (planner only matches first column in 9be — relax in 9d).
- **Five new VDBE opcodes**: `IdxOpenRead`, `IdxSeek`, `IdxNext`, `IdxRowid`, `TableSeekRowid`.
- **NULL-sort-first** ordering for index keys.

**OUT (deferred, split into downstream phases):**
- DML maintenance on indexed tables (INSERT/UPDATE/DELETE do NOT update indexes → 9c). Tests that INSERT after CREATE INDEX will observe stale indexes; SELECT-via-index on post-CREATE inserts returns ONLY the backfilled rows. Tests pin this explicitly.
- Range predicates (`WHERE col < k`, `>`, `BETWEEN`, `IN`) — deferred to 9d.
- ORDER BY via index — 9d.
- Multi-column index matching (planner only uses 1st col even on multi-col indexes) — 9d.
- Index-tree splits. **Single-leaf only** — if backfill would produce cells not fitting in one 0x0a page, raise `STORAGE_PAGE_FULL`. Lifted in 9d.
- UNIQUE enforcement — 9g.
- PRIMARY KEY auto-index — 9f.
- DROP INDEX — 9f.

### Phase 9be grammar

No grammar changes. CREATE INDEX grammar is unchanged from 9a. The equality planner hooks into the existing SELECT grammar — detection happens at compile time, no new syntax.

### Phase 9be planner recipe

Given `SELECT <projection> FROM <t> WHERE <col> = <expr>` (single-equality WHERE, no other predicates):

1. **Index selection.** Look up the indexes registry for table `t`. Select the first index whose first column is `<col>` (case-insensitive match). If multiple indexes qualify, pick the one with fewer total columns (tie: earliest-registered). If no index qualifies, fall back to full-scan (existing Phase 2c-2 WHERE recipe).
2. **Recipe emission.** If an index is selected and `<expr>` is a compile-time constant OR a column-free expression (i.e. independent of the table being scanned — evaluatable before the scan begins), emit:

```
       Init
       <compile expr into key_reg>                          -- the value to seek for
       OpenRead       t_cursor, "<t>"
       IdxOpenRead    idx_cursor, <idx.rootpage>
       IdxSeek        idx_cursor, key_reg, @done            -- position at first entry with key == regs[key_reg]; else jump @done
loop:  IdxRowid       idx_cursor, rowid_reg
       TableSeekRowid t_cursor, rowid_reg                   -- position table cursor at that rowid
       <emit Column opcodes for each projection column>
       ResultRow      proj_start, proj_count
       IdxNext        idx_cursor, key_reg, @loop            -- advance; if still matching, jump @loop; else fall through
done:  Close          idx_cursor
       Close          t_cursor
       Halt
```

If `<expr>` depends on the table's row data (e.g. `WHERE x = other_col`), the predicate is **not constant-across-scan** and the planner falls back to full-scan. Phase 9be does NOT attempt to index-join against the same table.

3. **Fall-back.** Any WHERE shape the planner doesn't recognize compiles exactly as it did pre-9be (Phase 2c-2 semantics). No regressions; the index is simply not consulted. Tests with un-indexed WHERE clauses remain green.

### Phase 9be index selection decision tree (compile-time)

```
function select_index_for_where(table_name, where_expr) -> Option<IndexRef>:
    # Match the AST shape EXACTLY. Don't try to be clever.
    if where_expr is not BinaryOp { op: "=", left: L, right: R }: return None
    let (col_side, const_side) =
        if L is ColumnRef and R is expression independent of table_name: (L, R)
        else if R is ColumnRef and L is expression independent of table_name: (R, L)
        else: return None
    let column_name = col_side.name
    let candidates = indexes_on(table_name) filtered to those where columns[0] ==_ci column_name
    if candidates is empty: return None
    # Tie-break: fewer columns first, then earliest-registered (lower sqlite_schema rowid).
    candidates.sort_by((idx) => (idx.columns.len, idx.sqlite_schema_rowid))
    return candidates[0]
```

`indexes_on(table_name)` consults the in-memory schema registry populated at DB open and CREATE INDEX time. `==_ci` is ASCII case-insensitive.

### Phase 9be constant-detection

`expression independent of table_name` means the AST contains no ColumnRef whose scope is the table being scanned. For 9be: if the ColumnRef's qualifier or resolution points at `table_name` or is unqualified in a single-table query, it depends on the table. Anything else (a literal, a subquery, an expression built from constants and scalar-function calls with no column refs to the scanned table) is independent. See `sql-grammar.spec.md` § "Phase 2c-2 column-binding scope" for the existing scope machinery.

### Phase 9be equivalence contract

For any SELECT the planner transforms to use an index, the **result set** MUST be identical (same rows, same order where ORDER BY is applied) to the full-scan result set. Specifically:

- **Row order**: the index-seek recipe produces rows in (indexed-col, rowid) order. The full-scan recipe produces rows in rowid order. When no ORDER BY is present, both are acceptable (SQL doesn't mandate order without ORDER BY). **Tests MUST NOT pin ordering-sensitive results on un-ORDERed SELECTs**. Where ordering is tested, an explicit ORDER BY is required.
- **Result content**: exactly the same rows must appear. If the index is stale (DML happened after CREATE INDEX without maintenance — that's the 9be known limitation), the index-backed result can diverge from the table's actual rows. **Tests that INSERT after CREATE INDEX and then query via the indexed column MUST pin the staleness behaviour explicitly** (see `stale-index-after-insert-does-not-see-new-row` fixture).

### Phase 9be error conditions

- **`STORAGE_PAGE_FULL`** (reused): backfill's serialized index cells don't fit in one 0x0a page. The backfill succeeds partially → cleanup: the transaction is aborted, the index entry in sqlite_schema is NOT written, the allocated page is released. Test-observable: the `STORAGE_PAGE_FULL` error surfaces and `CREATE INDEX` is treated as if it never ran.
- **`STORAGE_CORRUPT_INDEX_REFERENCE { rowid }`** (NEW): `TableSeekRowid` couldn't find a row with the given rowid in the target table. Indicates an index entry pointing at a rowid the table doesn't have — corruption or stale-index bug.
- **`COMPILE_*`** errors from CREATE INDEX remain as in 9a.

### Phase 9be backfill algorithm

On `CreateIndex` opcode dispatch, after the name-collision check and page allocation (Phase 9a):

1. Open a read cursor over the target table. Walk all rows (using the existing rowid-ordered Rewind+Next iteration).
2. For each row, extract the indexed column values. Build an **index cell record**: a record (per `file-format.spec.md` § "Record format") containing the indexed column values followed by the rowid as the final element. See `file-format.spec.md` § "Index cell format" for the byte-exact layout.
3. Accumulate cells in memory. When all rows are processed, sort cells by (indexed-col-values, rowid) using the ordering rules below.
4. Bulk-write the sorted cells into the empty 0x0a leaf page allocated in step 4 of Phase 9a's storage protocol. If total cell bytes exceed the page's available space, raise `STORAGE_PAGE_FULL`, release the allocated page, do NOT write the sqlite_schema row. The CREATE INDEX fails atomically.
5. Otherwise, finalize: write the sqlite_schema row, bump schema cookie, update page count.

Sort ordering (NULL-sort-first, type-aware):

- **NULL sorts before every non-NULL value**. All NULLs are equal.
- **INTEGER vs INTEGER**: numeric comparison (promoted through i64).
- **REAL vs REAL**: numeric comparison; NaN is a non-goal (our value model rejects NaN at construction, per Phase 6g).
- **INTEGER vs REAL**: promoted to f64, numeric comparison.
- **TEXT vs TEXT**: byte-wise UTF-8 (memcmp). No collation selection in 9be.
- **TEXT vs INTEGER/REAL**: INTEGER/REAL sorts before TEXT. (Matches SQLite's default type-precedence ordering.)
- **Rowid tie-breaker**: when all indexed columns are equal, compare rowids ascending.

### Phase 9be non-goals (restated)

- DML maintenance (→ 9c)
- Range / ORDER BY via index (→ 9d)
- Multi-column WHERE matching (→ 9d)
- Index splits (→ 9d)
- UNIQUE enforcement (→ 9g)
- PRIMARY KEY auto-index (→ 9f)
- DROP INDEX (→ 9f)
- Covering indexes (indexes that store non-key columns to avoid the TableSeekRowid round-trip) — permanent non-goal for v1.
- Reverse-index scan (descending) — 9d.

### Test authority (Phase 9be)

`tests/cross-build/phase9be.json` is the executable specification for Phase 9be. All prior phase fixtures MUST stay green.

### Phase 9be retroactive spec pins (2026-04-18, post-landing)

1. **`IdxSeek` / `IdxNext` with NULL key.** SQL `x = NULL` is never true under 3VL. Both `IdxSeek` and `IdxNext` MUST short-circuit to the no-match branch when `regs[key_reg]` is NULL. Backfilled NULL-keyed cells (which exist under NULL-sort-first ordering) MUST NOT match a NULL equality probe.
   - **Why pinned:** both C and Rust implementations independently converged on this behaviour; the `equality-with-null-const-returns-nothing` and `equality-excludes-null-rows` fixtures gate it.

2. **Equality-index planner conservatism — top-level bare `EQ` only.** The planner only matches a WHERE clause whose top-level AST node is `BinOp::Eq(ColumnRef, <constant-across-scan-expr>)` (or the symmetric form). `AND` / `OR` compounds fall back to full-scan in Phase 9be. Phase 9d introduces AND-with-post-filter.
   - **Why pinned:** both generators converged on the same conservative rule; simpler spec, smaller surface area for bugs.

3. **Index selection tie-break.** When multiple candidate indexes apply, prefer fewest indexed columns; break remaining ties by sqlite_schema_rowid (i.e. creation order). Single-column indexes always win over multi-column indexes whose leading column matches.

### Phase 9be deferred / latent (NOT required to pass fixtures)

- **Populated index-leaf disk serialization.** The in-memory backend is fully covered by Phase 9be fixtures. The on-disk writer in at least one generator currently emits *empty* 0x0a leaves even for populated indexes. This is acceptable for Phase 9be (no fixture exercises db_close → db_open round-trip with an index). Bidirectional file-format compatibility for populated index leaves is a hard requirement for Phase 8 (publication) and will be gated by a dedicated round-trip harness (`tests/roundtrip_real.py` or equivalent). Until then, **disk index serialization is a known gap**, not a bug.








## Phase 9c — DML index maintenance

Phase 9c wires INSERT, UPDATE, and DELETE to keep every existing index on a table in sync. No new grammar. No new keywords. No new statements. The work is entirely in the compiler's codegen for DML and the executor's handling of the three new Phase 9c opcodes (`IdxOpenWrite`, `IdxInsert`, `IdxDelete` — see `vdbe-opcodes.spec.md` § "Phase 9c opcodes").

### Phase 9c scope

**IN (v1):**
- INSERT INTO t ... — after `InsertRow`, for each index on `t`, emit `IdxOpenWrite` + `IdxInsert` + `Close`.
- DELETE FROM t WHERE ... — for each row visited by the DELETE scan, **before** `DeleteRow`, for each index on `t`, emit reads of indexed columns + `IdxDelete` + `Close`.
- UPDATE t SET c = ... WHERE ... — for each index on `t` whose column set intersects the SET target columns: read OLD indexed values → emit `IdxDelete(old, rowid)` → perform the row update → emit `IdxInsert(new, rowid)`. If an index's columns are disjoint from SET targets, skip maintenance for that index entirely.
- Multi-index tables (≥ 2 indexes) maintained simultaneously on every DML.
- NULL-valued indexed columns participate (NULL cells stored + removable; equality probe with `= NULL` still matches nothing, per 9be 3VL pin).

**OUT (later phases):**
- Splits / interior index pages → Phase 9d.
- UNIQUE enforcement → Phase 9g.
- PRIMARY KEY auto-index → Phase 9f.
- DROP INDEX → Phase 9f.
- Partial indexes (`WHERE` clause on CREATE INDEX) — not on v1 roadmap.

### Compile-time analysis — which indexes does a statement touch?

- **INSERT INTO t**: every index on `t` gets maintenance. Compiler looks up `indexes_on(t)` from the schema catalog at compile time.
- **DELETE FROM t**: every index on `t` gets maintenance (whether the DELETE targets 0, 1, or all rows — runtime determines the count, compile-time emits one maintenance block per index wrapped in the DELETE loop).
- **UPDATE t SET c1 = ..., c2 = ... WHERE ...**: for each index `idx` on `t`, check if `idx.columns ∩ {c1, c2, ...}` is non-empty. If yes, emit full OLD-read + IdxDelete + IdxInsert block inside the UPDATE loop. If no, skip this index entirely (observable as no change to the index — verified by post-UPDATE equality lookups returning unchanged rowid sets).

### Phase 9c codegen recipes

These are canonical shapes. Generators MAY reorder as long as externally-observable semantics hold (all-or-nothing: if `IdxInsert` raises `STORAGE_PAGE_FULL`, the table row MUST be rolled back; see "Atomicity" below).

#### INSERT recipe (per-index tail appended to existing INSERT)

After the existing Phase 2b INSERT body emits `InsertRow tbl_cursor, column_names, start, count` and the rowid is knowable from the freshly-inserted row:

```
for each idx in indexes_on(t):
  IdxOpenWrite  idx_cursor, idx.name, idx.root_page
  <Column tbl_cursor, idx_col_0, kreg_0>
  <Column tbl_cursor, idx_col_1, kreg_1>
  ...
  <Copy rowid_reg from the latest-inserted row>
  IdxInsert     idx_cursor, kreg_0, key_count, rowid_reg
  Close         idx_cursor
```

Generators MAY instead source the indexed-col values directly from the INSERT's `start..start+count` register range, bypassing the `Column` reads, if those registers still hold the values at this point in the program. Either is acceptable.

#### DELETE recipe (per-index head inside the scan loop)

Inside the per-row DELETE loop, BEFORE the row is deleted from the table:

```
loop_top:
  <WHERE predicate evaluation — skip if false>
  for each idx in indexes_on(t):
    IdxOpenWrite  idx_cursor, idx.name, idx.root_page
    <Column tbl_cursor, idx_col_0, kreg_0>
    ...
    <read rowid from tbl_cursor into rowid_reg>
    IdxDelete     idx_cursor, kreg_0, key_count, rowid_reg
    Close         idx_cursor
  DeleteRow       tbl_cursor   # existing Phase 2c-3 opcode
  Next            tbl_cursor, loop_top
```

#### UPDATE recipe (per-affected-index wrap around the row update)

For an UPDATE where index `idx` is affected by SET:

```
# OLD phase — read indexed columns BEFORE mutation
IdxOpenWrite  idx_cursor, idx.name, idx.root_page
<Column tbl_cursor, idx_col_0, old_kreg_0>
...
<read rowid into rowid_reg>
IdxDelete     idx_cursor, old_kreg_0, key_count, rowid_reg

# <update the row in place using existing UPDATE opcode path>

# NEW phase — indexed columns may have changed
<Column tbl_cursor, idx_col_0, new_kreg_0>   # re-read post-update
...
IdxInsert     idx_cursor, new_kreg_0, key_count, rowid_reg
Close         idx_cursor
```

For an UPDATE where index `idx` is NOT affected (SET targets disjoint from idx.columns): emit nothing — that index stays untouched.

### Atomicity contract

If any `IdxInsert` inside a DML statement raises `STORAGE_PAGE_FULL`:

- The entire DML statement fails (halts execution).
- The table row and all other index cells touched by this statement MUST revert to their pre-statement state. For the in-memory backend, this means the backend snapshots the affected rows + index cells at statement entry and restores on error. For on-disk backends, this is the transaction rollback responsibility of Phase 4 WAL.

**Phase 9c constraint**: until WAL lands, the in-memory backend MUST provide statement-level atomicity via snapshot-and-restore. Fixtures `insert-overflow-reverts-both-row-and-earlier-indexes`, `update-overflow-preserves-both-old-table-and-index-state` gate this.

### Equivalence contract

After any DML + index maintenance, the following MUST hold for all tables with indexes:

1. **Table ↔ index bijection**: every row in the table has exactly one cell in each of its indexes (keyed on the indexed-col values + rowid). Every cell in an index points to a rowid that exists in the table.
2. **Equality-probe correctness**: `SELECT ... WHERE indexed_col = <val>` via the 9be equality planner returns the same rowid set as a full scan with the same WHERE clause.
3. **NULL handling**: NULL-indexed rows are removable (DELETE of a NULL-indexed row removes the NULL cell from the index), observable via full-scan post-DELETE vs planner-assisted SELECT returning the same empty/non-empty set.

### Phase 9c error conditions

- `STORAGE_PAGE_FULL` (reused): an INSERT or UPDATE caused an index cell to overflow a single leaf. DML is aborted; state reverts.
- `STORAGE_CORRUPT_INDEX_REFERENCE { rowid }` (reused from 9be): `IdxDelete` couldn't find the expected cell. Fatal.
- All existing INSERT / UPDATE / DELETE errors propagate unchanged.

### Phase 9c non-goals (restated)

- No index splits → Phase 9d.
- No UNIQUE enforcement → Phase 9g.
- No PK auto-index → Phase 9f.
- No DROP INDEX → Phase 9f.
- No ON CONFLICT clauses — not on v1 roadmap.

### Test authority (Phase 9c)

`tests/cross-build/phase9c.json` is the executable specification. All prior phase fixtures MUST stay green.

## Phase 9d — range + ORDER BY via index + index splits

Phase 9d extends the Phase 9be equality planner with **range predicates** (`>`, `<`, `>=`, `<=`, `BETWEEN a AND b`) and **`ORDER BY indexed_col ASC` via index** (eliminates the sort phase). It also unblocks the `STORAGE_PAGE_FULL` ceiling from 9be/9c by implementing **index leaf splits** and **interior index pages** (see `file-format.spec.md` § "Phase 9d additions"). Four new VDBE opcodes: `IdxRewind`, `IdxSeekGE`, `IdxSeekGT`, `IdxAdvance`. Invariants 38-41. `max_invariant = 41`.

### Phase 9d scope

**IN (v1):**
- Range predicates on indexed columns: `col > const`, `col >= const`, `col < const`, `col <= const`, `col BETWEEN lo AND hi`.
- `ORDER BY indexed_col ASC` (no explicit `DESC`) via index scan; no sorter emitted when planner detects this shape.
- `LIMIT` + `OFFSET` on top of range / ORDER-BY-via-index loops.
- Aggregation (`COUNT`, `SUM`, `MIN`, `MAX`) on top of range / ORDER-BY-via-index loops.
- Index leaf splits on overflow.
- Interior index pages (type 0x02) at arbitrary depth.
- Bidirectional file-format compat for split index trees.

**OUT (later / permanent v1 non-goal):**
- `ORDER BY indexed_col DESC` via index — continues to use existing sorter path (spec § "Phase 9d ORDER BY via index — ASC only"). Deferred permanently; sorter handles DESC adequately.
- Multi-column index matching (`WHERE a = 1 AND b = 2` on `INDEX(a, b)`) — deferred to future phase.
- Composite bounds of the form `WHERE a = 1 AND b > 5` on `INDEX(a, b)` — deferred (requires multi-col seek).
- Compound predicates with `OR` — planner falls back to full-scan.
- `WHERE col IN (a, b, c)` — deferred (not part of 9d, separate future phase).

### Phase 9d planner decision tree (compile-time)

Extends Phase 9be § "Phase 9be index selection decision tree". For a single-table `SELECT ... FROM t WHERE <pred> [ORDER BY <ob>]`:

1. If `<pred>` is `col_x = <const>` AND there is a single-column index on `col_x`: use Phase 9be equality recipe. Done.
2. Else if `<pred>` matches one of the range shapes below AND there is a single-column index on the referenced column:
   - `col_x > c`   → `IdxSeekGT lo=c`, walk with `IdxAdvance`, no upper-bound check.
   - `col_x >= c`  → `IdxSeekGE lo=c`, walk with `IdxAdvance`, no upper-bound check.
   - `col_x < c`   → `IdxRewind`, walk with `IdxAdvance`, upper-bound check: `IdxColumn(x) → Compare GE c → JumpIfTrue loop-exit`.
   - `col_x <= c`  → `IdxRewind`, walk with `IdxAdvance`, upper-bound check: `IdxColumn(x) → Compare GT c → JumpIfTrue loop-exit`.
   - `col_x BETWEEN lo AND hi` → `IdxSeekGE lo`, walk with `IdxAdvance`, upper-bound check: `IdxColumn(x) → Compare GT hi → JumpIfTrue loop-exit`.
3. Else if `<pred>` is absent OR the WHERE does not match any indexable shape AND the SELECT has `ORDER BY col_x ASC` AND there is a single-column index on `col_x`: use `IdxRewind` + `IdxAdvance` loop, emit no sorter (rows come out pre-ordered by the index).
4. Else: full-scan path (existing behaviour).

**Constant-across-scan requirement** (same as 9be): `<const>`, `c`, `lo`, `hi` MUST be independent of the table's row data (literals, parameters, the `rowid` pseudo-column, scalar subqueries, etc. — excluding references to the table's other columns). If a bound depends on a column of the scanned table, the predicate is not indexable; full-scan.

**Equality-or-range tie-break.** If a WHERE matches BOTH shape 1 (equality) AND shape 2 (range — e.g. `x = 5` is technically `x ≥ 5 AND x ≤ 5`, but the compiler should not decompose it), the equality recipe wins.

**ORDER BY + range composition.** If WHERE matches shape 2 AND ORDER BY matches the same column ASC, the range loop's natural order satisfies the ORDER BY — emit no sorter. If ORDER BY names a different column, emit the sorter on top of the range loop (existing ORDER BY recipe). Fixture `range-with-order-by-same-col-no-sorter-observable` gates the "no sorter" path (observationally equivalent to sorter path — test pins the result set, not the opcode absence; opcode absence is a perf expectation, not a correctness one).

### Phase 9d codegen recipes

#### Range `col_x > c` (strict lower bound, no upper bound)

```
      Init
      <compile c into lo_reg>
      OpenRead       t_cursor, "<t>"
      IdxOpenRead    idx_cursor, idx.name, idx.root_page
      IdxSeekGT      idx_cursor, lo_reg, @done
loop: IdxRowid       idx_cursor, rowid_reg
      TableSeekRowid t_cursor, rowid_reg
      <Column opcodes for projection>
      ResultRow      proj_start, proj_count
      IdxAdvance     idx_cursor, @loop
done: Close idx_cursor
      Close t_cursor
      Halt
```

#### Range `col_x < c` (no lower bound, strict upper bound)

```
      Init
      <compile c into hi_reg>
      OpenRead       t_cursor, "<t>"
      IdxOpenRead    idx_cursor, idx.name, idx.root_page
      IdxRewind      idx_cursor, @done
loop: IdxRowid       idx_cursor, rowid_reg
      TableSeekRowid t_cursor, rowid_reg
      <Column t_cursor, col_x_index_in_t, probe_reg>
      <JumpIfFalse (probe_reg < hi_reg), @done>       # upper-bound check, exits loop when reached
      <Column opcodes for projection>
      ResultRow      proj_start, proj_count
      IdxAdvance     idx_cursor, @loop
done: ...
```

Generators MAY read `col_x` directly from the positioned index cell (avoiding `TableSeekRowid`) as an optimization. Fixtures do not pin mechanism.

#### Range `BETWEEN lo AND hi` (inclusive lower + inclusive upper)

```
      IdxSeekGE      idx_cursor, lo_reg, @done
loop: IdxRowid       idx_cursor, rowid_reg
      TableSeekRowid t_cursor, rowid_reg
      <Column t_cursor, col_x_index, probe_reg>
      <JumpIfFalse (probe_reg <= hi_reg), @done>
      <projection>
      ResultRow ...
      IdxAdvance     idx_cursor, @loop
done: ...
```

#### ORDER BY indexed_col ASC (no WHERE, all rows)

```
      IdxOpenRead    idx_cursor, idx.name, idx.root_page
      IdxRewind      idx_cursor, @done
loop: IdxRowid       idx_cursor, rowid_reg
      TableSeekRowid t_cursor, rowid_reg
      <Column opcodes for projection>
      ResultRow      proj_start, proj_count
      IdxAdvance     idx_cursor, @loop
done: ...
```

### Phase 9d ORDER BY via index — ASC only

`ORDER BY col_x` without explicit `DESC` is treated as ASC and eligible for the index path. `ORDER BY col_x ASC` is eligible. `ORDER BY col_x DESC` is NOT eligible — it falls through to the existing sorter-based ORDER BY recipe (no reverse-index scan in v1).

### Index splits and atomicity

9c's atomicity contract (`STORAGE_PAGE_FULL` → full revert) is now **vacuous for indexes**: splits eliminate the `STORAGE_PAGE_FULL` error path for index insertion. `STORAGE_PAGE_FULL` can still occur for *table* inserts (tables are not split-aware until a future phase covers table splits). Until then, table-leaf overflow remains the dominant atomicity scenario. 9d fixtures include large-enough inserts to force index splits; no 9d fixture triggers a `STORAGE_PAGE_FULL` on an index operation.

### Bidirectional compatibility (Phase 9d)

Fixtures in `tests/cross-build/phase9d.json` cover correctness of the query semantics. Round-trip fixtures (at `tests/roundtrip_formal.py` or equivalent) gate bidirectional file-format compatibility across split index trees. The file-format additions in `file-format.spec.md` § "Phase 9d additions" are the normative layout contract.

### Phase 9d error conditions

- All existing 9be/9c errors propagate unchanged.
- `STORAGE_CORRUPT_PAGE` — now additionally covers interior index pages with malformed structure (missing rightmost-child, cell pointers out of range, descent into non-existent child pagenum).
- No new error conditions beyond this.

### Phase 9d non-goals (restated)

- ORDER BY DESC via index — permanent v1 non-goal.
- Multi-column index matching — deferred.
- OR-compounds — deferred.
- `IN` lists — deferred.
- Reverse index iteration (`IdxPrev`) — permanent v1 non-goal.
- Index-only covering scans (avoid the `TableSeekRowid` round-trip by reading columns directly from index cells) — perf optimization, not a correctness change; generators MAY implement, tests don't require it.

### Test authority (Phase 9d)

`tests/cross-build/phase9d.json` is the executable specification for Phase 9d. All prior phase fixtures MUST stay green.

### Phase 9d retroactive spec pins (2026-04-18, post-landing)

1. **`BETWEEN lo AND hi` is a parse-time desugar.** Canonical lowering: `<expr> BETWEEN <lo> AND <hi>` produces AST `BinOp::And(BinOp::Ge(<expr>, <lo>), BinOp::Le(<expr>, <hi>))` at parse time. No new AST node. No new compiler pass. This lowering composes uniformly with WHERE / HAVING / aggregate-filter / subquery contexts because downstream code sees a standard AND-of-comparisons.
   - **Why pinned:** both C and Rust generators independently converged on this lowering; the `between-with-lo-greater-than-hi-returns-empty` fixture falls out naturally under existing semantics.
   - **Consequence for NULL:** `x BETWEEN NULL AND 5` → `x >= NULL AND x <= 5` → NULL AND ... → NULL under existing 3VL → row excluded by JumpIfFalse.

2. **`IdxSeekGE` / `IdxSeekGT` skip NULL-indexed cells.** The seek lands at the first non-NULL cell satisfying the `≥` / `>` condition. NULL-indexed rows never satisfy a range predicate under SQL 3VL; the opcode encodes this directly instead of delegating to a runtime filter.
   - **Why pinned:** both generators converged on in-opcode NULL-cell skip. Alternative (runtime JumpIfFalse against a comparison) works but is O(NULL-prefix) per seek.
   - **Fixture gating:** `range-gt-with-null-rows-null-excluded`, `range-on-null-indexed-column-respects-3vl`.

### Phase 9d known perf gaps (2026-04-18)

- **Rust range planner emits full-scan, not index seek.** Rust implemented all 4 new opcodes correctly and passes fixtures, but the planner still emits the full-scan + JumpIfFalse shape instead of the `IdxSeekGE`+`IdxAdvance` recipe. Opcode shape is not fixture-gated. **Consequence:** Rust L3 (SELECT scan) benchmark will lag C until a planner-emit pass lands. Targeted follow-up.
- **Disk-backend index splits deferred.** In-memory backend has no page budget; fixtures pass regardless. Disk-backend split algorithm per `file-format.spec.md` § "Phase 9d additions" is required for bidirectional file-format compat with split index trees — gated by Phase 8 publication bar via a future round-trip harness.

## Phase 9f — PRIMARY KEY auto-index + DROP INDEX

Phase 9f wires SQL-standard PRIMARY KEY declarations to produce appropriate auto-indexes, and introduces `DROP INDEX [IF EXISTS] <name>`. One new VDBE opcode: `DropIndex`. Invariant 42. `max_invariant = 42`. Five new reserved keywords: `DROP`, `PRIMARY`, `KEY`, `IF`, `EXISTS`.

### Phase 9f scope

**IN (v1):**
- `CREATE TABLE t (id INTEGER PRIMARY KEY, ...)` — `id` becomes a **rowid alias**; no separate index is created. `WHERE id = <const>` compiles to direct `TableSeekRowid`.
- `CREATE TABLE t (..., name TEXT PRIMARY KEY)` (non-INTEGER PK) — an **auto-index** is created with name `sqlite_autoindex_<table>_1`, on the PK column. The auto-index is used by the equality / range planner (9be / 9d) like any other single-column index. **Uniqueness is NOT enforced in 9f; lands in 9g.**
- Table-level `PRIMARY KEY (col)` constraint — equivalent to column-level `PRIMARY KEY`. Single column only in v1.
- `DROP INDEX <name>` — remove a user-declared index. Error if name unknown.
- `DROP INDEX IF EXISTS <name>` — no-op if name unknown.
- Error: `DROP INDEX sqlite_autoindex_*` raises `COMPILE_CANNOT_DROP_AUTO_INDEX { name }`.

**OUT (deferred):**
- Multi-column PRIMARY KEY.
- `UNIQUE` constraint enforcement — Phase 9g.
- `CREATE INDEX IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS` — deferred.
- `DROP TABLE` — permanent v1 non-goal.
- `FOREIGN KEY` — v1 non-goal.
- `PRIMARY KEY ASC` / `PRIMARY KEY DESC` (column-ordering hint) — accepted but ignored; ordering is always ASC.

### Grammar additions

```
column-def := IDENTIFIER type-name column-constraint*
column-constraint := KEYWORD_PRIMARY KEYWORD_KEY
                   | ... (future: NOT NULL, UNIQUE, CHECK, DEFAULT ...)

table-constraint := KEYWORD_PRIMARY KEYWORD_KEY LPAREN IDENTIFIER RPAREN

drop-index-stmt := KEYWORD_DROP KEYWORD_INDEX [ KEYWORD_IF KEYWORD_EXISTS ] IDENTIFIER
```

### INTEGER PRIMARY KEY — rowid alias semantics

When a column is declared `INTEGER PRIMARY KEY`:
- The column IS the rowid. Storage does not allocate a separate column slot; reading the column reads the rowid.
- On INSERT, if the user provides a value for this column, it becomes the row's rowid (if NULL or absent, the storage layer auto-assigns a rowid as before).
- Queries of the form `WHERE id = <const>` where `id` is an INTEGER PRIMARY KEY compile to:

```
      Init
      <compile const into key_reg>
      OpenRead       t_cursor, "<t>"
      TableSeekRowid t_cursor, key_reg
      <Column opcodes for projection — note: reading the PK col itself returns the rowid>
      ResultRow      proj_start, proj_count
      Close          t_cursor
      Halt
```

No index cursor is needed. Range queries on INTEGER PRIMARY KEY columns also benefit (table B-tree IS rowid-ordered), though 9f does NOT mandate planner support for range-via-rowid — it is permitted but deferred as a follow-up.

Reading an INTEGER PRIMARY KEY column via standard `Column cursor, col_idx, dest` MUST produce the rowid value as an Integer. Generators implement this by either (a) special-casing the column index to emit a rowid read, OR (b) storing the rowid redundantly in the table cell payload under the declared column. Either is acceptable as long as the observable semantics match; fixtures pin observables.

### Non-INTEGER PRIMARY KEY — auto-index semantics

When a column is declared `<non-INTEGER-type> PRIMARY KEY`:
- An auto-index is created at table-creation time, name `sqlite_autoindex_<table>_1` (following mainline SQLite's naming convention — this is a compat concern for read-back).
- The auto-index is a regular single-column index for planner purposes.
- Equality and range queries use the auto-index via the 9be / 9d planner paths.
- **Uniqueness is NOT enforced in 9f**; duplicate INSERTs succeed silently. Phase 9g will add enforcement.
- Deletion: user cannot `DROP INDEX sqlite_autoindex_*`. The auto-index would only disappear via `DROP TABLE` (not in v1).

### DROP INDEX semantics

```
DROP INDEX [IF EXISTS] <name>;
```

- Parse to AST `DropIndexStatement { name, if_exists }`.
- Compile to VDBE `[Init, DropIndex(name, if_exists), Halt]`.
- Compile-time resolution: the compiler MAY check that the index exists (failing with `COMPILE_UNKNOWN_INDEX` unless `if_exists`), or defer to runtime. Compile-time is preferred for better error messages.
- Runtime: remove the sqlite_schema row for the index, release the index's root page back to the free-page pool, remove the in-memory catalog entry.
- Post-DROP: `WHERE` queries previously using the index fall back to full-scan automatically (the planner re-checks the catalog per compile, and already-compiled programs are not cached across DDL in v1).

### Auto-index naming

The canonical name is `sqlite_autoindex_<table-name>_<N>` where `<N>` is 1 for the first auto-index, 2 for the second, etc. For v1 (single-col PK only), `<N>` is always 1 per table. This name is exact-match with mainline SQLite for bidirectional file-format compat: a leap-produced DB with a PK column is readable by mainline as an indexed table.

### Phase 9f error conditions

- `COMPILE_PRIMARY_KEY_CONFLICT { table }` — more than one PRIMARY KEY declared on a single CREATE TABLE.
- `COMPILE_UNKNOWN_INDEX { name }` — DROP INDEX on non-existent name without IF EXISTS.
- `COMPILE_CANNOT_DROP_AUTO_INDEX { name }` — DROP INDEX on a `sqlite_autoindex_*` name.
- `STORAGE_INDEX_NOT_FOUND { name }` — runtime counterpart of COMPILE_UNKNOWN_INDEX (if the compiler deferred).
- All existing errors propagate unchanged.

### Phase 9f non-goals (restated)

- Multi-column PK.
- UNIQUE enforcement (→ 9g).
- CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS — deferred.
- DROP TABLE — permanent non-goal.
- FOREIGN KEY — permanent non-goal.

### Test authority (Phase 9f)

`tests/cross-build/phase9f.json` is the executable specification for Phase 9f. All prior phase fixtures MUST stay green.

### Phase 9f retroactive spec pins (2026-04-18, post-landing)

1. **INTEGER PRIMARY KEY column read: write-back on INSERT is canonical.** Both generators converged on option (b): on INSERT, the assigned/extracted rowid is written **both** to the row's rowid AND redundantly into the declared PK column slot. Reading via standard `Column cursor, pk_col_idx, dest` naturally returns the rowid. No `Column` opcode special-casing required.
   - **Why pinned:** simpler in both C and Rust; composes with every existing projection / ORDER BY / WHERE / JOIN path.

2. **INTEGER PRIMARY KEY equality lookup: guarded full-scan is acceptable.** Both generators emitted a `Rewind` + `Column` + `Eq` + `JumpIfFalse` shape rather than `TableSeekRowid`. Reason: existing `TableSeekRowid` raises `STORAGE_CORRUPT_INDEX_REFERENCE` on miss (necessary for the 9c index→table bridge), which is wrong for user-level `WHERE pk = <const>` where a missing rowid must produce an empty result-set.
   - **Resolution:** fixtures pin observables; opcode shape is generator-choice. The pseudo-code in § "INTEGER PRIMARY KEY — rowid alias semantics" is advisory.
   - **Perf gap logged:** direct-rowid-seek performance for user-level PK equality is currently unavailable. A future miss-tolerant opcode (e.g. `TableSeekRowidOrJump { cursor, rowid_reg, jump_if_missing }`) would unlock the fast path. Not required for 9f correctness.

## Phase 9g — UNIQUE enforcement

Phase 9g lights up uniqueness enforcement on `UNIQUE` indexes and on non-INTEGER PRIMARY KEY auto-indexes. No new opcodes. No new invariants. Two new error kinds. Grammar extended with `UNIQUE` column constraint and `UNIQUE` in CREATE INDEX.

### Phase 9g scope

**IN (v1):**
- `CREATE UNIQUE INDEX idx ON t(col)` — creates an index flagged `unique=true`. Planner uses it like any other index for equality/range; storage layer rejects duplicate-key inserts.
- `CREATE TABLE t (col TYPE UNIQUE)` — the column-level UNIQUE constraint creates an auto-index `sqlite_autoindex_<table>_<N>` with `unique=true`.
- Non-INTEGER PRIMARY KEY auto-index (from 9f) now has `unique=true` — PK uniqueness enforced.
- INSERT duplicate-key raises `STORAGE_UNIQUE_VIOLATION { index, key }` — no row inserted, no partial index state.
- UPDATE that would duplicate a key raises `STORAGE_UNIQUE_VIOLATION` — per-row fail-fast (statements that have partially mutated earlier rows leave those earlier rows updated; full statement atomicity comes with WAL / Phase 4).
- `CREATE UNIQUE INDEX` on a populated table with duplicate values raises `STORAGE_UNIQUE_BACKFILL_VIOLATION { index, key }` — the index is NOT created.
- NULL values do NOT violate UNIQUE (SQLite convention): multiple rows with NULL in the UNIQUE column are permitted.

**OUT (deferred):**
- Full-statement atomic rollback on mid-statement violation — lands with WAL / Phase 4. Current 9g semantics: rows mutated before the failing row stay mutated.
- Multi-column UNIQUE (`UNIQUE (a, b)` table-constraint) — deferred; single-col only.
- `INSERT ... ON CONFLICT REPLACE/IGNORE/...` — permanent v1 non-goal (adds a large grammar surface for marginal gain).

### Grammar additions

```
column-constraint := KEYWORD_PRIMARY KEYWORD_KEY
                   | KEYWORD_UNIQUE
                   | ...

create-index-stmt := KEYWORD_CREATE [ KEYWORD_UNIQUE ] KEYWORD_INDEX IDENTIFIER
                     KEYWORD_ON IDENTIFIER LPAREN IDENTIFIER RPAREN
```

(UNIQUE is already a reserved keyword from Phase 9a; 9g just wires it into the CREATE INDEX + column-constraint productions.)

### Phase 9g NULL semantics

Under SQL standard interpretation, `NULL ≠ NULL` (3VL). SQLite departs from strict standard here in a pragmatic way: NULL values in a UNIQUE column are permitted without triggering a violation, regardless of how many NULL rows exist. This matches mainline SQLite behaviour and is the compatibility target.

Concretely:
- `IdxInsert` on a UNIQUE index: if ANY indexed-col value is NULL, skip the uniqueness probe entirely. The cell is inserted. Multiple such NULL cells can coexist.
- `CreateIndex` UNIQUE backfill: NULL-keyed cells are excluded from the adjacent-duplicate scan.
- Equality-planner lookups using the UNIQUE index with a NULL probe key: 3VL still applies (probe key NULL → empty result, per 9be NULL-key short-circuit).

### Phase 9g error conditions

- **`STORAGE_UNIQUE_VIOLATION { index, key }`** (NEW): INSERT or UPDATE attempted to write a duplicate non-NULL key into a UNIQUE index. Halts execution. Table-side row state: not inserted (INSERT) or pre-mutation (UPDATE — the violating row's update is aborted, earlier rows in the UPDATE loop remain updated).
- **`STORAGE_UNIQUE_BACKFILL_VIOLATION { index, key }`** (NEW): CREATE UNIQUE INDEX found duplicate non-NULL values during backfill. The index is not created. Table data is unchanged.
- All existing 9a/9be/9c/9d/9f errors propagate unchanged.

### Phase 9g pre-insert ordering

For any INSERT on a table with ≥ 1 UNIQUE index: the VDBE emits all UNIQUE-index `IdxInsert` opcodes BEFORE any non-UNIQUE-index `IdxInsert`. This ensures that if the INSERT fails on uniqueness, no non-UNIQUE indexes have been touched, leaving the catalog consistent without needing a revert. Generators SHOULD follow this ordering; fixtures pin observable semantics (successful inserts show up in ALL indexes; failed uniqueness leaves ALL indexes unchanged for that row).

For UPDATE: within a single row's maintenance, ordering is: (1) IdxDelete old for each affected index (both UNIQUE and non-UNIQUE), (2) IdxInsert new for each UNIQUE index — may raise, (3) IdxInsert new for each non-UNIQUE index. This ensures step 2's uniqueness probe excludes the old cell (already deleted) from the match set, so `UPDATE t SET x = x` (no-op on indexed col) doesn't self-conflict.

### Phase 9g atomicity caveat (pre-WAL)

- Single-row INSERT: clean — uniqueness violation raises before any mutation.
- UPDATE of N rows where row K violates: rows 1..K-1 were successfully updated; row K's old-index-cell was deleted before the violation-raising IdxInsert (per § "pre-insert ordering" above); row K's table cell is not mutated. Index state for row K: OLD cells DELETED, NEW cells NOT INSERTED — row K is effectively un-indexed after the violation. **This is a known non-atomicity, documented and accepted for v1 until WAL lands.** Fixtures either (a) test single-row UPDATE where the diagnosis is clean, or (b) test multi-row UPDATE without uniqueness conflicts.

### Phase 9g non-goals (restated)

- Multi-column UNIQUE.
- ON CONFLICT clauses.
- Full-statement atomic rollback — WAL / Phase 4.
- `UNIQUE` index read from mainline-written DBs — the flag is stored in sqlite_schema's `sql` text; read-back relies on re-parsing the CREATE statement. Bidirectional compat assumes both sides re-parse CREATE text (this is how mainline does it); covered by round-trip harness when UNIQUE fixtures land there.

### Test authority (Phase 9g)

`tests/cross-build/phase9g.json` is the executable specification for Phase 9g. All prior phase fixtures MUST stay green.

### Phase 9g retroactive spec pins (2026-04-18, post-landing)

1. **UNIQUE probe lives at the storage layer (`insert_row`), not purely in `IdxInsert` opcode reordering.** Both generators independently discovered that the original spec's "UNIQUE IdxInsert before non-UNIQUE IdxInsert" ordering pin is insufficient: `InsertRow` must precede any `IdxInsert` (because `IdxInsert` needs the rowid assigned by `InsertRow`), so per-opcode reordering alone still leaves the table row inserted BEFORE the uniqueness check fires. Fixture `unique-insert-violation-preserves-original-row` requires "no row visible after violation".
   - **Resolution:** storage-layer `insert_row` performs a UNIQUE probe across all UNIQUE indexes on the target table BEFORE committing the row. If any UNIQUE index has a matching non-NULL key, raise `STORAGE_UNIQUE_VIOLATION` with zero table-side mutation.
   - **Consequence:** `IdxInsert` on UNIQUE indexes can retain its probe as defense-in-depth, but in the INSERT path the opcode-level probe is now redundant (the storage check already caught it). In the UPDATE path (IdxDelete + IdxInsert), the opcode-level probe is still load-bearing because the storage `insert_row` isn't on the code path.
   - **Pin location:** `parts/storage/master.md` should document `insert_row`'s responsibility to probe UNIQUE indexes pre-commit.

2. **INTEGER PRIMARY KEY duplicate collision surfaces as `STORAGE_UNIQUE_VIOLATION`.** Both generators resolved this by having `insert_row` scan existing rowids when the table has an INTEGER PK and the incoming row has an explicit integer-valued PK. On collision, raise `STORAGE_UNIQUE_VIOLATION` with `index: "sqlite_autoindex_<table>_1"` (synthesised — there's no actual sqlite_autoindex index for INTEGER PK, but the error naming convention stays consistent with non-INTEGER PK's real auto-index).
   - **Fixture gating:** `integer-primary-key-duplicate-rejected` only pins the error name, not the `index` field. Both generators produce compatible output.

### Phase 9g recurring cross-corroboration signal — synthetic identifier ownership

Multiple phases (9be, 9c, 9f, 9g) have required the Rust generator to use `Box::leak` or equivalent owned-string escape hatches when synthesising identifiers like `sqlite_autoindex_<table>_<N>` that don't live in the SQL source buffer. The C generator doesn't have lifetime issues but ends up synthesising the same names with ad-hoc storage. This is a cross-cutting issue, not a phase-specific one.

**Spec note for future refactor:** the opcode-level identifier channel should be formalized as either (a) `Cow<str>`-equivalent (borrowed OR owned) in both generators, or (b) a side-table of owned identifiers addressed by index, indirected through a compile-time-assigned id. This is deferred to a post-9g cleanup pass; no fixture changes required.

## Phase 6r (IMPLEMENTATION) — Real→Text via fixed 17-digit scientific notation

Following the Phase 6r design-spike above, Stan selected Option D variant: **fixed-width deterministic scientific notation**, 17 significant digits, signed 2+ digit exponent. Trades SQLite-output-parity for cross-build byte-identity. All Real-producing casts and concatenations now have well-defined Text output.

### Algorithm (normative)

```
f64_to_text(v):
  if v is NaN:
    raise VDBE_UNSUPPORTED_CAST { from_kind: "Real", to_kind: "Text", reason: "NaN" }
  if v is +Inf or -Inf:
    raise VDBE_CAST_OVERFLOW { value: "Inf" }
  if v == 0.0:            # positive and negative zero both
    return "0.0"
  # Finite, non-zero case
  sign = "-" if v < 0.0 else ""
  u = abs(v)
  # Compute 17-significant-digit mantissa and integer exponent such that:
  #   u ≈ mantissa_digits × 10^(exp - 16)
  # where mantissa_digits is a 17-digit integer in [10^16, 10^17).
  # Exponent `exp` in the output is the power of 10 such that the
  # mantissa-with-decimal-point-after-first-digit × 10^exp ≈ u.
  (mantissa_digits, exp) = scale_to_17_digits(u)
  # Render: first digit, '.', remaining 16 digits
  s_mantissa = digit_at(mantissa_digits, 0) + "." + digits_1_through_16(mantissa_digits)
  # Exponent: always signed, always at least 2 digits
  s_exp_sign = "+" if exp >= 0 else "-"
  s_exp_digits = pad_left(abs(exp), width=2, pad='0')
  return sign + s_mantissa + "e" + s_exp_sign + s_exp_digits
```

### scale_to_17_digits(u) — the algorithmic core (2026-04-18 retroactive pin)

Given `u > 0` finite f64, produce a 17-significant-digit decimal mantissa with round-half-to-even on the 17th digit, and an integer exponent.

**Canonical implementation: delegate to the host language's correctly-rounded 17-significant-digit scientific formatter.** Both C's `snprintf("%.16e", v)` (C99+) and Rust's `format!("{:.16e}", v)` (core::fmt Grisu+Dragon4) produce correctly-rounded 17-digit output with matching mantissa bytes. The only divergence is exponent format:

- C's `%.16e`: always-signed, min 2 exponent digits. `1.0000000000000000e+00`, `1.0000000000000000e+100`, `1.0000000000000001e-09`.
- Rust's `{:.16e}`: no sign on positive, no padding. `1.0000000000000000e0`, `1.0000000000000000e100`, `1.0000000000000001e-9`.

Both generators MUST post-process the output to produce the C-style exponent form: split on `'e'`, take the exponent integer, render as `"e"` + `("+" or "-")` + `pad_left(abs(exp), width=2, pad='0')` (3+ digits naturally if |exp| ≥ 100).

**Why this is canonical.** A hand-rolled f64 scale-and-round algorithm loses 1–2 digits of precision at the extremes (log10 approximation + scaling error). The host language's formatter is correctly-rounded to the last digit — matching this is the only way fixture pins can be hand-computed from the IEEE 754 bit-pattern of the input without a bignum implementation.

**Historical note.** The original Phase 6r spec (2026-04-18 morning) proposed a hand-rolled f64 scale-and-round. Both generators independently discovered this produces different last-digit output for several cases (0.1, 3.14, 6.022e23, 1e-9), while the language stdlib's correctly-rounded formatter matches the f64 bit-pattern exactly. The retroactive pin (this section) replaces the scale-and-round sketch with "delegate to correctly-rounded stdlib + normalize exponent format". Fixture pins align with the stdlib path.

### Pin exact bytes for canonical reals

| Input (f64 literal) | Expected Text output |
|---|---|
| `0.0` | `"0.0"` |
| `-0.0` | `"0.0"` (positive and negative zero collapse) |
| `1.0` | `"1.0000000000000000e+00"` |
| `-1.0` | `"-1.0000000000000000e+00"` |
| `2.0` | `"2.0000000000000000e+00"` |
| `10.0` | `"1.0000000000000000e+01"` |
| `0.1` | `"1.0000000000000001e-01"` (f64 rep of 0.1 is 0.1000000000000000055...) |
| `3.14` | `"3.1400000000000001e+00"` (f64 rep: 3.1400000000000001243...) |
| `1e100` | `"1.0000000000000000e+100"` |
| `1e-100` | `"1.0000000000000000e-100"` |
| `6.022e23` | `"6.0220000000000000e+23"` (rounded at 17 digits) |

### Grammar / opcode changes

No new opcodes. `VDBE_UNSUPPORTED_CAST` restriction in Phase 6i is lifted for `Real → Text`. The `Scalar { kind: ScalarKind::CastText, ... }` opcode path now handles Real input by invoking `f64_to_text`. The `Concat` opcode (Phase 6q) invokes `f64_to_text` when a Real operand needs coercion.

### Phase 6r fixtures

`tests/cross-build/phase6r.json` — ~25 fixtures covering each row of the canonical-bytes table above plus edge cases (subnormals, very-large-exp, integer-valued reals, Real + Text concat, CAST Real AS TEXT in WHERE, etc.).

### Phase 6r non-goals (after this pin)

- Exact SQLite-output parity (SQLite emits `"0.1"` not `"1.0000000000000001e-01"`). This is deliberate — cross-build identity > mainline-output parity.
- Bignum-correct last-digit accuracy. f64 arithmetic is canonical; minor last-digit drift vs mainline is acceptable.
- NaN pass-through. NaN is rejected at value-construction time per 6g.
- Subnormal handling is NOT special-cased; scale_to_17_digits handles them identically to normal values (some may have reduced effective precision but still produce a 17-digit representation).

### Test authority (Phase 6r)

`tests/cross-build/phase6r.json` is the executable specification. All prior phase fixtures MUST stay green.

---

## Phase 6u — `IS NULL` / `IS NOT NULL` postfix operators

Phase 6u adds the two SQL postfix null-test operators. Lifts the Phase 2c-1 deferral of `IS NULL` / `IS NOT NULL`. No new tokens (reuses existing `KEYWORD_IS`, `KEYWORD_NOT`, `KEYWORD_NULL`). No new VDBE opcodes — `IS NULL` lowers to `IsNull` if available, or is implemented by compiling the sub-expression to a register then branching on `Value::Null` via existing JumpIfFalse plumbing (implementation-choice). `max_invariant` unchanged (= 42).

### Phase 6u tokens

No new tokens. `KEYWORD_IS` must be added as a reserved keyword if not already present — check before adding. `KEYWORD_NOT` and `KEYWORD_NULL` are already reserved from Phases 2c-2 and 2a respectively.

### Phase 6u grammar

Extend the `expression` grammar at the comparison level:

```
comparison     := additive [ cmp-op additive | null-test ]
null-test      := KEYWORD_IS [ KEYWORD_NOT ] KEYWORD_NULL
```

Postfix (left-associative). Binding tighter than AND/OR but looser than `=`/`<`/etc. Therefore `x IS NULL AND y = 1` parses as `(x IS NULL) AND (y = 1)`.

### Phase 6u semantics

- `x IS NULL` evaluates to `Integer(1)` if `x` is `Null`, else `Integer(0)`.
- `x IS NOT NULL` evaluates to `Integer(1)` if `x` is NOT `Null`, else `Integer(0)`.
- UNLIKE `x = NULL` (which yields `Null` per SQL 3VL), `IS NULL` ALWAYS yields a non-NULL boolean (0 or 1). This is the canonical SQL convention.

### Phase 6u compile

Either generator may implement via one of:
- **(a)** A new AST node `NullTest { expr, negated: bool }` compiled to a sub-expression evaluation + a `JumpIfFalse` on a register holding `IsNull`-test result. If no dedicated IsNull-result opcode exists, use a pair of `LoadConst 0`/`LoadConst 1` with a conditional jump.
- **(b)** Desugar at parse time: `x IS NULL` → a specific AST marker that the compiler lowers to the same opcode sequence without introducing a new AST kind.

Both are spec-permitted. Cross-language byte-identical output is NOT required at the opcode-sequence level for internal 6u plumbing — fixtures check OUTPUT rows only.

### Phase 6u errors

No new errors. Subexpression errors propagate unchanged.

### Phase 6u non-goals

- `IS DISTINCT FROM` / `IS NOT DISTINCT FROM` — future.
- `IS <expr>` (general IS with non-NULL RHS) — future.

### Test authority (Phase 6u)

`tests/cross-build/phase6u.json` is the executable specification. All prior phase fixtures MUST stay green.

### Phase 6u retroactive pin (2026-04-19, post-landing) — cross-corroboration finding

Both C and Rust agents **independently converged** on the same implementation workaround: desugar `x IS NULL` to a dual-IFNULL-sentinel pattern that compares `IFNULL(x, A)` vs `IFNULL(x, B)` with distinct constants `A ≠ B`. The two expressions differ iff `x` is `Null`. Existing `Scalar2::Ifnull` + `Eq` / `Ne` opcodes cover this; no dedicated `IsNull` opcode is needed.

The Rust agent's commit even **explicitly predicted the cross-corroboration signal**: "if the C generator independently reaches for the same pair-of-IFNULLs workaround, that's the spec-bug signal to promote a dedicated `IsNull` opcode into the language-neutral table."

C did reach for the same workaround. That's the signal.

**Pin**: the dual-IFNULL-sentinel desugar is SPEC-BLESSED for v1 Phase 6u. Implementations MAY use it as the canonical lowering, OR MAY introduce a dedicated `IsNull { arg, dest, negated }` opcode as a future optimization (saves one `LoadConst` and two `Scalar2` calls per null-test — profile-gated, not required). The `max_invariant=42` cap is preserved until such an opcode is introduced.

**Why the spec's original hint was wrong**: the spec suggested "branch on `Value::Null` via existing `JumpIfFalse` plumbing." But `JumpIfFalse` raises `EVAL_TYPE_ERROR` on TEXT operands, which would break the `'x' IS NULL → 0` fixture. IFNULL is the only v1 opcode that inspects Null without type-checking. Both agents discovered this the same way; spec hint now retracted.

---

## Phase 6v — `IN (expr-list)` operator

Phase 6v adds the `IN (list)` predicate with an explicit expression list. Lifts the Phase 2c-1 deferral of `IN`. No new VDBE opcodes. No new tokens except the `IN` keyword if it isn't already reserved. `max_invariant=42` unchanged. The subquery form `x IN (SELECT ...)` is OUT OF SCOPE for 6v (belongs to a later subquery phase).

### Phase 6v tokens

Add `KEYWORD_IN` as a reserved keyword if not already present.

### Phase 6v grammar

Extend the `expression` grammar at the comparison level:

```
comparison     := additive [ cmp-op additive | null-test | in-list ]
in-list        := [ KEYWORD_NOT ] KEYWORD_IN LPAREN expression ( COMMA expression )* RPAREN
```

Postfix on `additive`. `x IN (a, b, c)` and `x NOT IN (a, b, c)` are both accepted; `NOT IN` is a two-token phrase where the leading `NOT` is peeked at the `IN`-parse position.

`IN ()` with an empty list is REJECTED at parse time with `PARSE_UNEXPECTED_TOKEN { kind: RPAREN }` — at least one expression required.

### Phase 6v semantics

- `x IN (a, b, c)` evaluates each element left-to-right. If any element compares EQUAL to `x` (**per the IN-equality rules below, NOT the `=` operator's rules**), result is `Integer(1)` and remaining elements are short-circuited. If no element compares equal AND no comparison produced Null, result is `Integer(0)`.
- **NULL semantics (SQL 3VL):**
  - If `x` is Null, result is `Null` (regardless of list contents).
  - If any element is Null AND no other element matched, result is `Null` (not `0`).
  - If a non-Null element matches first, result is `1` (short-circuit; the trailing Nulls don't matter).
- `x NOT IN (a, b, c)` is the negation: `Integer(1)` iff `x IN (...)` would have been `Integer(0)`; `Integer(0)` iff it would have been `Integer(1)`; `Null` iff it would have been `Null`.

#### IN-equality rules (⚠ retroactively pinned 2026-04-19 after cross-corroboration event)

`IN` equality is **NOT** identical to the `=` operator. Specifically: where `x = y` on cross-type non-Null operands (e.g. `1 = '1'`) **raises `EVAL_TYPE_ERROR`**, `x IN (...)` on the same cross-type pair **yields `0`** (no match, no error). This is the weaker, error-suppressing cross-type compare already used internally by DISTINCT / sort deduplication.

Concretely:

| `x` | element `e` | `x = e` | `x IN (e)` |
|-----|-------------|---------|------------|
| `Integer(1)` | `Integer(1)` | `1` | `1` |
| `Integer(1)` | `Text("1")` | **error** | `0` |
| `Null` | any | `Null` | `Null` |
| any | `Null` | `Null` | `Null` |
| `Integer(1)` | `Integer(2)` | `0` | `0` |

**Cross-corroboration history (2026-04-19):** the original spec said "same rules as `=`" and suggested option (a) (desugar to OR-chain of `=`) as a clean lowering. **Both C and Rust generators independently discovered this was wrong** when compiling fixture `in-list-mixed-types-no-coercion`: `SELECT 1 IN ('1', '2')` expects `[[0]]`, but `OP_EQ` raises type error on `Integer(1) = Text("1")`. C worked around via parse-time literal-pair cross-type elision; Rust worked around via a dedicated `InList` AST node compiled against `SortValueEq`. The underlying bug is the spec, not the engines. This pin makes the intended semantics authoritative.

### Phase 6v compile

Recommended: **option (b) — dedicated lowering** that uses an error-suppressing cross-type compare (e.g. `SortValueEq`). Option (a) — desugar to an OR-chain of `=` — is **spec-LEGAL only if the generator's `=` matches IN-equality rules on cross-type literals** (i.e. produces `0` not error). Current v1 `OP_EQ` does NOT, so option (a) requires either (i) a parse-time literal-pair elision pass (C's approach) or (ii) a new `OP_EQ_NOERR` variant. Option (b) is simpler.

Cross-build output must match on fixtures; opcode sequences may differ.

### Phase 6v errors

No new errors. Element-evaluation errors propagate unchanged.

### Phase 6v non-goals

- `x IN (SELECT ...)` — subquery-source IN, deferred.
- `x IN (table_alias)` — table-as-value-list form, deferred.
- Optimized IN against a HASH or SORTED set — v1 is linear scan, fine for small lists.

### Test authority (Phase 6v)

`tests/cross-build/phase6v.json` is the executable specification. All prior phase fixtures MUST stay green.

---

## Phase 6w — multi-row `INSERT INTO … VALUES (…), (…), (…)`

Phase 6w widens the INSERT grammar to accept multiple value-tuples separated by commas. No new tokens. No new VDBE opcodes. `max_invariant=42` unchanged.

### Phase 6w grammar

Existing (single-tuple) INSERT production:

```
insert-statement := KEYWORD_INSERT KEYWORD_INTO IDENTIFIER
                    KEYWORD_VALUES values-tuple
values-tuple     := LPAREN expression ( COMMA expression )* RPAREN
```

Widened to:

```
insert-statement := KEYWORD_INSERT KEYWORD_INTO IDENTIFIER
                    KEYWORD_VALUES values-tuple ( COMMA values-tuple )*
```

Note the comma BETWEEN tuples. Each tuple is itself a parenthesized comma-separated expression list.

### Phase 6w semantics

- N tuples, M columns each. Every tuple must have the same M (all tuples match the table's column count, same check as today).
- Tuples are evaluated and inserted IN ORDER (left-to-right).
- If insertion of tuple K fails (e.g., UNIQUE violation), tuples 1..K-1 have already been inserted AND REMAIN inserted (non-atomic multi-row insert). This matches the Phase 9g atomicity caveat for multi-row UPDATE. Pre-WAL semantics.
- Error messages for column-count mismatch name the OFFENDING TUPLE's index (1-based) in the `reason` field when possible.

### Phase 6w compile

Lower to a repeated sequence of the existing single-tuple INSERT opcode plan, once per tuple. The compiled VDBE program is longer by a factor of N.

This is pure grammar+compiler repetition; no new opcodes, no new invariants.

### Phase 6w errors

- `COMPILE_INSERT_COLUMN_COUNT_MISMATCH { table, expected, got }` — reused from existing single-tuple form. May gain an optional `tuple_index` field (1-based) when the offending tuple is not the first; omitted when it IS the first (back-compat with existing fixtures).

### Phase 6w non-goals

- `INSERT INTO t (col1, col2) VALUES ...` (column-list form) — separate phase.
- `INSERT INTO t SELECT ...` (INSERT-from-SELECT) — separate phase.
- Atomic multi-row insert with rollback on mid-sequence failure — Phase 4b/c (WAL-dependent).

### Test authority (Phase 6w)

`tests/cross-build/phase6w.json` is the executable specification. All prior phase fixtures MUST stay green, including the Phase 9g UNIQUE enforcement fixtures (multi-row INSERT interacting with UNIQUE constraint).

---

## Phase 6x — `LIKE` pattern matching

Phase 6x adds the SQL `LIKE` operator with its two canonical wildcards: `%` (zero-or-more characters) and `_` (exactly one character). Byte-level matching over UTF-8 strings — NOT grapheme-aware. No ESCAPE clause (deferred). No GLOB (deferred). **One new VDBE opcode kind `Scalar2::Like` pinning invariant 43; `max_invariant=43`.** One new reserved keyword: `KEYWORD_LIKE`.

### Phase 6x tokens

Add `KEYWORD_LIKE` to the reserved keyword table.

### Phase 6x grammar

Extend the `comparison` production with an optional postfix `like-test`:

```
comparison     := additive [ cmp-op additive | null-test | in-list | like-test ]
like-test      := [ KEYWORD_NOT ] KEYWORD_LIKE additive
```

Postfix on `additive`. Both `x LIKE pat` and `x NOT LIKE pat` are accepted.

### Phase 6x semantics

- Operands MUST be Text. Non-Text operands (including Integer, Real, Null) make the result Null (SQL 3VL).
- Pattern is a Text string with two special characters:
  - `%` (byte `0x25`) matches zero or more bytes.
  - `_` (byte `0x5F`) matches exactly one byte.
  - All other bytes (including multibyte UTF-8 sequences) match themselves byte-exactly.
- Case-sensitive (SQLite's default behavior; ICU / NOCASE collation is out-of-scope).
- Result:
  - `Integer(1)` if the entire subject string matches the pattern.
  - `Integer(0)` if no match.
  - `Null` if either operand is Null or non-Text.
- `x NOT LIKE pat` is the negation: `Integer(1)` iff `x LIKE pat` is `0`; `Integer(0)` iff `1`; `Null` iff `Null`.

### Phase 6x matching algorithm (reference)

Standard pattern-matching with backtracking. Either generator may implement via:
- A per-character state machine with explicit backtracking on `%`.
- A recursive descent.
- Any algorithm that gives the same result on every fixture.

This is spec-permitted generator freedom. The byte-matching rules are what's canonical.

### Phase 6x compile

Either generator may:
- **(a)** Introduce a `Scalar2::Like` opcode variant. Small addition to `Scalar2Kind` (like Ifnull). Invariant budget: invariant 43, `max_invariant=43`.
- **(b)** Desugar via a dedicated compile-time path emitting existing string-test opcodes — BUT no current opcode handles `%`/`_` wildcards, so this option is impractical. Option (a) is the realistic choice.

Option (a) is RECOMMENDED. This will be the first new opcode since Phase 9f's `DropIndex` (invariant 42).

### Phase 6x errors

No new errors. Type-mismatch behavior yields Null (3VL), not an error.

### Phase 6x non-goals

- `ESCAPE` clause (`x LIKE 'foo\%' ESCAPE '\'`) — future.
- `GLOB` operator — future.
- `NOCASE` / `BINARY` / `RTRIM` collation variants — future.
- ICU / Unicode-aware matching — future.

### Test authority (Phase 6x)

`tests/cross-build/phase6x.json` is the executable specification. All prior phase fixtures MUST stay green.

---

## Phase 6y — `CASE` expression (simple and searched forms)

Phase 6y adds SQL's `CASE ... WHEN ... THEN ... [ELSE ...] END` conditional expression in both forms:

- **Searched CASE**: `CASE WHEN cond1 THEN r1 [WHEN cond2 THEN r2 ...] [ELSE rE] END`
- **Simple CASE**: `CASE expr WHEN v1 THEN r1 [WHEN v2 THEN r2 ...] [ELSE rE] END`

No new VDBE opcodes. `max_invariant=43` unchanged. Two new reserved keywords: `KEYWORD_CASE`, `KEYWORD_WHEN`, `KEYWORD_THEN`, `KEYWORD_ELSE`, `KEYWORD_END` — add any not already reserved from prior phases (`END` is already used by `COMMIT`/`END`-transaction in Phase 6t and stays one token; `ELSE` also reused if prior phases added IF-LIKE semantics; net-new keywords are `CASE`, `WHEN`, `THEN`).

### Phase 6y tokens

Add `KEYWORD_CASE`, `KEYWORD_WHEN`, `KEYWORD_THEN`. Reuse `KEYWORD_ELSE` and `KEYWORD_END` if already present; else add. All case-insensitive.

### Phase 6y grammar

Extend the `expression` grammar at the `primary` level (same as parenthesized-expr, literal, function-call):

```
primary       := ... | case-expr
case-expr     := KEYWORD_CASE [ expression ] when-clause+ [ KEYWORD_ELSE expression ] KEYWORD_END
when-clause   := KEYWORD_WHEN expression KEYWORD_THEN expression
```

At least one `WHEN` clause is required. If the leading `expression` between `CASE` and the first `WHEN` is present, it's the **simple** form; absent, it's the **searched** form.

### Phase 6y semantics

**Searched CASE**: evaluate each `WHEN` condition left-to-right:
- If `cond_i` evaluates to `Integer(1)` (truthy), result is `r_i`; remaining WHENs skipped.
- If `cond_i` is `Integer(0)` or `Null`, continue to next WHEN.
- If no WHEN matched and `ELSE rE` present, result is `rE`.
- If no WHEN matched and `ELSE` absent, result is `Null`.

**Simple CASE** `CASE x WHEN v1 THEN r1 ... END`:
- Evaluate `x` once.
- For each WHEN clause, evaluate `v_i` and compare to `x` using the `=` operator's rules (3VL; cross-type behavior per `OP_EQ`).
- If `x = v_i` yields `Integer(1)`, result is `r_i`.
- If `x` is Null: simple-CASE comparison is always Null → falls through to ELSE (or Null).
- If `v_i` evaluation raises an error (cross-type type error), that error propagates (same as using `=` directly).

The simple form is semantically equivalent to the searched form with each `WHEN v_i` replaced by `WHEN x = v_i` — **but** `x` is only evaluated ONCE even in the simple form (important for expressions with side-effects or expensive computations). Compilers MAY cache `x` into a register and emit `x = v_i` comparisons against the cached register.

### Phase 6y compile — reference lowering

**Searched CASE** `CASE WHEN c1 THEN r1 WHEN c2 THEN r2 ELSE rE END` compiles to:

```
evaluate c1 into reg_cond
JumpIfFalse reg_cond -> L_next1   ; jumps on Null too
evaluate r1 into reg_result
Jump -> L_done
L_next1:
evaluate c2 into reg_cond
JumpIfFalse reg_cond -> L_next2
evaluate r2 into reg_result
Jump -> L_done
L_next2:
evaluate rE into reg_result       ; if ELSE absent: LoadConst Null into reg_result
L_done:
```

`JumpIfFalse` already treats `Null` as "don't take branch" / "skip this THEN" when used in a boolean-predicate role here — matching SQL's 3VL semantics: Null condition means "skip this WHEN."

**Simple CASE** is desugared at compile time to searched CASE over `=` comparisons, caching the scrutinee in a register:

```
evaluate x into reg_x          ; ONCE
CASE WHEN reg_x = v1 THEN r1 WHEN reg_x = v2 THEN r2 ... ELSE rE END
```

This avoids re-evaluating side-effects of `x`. Each generator is free to either:
- **(a)** Desugar at parse time to the above searched form (simpler, reuses searched-case codegen).
- **(b)** Keep simple-CASE as a distinct AST node and compile with the cache-register directly.

Both spec-legal. Cross-build output must match on fixtures.

### Phase 6y errors

No new error names. Evaluation errors propagate unchanged. Parse errors use existing `PARSE_UNEXPECTED_TOKEN`.

### Phase 6y non-goals

- `CASE` as a **statement** (PL/pgSQL style) — out of scope; this is the expression form only.
- Result-type unification across arms — each arm's result value is emitted as-is; no implicit coercion.
- Exhaustiveness checking — missing `ELSE` legitimately yields `Null`, not an error.

### Test authority (Phase 6y)

`tests/cross-build/phase6y.json` is the executable specification. All prior phase fixtures MUST stay green.

---

## Phase 6aa — non-recursive Common Table Expressions (`WITH … AS`)

Phase 6aa adds `WITH name AS (select-statement) [, name AS (select-statement)]* <outer-statement>` — the SQL:1999 non-recursive CTE. Recursive CTEs (`WITH RECURSIVE …`) are OUT OF SCOPE for v1; deferred to a later phase.

No new VDBE opcodes expected. `max_invariant=43` unchanged. One new reserved keyword: `KEYWORD_WITH`.

### Phase 6aa tokens

Add `KEYWORD_WITH` if not already reserved.

### Phase 6aa grammar

```
with-prefix      := KEYWORD_WITH cte-binding ( COMMA cte-binding )*
cte-binding      := IDENTIFIER KEYWORD_AS LPAREN select-statement RPAREN
with-statement   := with-prefix ( select-statement | insert-statement | update-statement | delete-statement )
```

A `with-prefix` MUST be followed by exactly one outer statement (SELECT / INSERT / UPDATE / DELETE). A `WITH` clause on its own is a parse error.

Multiple bindings are comma-separated. Each binding introduces a named result-set visible to the **outer statement only**. CTE bindings are NOT visible to each other (no forward or backward references between CTEs in the same WITH-prefix). This is the v1 pin; richer forward-visibility may land in a later phase.

### Phase 6aa semantics

- Each CTE binding evaluates to a materialized result-set named by its IDENTIFIER.
- In the outer statement, the CTE name is referenceable in any position where a regular table name is accepted (FROM clause, JOIN, etc.).
- Name resolution: CTE names SHADOW real table names with the same identifier for the duration of the outer statement.
- If two CTE bindings in the same WITH share an identifier, `PARSE_DUPLICATE_CTE_NAME` at parse time.
- Column names for the CTE are inferred from the select-statement's projection (SQL:1999 optional-column-list is NOT supported in v1 — `WITH x(a, b) AS (...)` is a parse error).
- CTE is evaluated **per outer-statement invocation**, not memoized across invocations.

### Phase 6aa compile

**Recommended lowering (both targets): substitution at resolve-time**, not materialization. Specifically:

- Parser produces a CTE-binding table (`{name: Identifier, definition: SelectAst}`) attached to the outer statement.
- At name-resolution time in the outer statement's compile pass, any `FROM name` / `JOIN name` whose identifier matches a CTE binding is rewritten to `FROM (<definition>) AS name` — i.e., the CTE becomes a subquery in place.
- This reuses all existing Phase 2c / Phase 6 subquery-in-FROM machinery.

Alternative (option b): materialize the CTE into an in-memory ephemeral table at outer-statement start, rewrite references to scans over the ephemeral table. More complex, permits multi-reference deduplication; deferred unless fixtures require it.

If a CTE is referenced MORE THAN ONCE in the outer statement, option (a) re-evaluates the subquery each time. Fine for v1; bench-notable but not correctness-breaking.

### Phase 6aa errors

- `PARSE_DUPLICATE_CTE_NAME { name }` — two bindings in the same WITH share an identifier.
- `PARSE_UNEXPECTED_TOKEN` — malformed syntax (e.g. missing AS, missing RPAREN, trailing comma, WITH not followed by an outer statement).
- No new runtime errors; existing subquery errors propagate.

### Phase 6aa non-goals

- `WITH RECURSIVE` — deferred to dedicated phase.
- Optional column list `WITH x(col1, col2) AS (...)` — deferred.
- CTE forward/backward visibility within the same WITH-prefix — deferred.
- CTEs in DDL (`CREATE TABLE … WITH …`) — out of scope.

### Test authority (Phase 6aa)

`tests/cross-build/phase6aa.json` is the executable specification. All prior phase fixtures MUST stay green.

### Phase 6aa retroactive pins (2026-04-19, after third major cross-corroboration event)

Both C and Rust agents independently discovered that the harness-spec's option (a) framing ("reuses existing subquery-in-FROM machinery") was wrong — neither target had such machinery. Both also independently invented five surface-grammar extensions that the fixtures implicitly required but no prior spec declared. Both chose **option (b) — compile-time materialization of each CTE into a synthetic ephemeral table**, not option (a) substitution.

These are now pinned as part of Phase 6aa's canonical surface:

1. **Projection aliases**: `SELECT expr AS ident` at projection level. Ident captured as the column's output name in CTE result sets. Parse-and-drop for compile purposes outside CTE context. Stored on `SelectCore.projection_aliases` (Rust) / equivalent (C).
2. **Table aliases**: `FROM table alias` or `FROM table AS alias` at FROM sources and JOIN right-hand tables. Alias scopes column-qualified references within the SELECT.
3. **Comma-cross-join**: `FROM a, b` desugared at parse time to `a CROSS JOIN b ON 1` (or equivalent literal-true predicate). No outer-join semantics.
4. **CTE materialization approach (canonical)**: each CTE body evaluates eagerly before outer-statement compile; results land in a synthetic ephemeral table whose name is a harness-generated unique identifier; outer-statement FROM/JOIN references to the CTE's name rewrite to the synthetic-table name. Synthetic tables are CLEANED UP at end-of-statement (both targets MUST do this; avoids schema pollution between statements).
5. **CTE name comparison**: case-sensitive (matches existing table-name comparison convention in both targets).

The harness-spec's option (a) (resolve-time subquery-in-FROM substitution) remains spec-legal but requires the FROM-subquery AST variant that neither target has as of v1. Implementers SHOULD prefer option (b) until a dedicated FROM-subquery phase lands.

**Cross-corroboration strength**: this is the third major event in the same autonomous session (6u IS NULL → dual-IFNULL-sentinel desugar, 6v IN → IN-equality ≠ OP_EQ, 6aa CTEs → five surface extensions + option-(b) canonicalization). Pattern is now reproducibly robust enough that future phases should treat "both agents converged on an unspec'd addition" as a spec-bug signal worth pinning immediately, not a deferred refactor candidate.

---

## Phase 6ab — `INSERT OR {REPLACE|IGNORE}` conflict resolution

Phase 6ab adds two SQLite-flavored conflict-resolution clauses to INSERT:

- `INSERT OR IGNORE INTO t VALUES (…)` — on UNIQUE / PRIMARY KEY conflict, silently skip the offending row; remaining tuples (in a multi-row INSERT) still process.
- `INSERT OR REPLACE INTO t VALUES (…)` — on UNIQUE / PRIMARY KEY conflict, DELETE the conflicting existing row(s), then insert the new row.

No new VDBE opcodes (expected — existing INSERT, UNIQUE-check, and DELETE opcodes suffice with a control-flow branch). `max_invariant=43` unchanged. One new reserved keyword `REPLACE`; `IGNORE` and `OR` may already be reserved — verify and reuse.

### Phase 6ab tokens

`REPLACE` and `IGNORE` are **contextually reserved**, not globally reserved (reconciled 2026-04-20 based on C↔Rust cross-corroboration):

- In the narrow `INSERT OR <ident>` position, `REPLACE` and `IGNORE` are recognized by case-insensitive identifier-text match (or by a token that is contextually emitted and then allowed back into expression/function-call positions).
- Everywhere else, both words remain valid identifiers — critically, `REPLACE(s, from, to)` must parse as a function call (Phase 6ao requires this).

Implementations are free to choose either strategy:
- **Pure-identifier strategy** (C chose this): lexer never emits special tokens; parser matches by text only in the INSERT-prefix position.
- **Reserved-then-re-allowed strategy** (Rust chose this): lexer emits `KEYWORD_REPLACE`/`KEYWORD_IGNORE`; parser explicitly re-admits them in expression/function-call positions via explicit token arms.

Both strategies produce byte-identical cross-build output. `KEYWORD_OR` already reserved (Phase 2c-2 logical OR).

### Phase 6ab grammar

Extend the INSERT statement:

```
insert-statement := KEYWORD_INSERT [ KEYWORD_OR ( KEYWORD_IGNORE | KEYWORD_REPLACE ) ]
                    KEYWORD_INTO IDENTIFIER
                    KEYWORD_VALUES values-tuple ( COMMA values-tuple )*
```

The `OR IGNORE` / `OR REPLACE` clause is optional. If present, it's attached to the INSERT AST node as a `conflict_strategy` field (enum: `Default | Ignore | Replace`). Default means Phase 9g's hard-abort behavior.

No other DML statement takes `OR` clauses in v1 (`UPDATE OR …` and `REPLACE INTO` as synonym for `INSERT OR REPLACE` are both deferred).

### Phase 6ab semantics

**IGNORE strategy, per tuple**:
1. Evaluate tuple expressions into registers.
2. Check UNIQUE constraints (including PRIMARY KEY auto-index from Phase 9f and UNIQUE indexes from Phase 9g).
3. On conflict: skip this tuple. Do NOT emit `InsertRow`. Do NOT emit any index-maintenance opcodes for this tuple. Proceed to next tuple.
4. On no conflict: proceed with normal `InsertRow` + index maintenance.

Multi-row INSERT semantics (Phase 6w): each tuple is independently ignored on conflict. Partial success is expected (this is the whole point of OR IGNORE).

**REPLACE strategy, per tuple**:
1. Evaluate tuple expressions into registers.
2. Check UNIQUE constraints.
3. On conflict: for each constraint that would be violated, DELETE the existing row(s) currently holding the conflicting key(s). Then proceed with normal `InsertRow` + index maintenance.
4. On no conflict: proceed with normal `InsertRow`.

REPLACE may DELETE multiple rows if the new tuple conflicts with multiple UNIQUE constraints. ROWID / PRIMARY KEY conflict deletes the matching row. After deletion, the INSERT proceeds as if the conflict never existed.

**Cascading deletes are NOT triggered** by OR REPLACE in v1 (foreign keys are out of scope; noted for completeness).

### Phase 6ab compile — reference lowering

For each tuple, the compile emits a guarded conflict-detection block:

```
evaluate tuple into registers
for each UNIQUE constraint:
    probe index for conflict
    if conflict:
        if strategy == Ignore: Jump -> next-tuple-label (AND suppress index-maintenance for this tuple — see note below)
        if strategy == Replace: emit DeleteRow(conflicting-rowid) + index cleanup
emit InsertRow + index maintenance
next-tuple-label:
```

**Payload extension** (reconciled 2026-04-20): the existing `InsertRow` opcode's payload is extended with a `conflict_strategy` field (enum `Default | Ignore | Replace`). This is NOT a new opcode kind — it is a new field on the existing opcode. Max-invariant stays unchanged.

**IGNORE index-maintenance suppression** (reconciled 2026-04-20): the simple "jump past the remaining tuple's index-maintenance opcodes" approach is not always sufficient when index-maintenance opcodes are interleaved with other per-tuple work. Implementations must use ONE of these strategies to suppress index-maintenance after an IGNORE-skipped tuple:
- **Control-flow jump**: emit a forward jump from the conflict-detection site over every per-tuple index-maintenance opcode. Requires emit-time label tracking.
- **Runtime-flag suppression**: set a VM-local `last_insert_skipped` flag on IGNORE-skip; index-maintenance opcodes check the flag and become no-ops when set; cleared at start of next tuple.
Both produce byte-identical cross-build output. The spec does not prefer either; C uses the jump approach, Rust uses the flag approach.

Reuses existing UNIQUE-probe machinery (Phase 9g), existing DeleteRow (Phase 2c-3), existing index-maintenance (Phase 9c).

### Phase 6ab errors

No new error names. On Default strategy, `STORAGE_UNIQUE_VIOLATION` fires as before (Phase 9g).

Invalid conflict keywords (e.g. `INSERT OR ROLLBACK INTO t VALUES (1);` — SQLite supports this but we don't in v1) → `PARSE_UNEXPECTED_TOKEN`.

### Phase 6ab non-goals

- `INSERT OR ABORT` / `INSERT OR FAIL` / `INSERT OR ROLLBACK` — deferred.
- `REPLACE INTO t VALUES (…)` as a synonym for `INSERT OR REPLACE INTO t VALUES (…)` — deferred.
- `UPDATE OR {REPLACE|IGNORE}` — deferred.
- Foreign-key cascade semantics triggered by REPLACE — out of scope (FKs are out of scope).
- Conflict resolution for `INSERT INTO t SELECT …` form — deferred (that form may not exist yet in v1; verify).

### Test authority (Phase 6ab)

`tests/cross-build/phase6ab.json` is the executable specification. All prior phase fixtures MUST stay green, especially Phase 9g UNIQUE fixtures and Phase 6w multi-row INSERT fixtures.

---

## Phase 6af — parenthesized type parameters in CREATE TABLE (accept-and-ignore)

Phase 6af extends CREATE TABLE column-definition parsing to **accept-and-ignore** parenthesized integer lists after a column type name. This enables canonical SQL type declarations like `VARCHAR(30)`, `NUMERIC(10, 2)`, `CHAR(8)` without changing type semantics. v1 still treats all types as type-affinity-only — the integer arguments carry no runtime effect.

No new VDBE opcodes. `max_invariant=43` unchanged. No new keywords (LPAREN/RPAREN/INTEGER_LITERAL/COMMA all reserved from prior phases).

### Phase 6af grammar

Extend the column-definition's type production:

```
column-type         := IDENTIFIER [ type-param-list ]
type-param-list     := LPAREN INTEGER_LITERAL ( COMMA INTEGER_LITERAL )* RPAREN
```

Parser accepts the integer list but attaches no semantic meaning. CREATE TABLE's existing type-affinity derivation continues to inspect only the IDENTIFIER portion.

### Phase 6af semantics

Zero runtime effect. The parenthesized integers are consumed by the parser, dropped, and never influence storage, coercion, or comparison. The column's type-affinity is derived from the identifier alone (same rules as pre-6af).

### Phase 6af errors

- Malformed parameter list (non-integer, trailing comma, unclosed paren) → `PARSE_UNEXPECTED_TOKEN`.
- Empty parameter list `VARCHAR()` → `PARSE_UNEXPECTED_TOKEN` (at least one integer required).

### Phase 6af non-goals

- No type-parameter-based validation (length limits on VARCHAR, precision on NUMERIC). Those remain out of scope for v1.
- No preservation of type parameters in CREATE TABLE serialization (ROUND-TRIP compatibility with mainline SQLite's sqlite_schema is deferred).

### Test authority (Phase 6af)

`tests/cross-build/phase6af.json` is the executable specification. All prior phase fixtures MUST stay green. Additionally, upstream `select4.test` and `select5.test` (which were 0/3857 and 0/1436 respectively pre-6af due to `VARCHAR(N)` blockers) must now reach pass rates comparable to select1..3.

---

## Phase 6ay — N-way JOINs (N ≥ 3 tables joined)

Phase 6ay extends the JOIN planner from 2-table (Phase 6e) to N-table (N ≥ 3). Surfaced as a blocker on upstream `select4.test` / `select5.test` which use 3+ way joins extensively.

No new VDBE opcodes. No new keywords. `max_invariant=43` unchanged.

### Phase 6ay grammar

Already supported by the parser — the existing JOIN production accepts arbitrary chains:

```
join-chain := table-ref ( join-op table-ref join-condition )*
```

Only the **compiler / planner** is currently limited to 2 tables. This phase lifts that limit.

### Phase 6ay semantics

Standard SQL left-associative JOIN:

```
a JOIN b ON c1 JOIN c ON c2  ≡  (a JOIN b ON c1) JOIN c ON c2
```

- Each ON clause filters the composite rowset as tables accumulate.
- INNER / LEFT OUTER kinds per Phase 6e apply unchanged.
- NATURAL / USING deferred to Phase 6aq.

### Phase 6ay compile — reference lowering

Nested-loop join, left-associative:

```
open cursor a
outer loop over a:
    open cursor b; filter by on-condition-1
    loop over b:
        open cursor c; filter by on-condition-2
        loop over c:
            emit result
```

Naive O(N) nesting. No join-reordering optimization in v1. Each table contributes one cursor nesting level.

### Phase 6ay errors

No new error names. Column-reference resolution errors propagate.

### Phase 6ay non-goals

- Join-order optimization (hash-join, merge-join, reorder based on cardinality) — deferred.
- CROSS JOIN as explicit keyword — probably works via existing grammar; confirm via fixture.
- FULL OUTER JOIN — out of v1.

### Test authority (Phase 6ay)

`tests/cross-build/phase6ay.json` is the executable specification. All prior phase fixtures MUST stay green. Additionally, upstream `select4.test` and `select5.test` must stop panicking on join-shape errors (may still fail on other unrelated features).

---

## Phase 6ag — correlated subqueries

Phase 6ag adds support for **correlated subqueries**: an inner SELECT that references columns from the enclosing query's scope. Currently the biggest single unlock on the upstream corpus (~1400 records on select1..3 affected).

No new VDBE opcodes expected. `max_invariant=43` unchanged.

### Problem

Without this phase, a query like:

```sql
SELECT (SELECT count(*) FROM t1 AS x WHERE x.b < t1.b) FROM t1
```

fails at compile with `COMPILE_UNKNOWN_COLUMN` because the inner `t1.b` reference resolves only against the inner FROM scope (`x`), not the outer (`t1`).

### Phase 6ag semantics

- An inner subquery's column-resolution scope includes the inner FROM chain AND all enclosing FROM chains (walked outward until resolved or exhausted).
- Inner-vs-outer resolution: innermost scope containing the identifier wins. Shadowing is allowed (inner alias shadows outer table with same name).
- Qualified references (`t.col`) must resolve to a specific scope level; unqualified references resolve by walking outward, ambiguity at any level → error.
- When an inner subquery references an outer column, the subquery is **correlated** — it must be re-evaluated per outer row (no simple hoist).

### Phase 6ag compile — reference lowering

Scope stack model:
- Before entering inner-subquery compile, push the current outer-scope's (alias → cursor-register / column-index) map onto a stack.
- Inner subquery's column resolution walks the stack from top (innermost) down.
- When an outer column is referenced, compile it as a "read column-index C from cursor-register R of scope level L." At VDBE time, this reads the value the outer cursor currently holds — which means the subquery MUST execute in the inner loop of the outer scan.
- Naive execution: re-emit the full subquery program for each outer row (no caching, no lifting). The subquery's inner cursors re-open per outer row, scan, close.

This is correct for v1. Performance-optimal implementations (hoisting uncorrelated portions, memoizing, indexed-subquery rewrite) are deferred.

### Phase 6ag errors

No new error names. `COMPILE_UNKNOWN_COLUMN` still fires if the identifier can't be resolved in ANY enclosing scope.

### Phase 6ag non-goals

- Lateral joins / `LATERAL` keyword — deferred.
- Correlated DELETE / UPDATE — deferred.
- Subquery flattening / predicate pushdown optimizations — deferred.
- Infinite-nesting testing — v1 supports at least 3 levels of nesting; no explicit depth limit declared but stack depth is bounded by implementation.

### Test authority (Phase 6ag)

`tests/cross-build/phase6ag.json` is the executable specification. All prior phase fixtures MUST stay green. Upstream `select1..3.test` must jump significantly (projected +1000-1400 records across the three files).

---

## Phase 6ae — `EXISTS` / `NOT EXISTS` subquery predicate

Phase 6ae adds the `EXISTS (subquery)` and `NOT EXISTS (subquery)` predicates. Builds on Phase 6ag's scope stack since most upstream EXISTS usage is correlated. Expected ~400-700 record unlock across select1..3.

No new VDBE opcodes. `max_invariant=43` unchanged. New reserved keyword `EXISTS`.

### Phase 6ae tokens

Add `KEYWORD_EXISTS`.

### Phase 6ae grammar

```
primary       := ... | [ KEYWORD_NOT ] KEYWORD_EXISTS LPAREN select-statement RPAREN
```

`NOT EXISTS` is a two-token phrase parsed as a single operator kind at primary-expression level.

### Phase 6ae semantics

- `EXISTS (subquery)`: Integer(1) if subquery returns ≥1 row, Integer(0) if 0 rows. **NEVER NULL**, even if subquery rows contain NULLs (SQL-standard).
- `NOT EXISTS (subquery)`: inverse. Integer(1) if 0 rows, Integer(0) if ≥1 rows.
- Correlated EXISTS: inner subquery scope-stack applies per Phase 6ag; re-evaluated per outer row.

### Phase 6ae compile — reference lowering

Canonical lowering for `EXISTS (subquery)`:

```
  result_reg := LoadConst 0
  compile subquery as-if body only had LIMIT 1
  on first row of subquery: result_reg := LoadConst 1 ; Jump done
done:
```

Specifically: treat the subquery body as a scan that exits at the first ResultRow emit, store 1; otherwise fall through with 0. `NOT EXISTS` wraps with the Phase 6u `Not` opcode on the result.

Null handling: `EXISTS` does NOT propagate Null — even a subquery returning only Null-containing rows yields Integer(1) (rows are rows regardless of their values).

### Phase 6ae errors

No new error names. Subquery-level errors propagate.

### Phase 6ae non-goals

- `UNIQUE` / `ANY` / `SOME` / `ALL` predicates — deferred.
- EXISTS with forward column references inside the subquery (correlated case handled via 6ag).

### Test authority (Phase 6ae)

`tests/cross-build/phase6ae.json` is the executable specification. All prior phase fixtures MUST stay green. Upstream `select1..3.test` must absorb another wave of EXISTS-gated queries.

---

## Phase 6az — `NOT BETWEEN`

Phase 6az extends Phase 6-level BETWEEN with its NOT form: `x NOT BETWEEN lo AND hi` ≡ `NOT (x BETWEEN lo AND hi)`. Surfaced as the single biggest remaining parse-error blocker on upstream `select1..3` (771 occurrences across those three files — each currently a parse failure).

No new VDBE opcodes. No new keywords. `max_invariant=43` unchanged.

### Phase 6az grammar

Extend BETWEEN with optional leading NOT:

```
comparison := additive [ cmp-op additive | null-test | in-list | [KEYWORD_NOT] KEYWORD_BETWEEN additive KEYWORD_AND additive ]
```

`NOT BETWEEN` is a two-token phrase at the same precedence as BETWEEN.

### Phase 6az semantics

`x NOT BETWEEN lo AND hi` ≡ `NOT (x BETWEEN lo AND hi)` ≡ `NOT ((x >= lo) AND (x <= hi))`. Follows 3VL via the existing NOT opcode.

### Phase 6az compile

Parse-time desugar to `UnaryOp::Not` wrapping the existing BETWEEN desugar (which is already `(x >= lo) AND (x <= hi)`). Zero new opcodes.

### Phase 6az errors

None new. Malformed uses reuse existing PARSE_UNEXPECTED_TOKEN.

### Test authority (Phase 6az)

`tests/cross-build/phase6az.json` is the executable specification. Upstream `select1..3.test` must jump ~+600-750 records after 6az lands.


## Phase 6ba — positional `ORDER BY`

Phase 6ba extends Phase 6b's `ORDER BY` to accept integer literals as *projection column references* (1-indexed), per standard SQL. `ORDER BY 1` means "sort by the 1st expression in the SELECT list." Cross-build evidence: upstream `select1.test` uses `ORDER BY <integer>` exclusively (1000 occurrences, 0 uses of `ORDER BY <identifier>`) and all 1031 of its queries are `nosort` mode — so our current treatment of `ORDER BY 1` as "sort by the constant 1 per row" (a silent no-op) invalidates the entire file. Projected unlock: ~340+ records on select1.test alone (from 680/1031 → ~1020/1031).

No new VDBE opcodes. No new keywords. No new AST node kind. Pure compile-time rewrite inside the ORDER BY lowering. `max_invariant=43` unchanged.

### Phase 6ba grammar

Unchanged. `order-by-term := expression [ KEYWORD_ASC | KEYWORD_DESC ]` already admits integer literals (an integer literal is a valid expression). The extension is purely in the compile step, not the grammar.

### Phase 6ba semantics

At **compile time**, every `order-by-term` whose expression is a bare positive integer literal `N` is rewritten to refer to the Nth expression of the SELECT projection (1-indexed).

Rules:

1. **Positional match.** If the order-by expression is *literally* an integer literal with value `N` where `1 ≤ N ≤ projection_count`, substitute the Nth projection expression as the sort key. Direction (ASC/DESC) is preserved.

2. **Out of range.** `N < 1` or `N > projection_count` raises `COMPILE_ORDER_BY_POSITION_OUT_OF_RANGE { position: N, projection_count: P }` at compile time.

3. **Not a bare literal.** Any order-by-term that is *not* a bare integer literal remains evaluated as an expression (old behavior). This includes:
    - `ORDER BY 1+0` — a `BinaryOp(1, +, 0)` node, not an integer literal → evaluated per row as the constant 1.
    - `ORDER BY (1)` — depends on AST: if the parser collapses `Paren(Int(1))` to `Int(1)`, this IS positional; if the parser keeps the `Paren` wrapper, it is NOT. Spec decision: **parenthesised integer literal is NOT positional** — the `Paren` wrapper is preserved in the AST and the compile-time rewrite keys off `AstKind::IntLiteral`, not semantic integer value. This matches mainline SQLite, where `(1)` is treated as an expression.
    - `ORDER BY 1.0` — REAL literal, not INTEGER → not positional. (SQLite treats `ORDER BY 1.0` as expression.)
    - `ORDER BY -1` — AST shape is `UnaryOp(Neg, Int(1))`, not `Int(-1)` → not positional. SQLite treats this as expression (and since it's a constant negative, a no-op sort).

4. **Aggregate / window in projection.** If the targeted projection is an aggregate or otherwise context-sensitive expression, the rewrite still points to the *evaluated* projection value — i.e. the sort key is the same value that will be produced by the projection, not a re-evaluation of the underlying expression. Implementation hint: the compiler may either (a) reference the already-materialised projection register/slot, or (b) emit the same projection expression a second time for the sort key. The semantics are identical; generators should choose whichever fits their existing ORDER BY lowering most naturally. Cross-build risk: both choices must produce byte-identical result rows — and they do, because ORDER BY determines row order, not content.

5. **Duplicate keys across ORDER BY terms.** `ORDER BY 1, a` where `a` is projection 1 is permitted; the two terms evaluate to the same key value per row. No deduplication.

6. **Direction & NULLS handling.** Preserved unchanged from Phase 6b. `ORDER BY 1 DESC` means "sort by projection 1, descending." NULLs sort per Phase 6b rules.

7. **`SELECT *` projection + positional ORDER BY.** When the projection is `*` (star), the implicit projection list is the FROM-clause's column list in declared order. `ORDER BY N` refers to the Nth column of that implicit list. Implementation hint: each generator may either (a) expand `*` into an explicit projection list before the positional rewrite, or (b) synthesize a `ColumnRef` node for the Nth column by walking FROM-clause tables. Both choices are semantically identical. Do NOT leave `*` unrewritten — that silently produces "sort by literal N per row" (no-op sort), diverging from SQLite. Regression fixture: `SELECT * FROM t ORDER BY 1` must sort by the first declared column.

8. **Aggregate SELECT without GROUP BY + positional ORDER BY.** An aggregated single-row SELECT like `SELECT COUNT(*) FROM t ORDER BY 1` is rejected at compile time. The exact error NAME depends on the internal ordering of (a) the 6ba positional rewrite and (b) the Phase 6c aggregate-ORDER-BY check: if the rewrite runs first, the query becomes "ORDER BY aggregate-expression" and fires `AGGREGATE_IN_NON_PROJECTION_CONTEXT`; if the check runs first (or the rewrite is specialized to skip this shape), it fires `AGGREGATE_WITH_ORDER_OR_LIMIT`. Both are valid spec responses — the query is invalid either way. Each generator pins its own choice; cross-build regression test for this interaction is left to the per-phase fixture (`phase6c: compile-error-aggregated-with-order-by`), which currently expects `AGGREGATE_WITH_ORDER_OR_LIMIT`. Generators MUST either (i) make their 6ba rewrite run after the 6c check, or (ii) specialize the rewrite to no-op in the aggregate-no-GROUP-BY shape — whichever keeps that fixture green.

### Phase 6ba compile

Where the compiler lowers an `order-by-term` to sort-key evaluation:

```
fn lower_order_by_term(term, projection):
    if term.expression is IntLiteral(n) where 1 <= n <= len(projection):
        sort_key_expr = projection[n - 1].expression
    else if term.expression is IntLiteral(n):
        raise COMPILE_ORDER_BY_POSITION_OUT_OF_RANGE { position: n, projection_count: len(projection) }
    else:
        sort_key_expr = term.expression
    emit_sort_key(sort_key_expr, term.direction)
```

The substitution is **syntactic** (AST-level), performed once, before sort-key codegen. Both generators must perform the check on the exact same AST node shape (bare `IntLiteral`) — no semantic integer-value inference.

### Phase 6ba errors

- `COMPILE_ORDER_BY_POSITION_OUT_OF_RANGE { position: int, projection_count: int }` — positional index outside `[1, projection_count]`.

### Phase 6ba non-goals

- `ORDER BY 1+0` treated as expression (per rule 3). Will silently be a no-op; this is a user mistake, not something the engine should rewrite.
- GROUP BY positional references — separate phase (6bb when needed).
- Compound SELECT ORDER BY positional — deferred (compound SELECT itself is deferred).

### Test authority (Phase 6ba)

`tests/cross-build/phase6ba.json` is the executable specification. After Phase 6ba lands, upstream `select1.test` must jump from 680/1031 to near 1000/1031 byte-identical on both targets.


## Phase 6ak — `IF EXISTS` / `IF NOT EXISTS` clauses

Phase 6ak adds the optional `IF EXISTS` clause to DROP statements and the optional `IF NOT EXISTS` clause to CREATE statements. These are pure idempotency modifiers: they suppress the otherwise-raised error when the target does/doesn't already exist. No new keyword (all three — `IF`, `EXISTS`, `NOT` — already exist as reserved words from earlier phases).

**Scope note on opcodes.** The `IF EXISTS` / `IF NOT EXISTS` modifiers themselves add no opcodes — they are handled at compile time by emitting an `[Init, Halt]` no-op program when the existence condition already matches. However, `DROP TABLE` (as a statement form) is reachable in this phase for the first time; the v1 spec labelled schema-alteration statements as non-goal in Phase 2a, and Phase 9f introduced `DROP INDEX` but not `DROP TABLE`. Both C and Rust 6ak generators independently added an `OP_DROP_TABLE` opcode to handle the storage side-effect — that is the correct answer. The new opcode reuses the pre-existing non-empty-name invariant (existing invariant index from earlier DDL opcodes), so `max_invariant=43` is unchanged. `DROP INDEX` reuses its pre-existing opcode; only `DROP TABLE` is net-new here.

Cross-build evidence: upstream corpus survey (2026-04-19) shows 30+ `.test` files fail at parse for DROP IF EXISTS or CREATE IF NOT EXISTS shapes. Evidence-subcorpus pass rate is held back by these primarily.

### Phase 6ak grammar

Extend four DDL productions:

```
drop-table-statement  := KEYWORD_DROP KEYWORD_TABLE  [KEYWORD_IF KEYWORD_EXISTS] identifier
drop-index-statement  := KEYWORD_DROP KEYWORD_INDEX  [KEYWORD_IF KEYWORD_EXISTS] identifier
drop-view-statement   := KEYWORD_DROP KEYWORD_VIEW   [KEYWORD_IF KEYWORD_EXISTS] identifier   (added once CREATE VIEW lands)
create-table-statement := KEYWORD_CREATE KEYWORD_TABLE [KEYWORD_IF KEYWORD_NOT KEYWORD_EXISTS] identifier ...
create-index-statement := KEYWORD_CREATE KEYWORD_INDEX [KEYWORD_IF KEYWORD_NOT KEYWORD_EXISTS] identifier ...
```

`IF EXISTS` is a two-token phrase; `IF NOT EXISTS` is a three-token phrase. Consume greedily; partial phrases (`DROP TABLE IF t`) are parse errors — reject at the `identifier` position with `PARSE_UNEXPECTED_TOKEN { expected: [KEYWORD_EXISTS] }`.

The DROP VIEW variant exists in the grammar but is only reachable once Phase 6ac (CREATE VIEW) lands; until then, attempting DROP VIEW raises the existing pre-6ac error.

### Phase 6ak semantics

**IF EXISTS on DROP**: if the target object exists, drop it (unchanged from pre-6ak). If the target does NOT exist, do nothing successfully — suppress the otherwise-raised `STORAGE_TABLE_NOT_FOUND` / `STORAGE_INDEX_NOT_FOUND` / `STORAGE_VIEW_NOT_FOUND` error. Return `{"rows": []}` either way.

**IF NOT EXISTS on CREATE**: if the target object already exists with the same name (case-insensitive, matching existing Phase 2a / 9a rules), do nothing successfully — suppress the otherwise-raised `STORAGE_TABLE_EXISTS` / `STORAGE_INDEX_EXISTS`. If it does not exist, create it as usual. Return `{"rows": []}` either way.

**Case sensitivity**: the existence check reuses the existing case-insensitive lookup (Phase 2a canonical). `DROP TABLE IF EXISTS t` where the stored name is `T` succeeds.

**Cross-object collision**: `CREATE TABLE IF NOT EXISTS idx` when `idx` is an *index* — the spec pins this as a `STORAGE_TABLE_EXISTS` error (not suppressed), because IF NOT EXISTS checks for the specific object kind. If a *table* named `idx` already exists, suppress; if an *index* named `idx` exists, raise. This matches mainline SQLite's behaviour and is pinned by fixture `if-not-exists-different-kind-not-suppressed`.

### Phase 6ak compile

Two changes:

1. Extend the parser to accept the optional `IF EXISTS` / `IF NOT EXISTS` phrase and attach a boolean flag to the DDL AST node (`if_exists: bool` on DROP nodes, `if_not_exists: bool` on CREATE nodes).

2. In the compile step for DROP / CREATE, before emitting the existence check / error, check the flag: if set and the existence condition is already as desired, emit a zero-opcode path (or a no-op program) that just exits cleanly with `{"rows": []}`.

### Phase 6ak errors

No new error kinds. Existing storage errors are *conditionally suppressed* by the flag; they are not renamed or reshaped.

### Phase 6ak non-goals

- `IF EXISTS` on ALTER TABLE — separate phase.
- `DROP SCHEMA IF EXISTS` / `DROP TRIGGER IF EXISTS` — per-object when those statements are added.
- Bulk DROP (`DROP TABLE a, b, c`) — non-goal permanently.

### Test authority (Phase 6ak)

`tests/cross-build/phase6ak.json` is the executable specification. After landing, upstream corpus evidence subcorpus should jump from 77.4% → ~95% and IF-EXISTS-blocked random-subcorpus files should move up a tier.


## Phase 6bb — `ASC`/`DESC` modifier in CREATE INDEX column list

Phase 6bb allows `ASC` and `DESC` tokens after each column in `CREATE INDEX ... (col1, col2)` to specify per-column sort order. In v1 of sqlite-leap the query planner does not yet consult indexes for ORDER BY, so the modifier is parsed and stored on the index schema but has no execution-time effect. This matches the upstream-corpus compatibility shape: tests emit `CREATE INDEX ... (col DESC)` and expect the statement to succeed; they never rely on the index being used to satisfy an ORDER BY clause. No new VDBE opcodes. No new keywords (`ASC`, `DESC` already exist from Phase 6b). `max_invariant=43` unchanged.

Cross-build evidence: corpus survey identified 10+ `index/` files each with 4–5K failures, all from `CREATE INDEX ... (col DESC)` being rejected at parse. Estimated unlock: ~40K passing records on top of current select1..3 core.

### Phase 6bb grammar

Replace the CREATE INDEX column list:

```
indexed-column := identifier [ KEYWORD_ASC | KEYWORD_DESC ]
create-index-column-list := LPAREN indexed-column ( COMMA indexed-column )* RPAREN
```

Direction is optional per column; default is `ASC`.

### Phase 6bb semantics

The direction modifier is persisted on the index schema (new `direction: "asc" | "desc"` field per indexed-column entry in the schema representation). Execution-time effect in v1: none. The index is built using the table's row order; queries that scan the index get the order implied by the row insertion / row-id ordering. ORDER BY still sorts results correctly at the VDBE level regardless of index direction.

Cross-build risk: the persisted direction must survive round-trip through `sqlite_schema` (when that phase lands). For now, the direction is an in-memory flag on the index schema node. Both generators must agree on the flag shape and the default ("asc" when unspecified) for byte-identical schema dumps.

### Phase 6bb compile

Parser extension only. The direction flag is consumed at parse time, stored on the index schema, and ignored by the index-build codegen. No VDBE change.

### Phase 6bb errors

- Invalid token after identifier (neither `ASC`, `DESC`, `,`, nor `)`): `PARSE_UNEXPECTED_TOKEN` as usual.
- `DESC DESC` or `ASC DESC` in sequence: `PARSE_UNEXPECTED_TOKEN` on the second direction token.

### Phase 6bb non-goals

- Query planner using ASC/DESC index direction to optimize ORDER BY — deferred to a later index-planner phase.
- Collating sequences per column — separate phase.
- Multi-level direction inheritance rules — non-goal.

### Test authority (Phase 6bb)

`tests/cross-build/phase6bb.json` is the executable specification.


## Phase 6bc — empty `IN ()` list

Phase 6bc allows the empty-parenthesized form of IN: `x IN ()` (with no expressions between parens). Per SQLite semantics (verified against upstream `evidence/in2.test`), `x IN ()` is **always false regardless of `x`** — including `NULL IN ()` → `0`. There is no NULL propagation in the empty-list case because no comparison occurs: NULL propagation in IN-lists is driven by per-element comparisons (`x = list[i]` being Null-tainted), and with zero elements there are no comparisons to taint. The membership question "is x in the empty set?" has a definitionally unambiguous answer: no. Symmetrically, `x NOT IN ()` is **always true**, including `NULL NOT IN ()` → `1`. No new VDBE opcodes. No new keywords. `max_invariant=43` unchanged.

Cross-build evidence: `evidence/in2.test` line 139 asserts `NULL NOT IN ()` returns `1`. Initial 6bc spec (corrected here) gave `Null`; both C and Rust 6bc generators faithfully implemented the incorrect spec, and both produced the same wrong hash on in2.test line 139 — cross-corroboration signal firing. Spec corrected 2026-04-19.

### Phase 6bc grammar

Extend `in-list` in Phase 6v to accept zero expressions:

```
in-list := LPAREN [ expression ( COMMA expression )* ] RPAREN
```

### Phase 6bc semantics

- `x IN ()` → always `Int(0)` (false), for any value of `x` including Null.
- `x NOT IN ()` → always `Int(1)` (true), for any value of `x` including Null.

Both forms short-circuit: `x` is still evaluated (for any side effects), but no comparison to any element occurs because there are none, and no NULL propagation applies in the empty case. This deliberately deviates from the "NULL propagates through IN" rule for non-empty lists — the justification is that NULL propagation is a consequence of comparing NULL to some value, which cannot happen with zero values.

### Phase 6bc compile

Parser allows empty list. At compile time, detect the empty list and emit a constant-Int result without opening any comparison loop or a null-check on x. Canonical lowering:

```
emit:
    result = 0   (for IN)
    # or
    result = 1   (for NOT IN)
```

Implementation hint: reuse existing OpInteger. Do NOT emit a null-check on x — there is nothing for x's null to propagate through, and SQLite behaviour pins the result to 0 / 1 regardless. Note: `x` does NOT need to be evaluated for the empty-list case (no side effects are expected of SQL expressions in sqlite-leap's scope), so generators may skip evaluating `x` entirely.

### Phase 6bc errors

None new. A malformed `IN (,)` or `IN (, a)` is still `PARSE_UNEXPECTED_TOKEN` at the stray comma.

### Phase 6bc non-goals

- Empty list in `IN <subquery>` — deferred (subquery form is its own phase).
- Empty list with trailing comma `IN (a,)` — non-goal (strict parse).

### Test authority (Phase 6bc)

`tests/cross-build/phase6bc.json` is the executable specification.


## Phase 6bd — `SELECT ALL` keyword

Phase 6bd accepts the optional `ALL` keyword after `SELECT`, as a no-op (it means "include duplicates" — already our default behavior). Mirror of `SELECT DISTINCT` (which removes duplicates). No new VDBE opcodes. No new keyword (`ALL` already reserved from earlier phases). `max_invariant=43` unchanged.

Cross-build evidence: upstream corpus survey (2026-04-19) flagged `SELECT ALL` as a blocker on ~7K+ records in random/aggregates and random/select subcorpus — these are random-generated queries where ALL is frequently inserted.

### Phase 6bd grammar

```
select-core := KEYWORD_SELECT [ KEYWORD_ALL | KEYWORD_DISTINCT ] projection ...
```

`ALL` and `DISTINCT` are mutually exclusive. `ALL` is effectively the default (no deduplication).

### Phase 6bd semantics

`SELECT ALL` is equivalent to `SELECT` (no modifier). Result set includes duplicates. DISTINCT-flag-on-AST remains `false`; no new flag introduced.

### Phase 6bd compile

Parser: accept and discard `KEYWORD_ALL` at the DISTINCT-peek position. Do not store anything on the Select AST (ALL is the default). No compiler change.

### Phase 6bd errors

- `SELECT ALL DISTINCT` or `SELECT DISTINCT ALL`: `PARSE_UNEXPECTED_TOKEN` on the second modifier.

### Phase 6bd non-goals

None.

### Test authority (Phase 6bd)

`tests/cross-build/phase6bd.json` is the executable specification.


## Phase 6be — `INSERT INTO <table> <select-statement>`

Phase 6be extends INSERT to accept a SELECT as the row source, in addition to the existing `VALUES (…)` form. `INSERT INTO u SELECT a FROM t` inserts one row into `u` per row produced by the SELECT. No new VDBE opcodes (reuses existing `OP_INSERT` and SELECT machinery). `max_invariant=43` unchanged.

Cross-build evidence: upstream corpus survey (2026-04-19) identified INSERT INTO SELECT as the setup-phase blocker for the four largest index subcorpora (orderby_nosort, between, in, delete — 10 files each, ~10K records each). Current failure mode: parse error on the INSERT statement in test-setup, cascading to all dependent query failures. Projected unlock: ~30K records across four subcorpora.

### Phase 6be grammar

Extend the INSERT production to two forms:

```
insert-statement := KEYWORD_INSERT KEYWORD_INTO identifier [ LPAREN column-list RPAREN ] insert-source
insert-source    := KEYWORD_VALUES row-list
                  | select-statement
```

The existing form `INSERT INTO t VALUES (…)` is unchanged. The new form reads `INSERT INTO t SELECT …` (no VALUES keyword).

Optional column list: `INSERT INTO t (a, b) SELECT …` — same projection-to-column mapping rules as existing INSERT-VALUES.

### Phase 6be semantics

For each row produced by the SELECT, treat it as a VALUES tuple and insert it into the target table using existing per-column coercion rules (Phase 6g INTEGER/REAL/TEXT affinity, Phase 2a column-type coercion). The SELECT is fully evaluated against the database state at INSERT time — if the SELECT's FROM references the INSERT target, its scan completes before any new rows arrive (snapshot-at-start semantics).

Column-count mismatch: if the SELECT produces N columns but the target has M columns (or the explicit column list has K entries), raise `COMPILE_INSERT_COLUMN_COUNT_MISMATCH { expected, got }` at compile time. Same error kind already used for INSERT VALUES.

NULL, REAL, BLOB, and all Phase 6g types flow through unchanged.

### Phase 6be compile

Two-stage lowering:

1. Compile the SELECT statement's core loop (open cursor on source, scan, per-row projection into result registers) — exactly as for a standalone SELECT.
2. Where the SELECT would normally emit `OP_RESULT_ROW`, emit `OP_INSERT` instead, using:
    - The target table's cursor (opened with `OP_OPEN_WRITE` at INSERT-statement start).
    - The projected row registers as the new row's column data.

Column list translation: if the INSERT has an explicit `(a, b)` list, reorder/pad the projection registers before `OP_INSERT` using the existing INSERT-VALUES translator.

Self-insert (INSERT INTO t SELECT ... FROM t): the SELECT's cursor and the target cursor are separate cursor instances, but the b-tree is shared. Generators MAY buffer the SELECT's rows in a sorter before inserting, to avoid scan-order disturbance, OR rely on the b-tree's split-stability under concurrent read+insert. For v1, recommend buffering via `OP_SORTER_OPEN` → `OP_SORTER_INSERT` during SELECT, then `OP_SORTER_SORT` + iterate + `OP_INSERT`. Both generators must agree on buffering-or-streaming for byte-identical behavior on self-insert fixtures.

### Phase 6be errors

- `COMPILE_INSERT_COLUMN_COUNT_MISMATCH { expected: int, got: int }` — existing error, reused for SELECT-source. Triggered when SELECT projection count doesn't match target columns.
- `COMPILE_TABLE_NOT_FOUND` (existing) — if target table doesn't exist.
- Runtime errors from the SELECT (e.g. referenced table missing) propagate as-is.

### Phase 6be non-goals

- `INSERT OR REPLACE / OR IGNORE ... SELECT` — deferred to Phase 6ab (conflict resolution + SELECT source is a product of the two phases).
- `RETURNING` clause — permanent non-goal.
- `INSERT ... DEFAULT VALUES` — deferred to Phase 6al.

### Test authority (Phase 6be)

`tests/cross-build/phase6be.json` is the executable specification. After landing, upstream `index/orderby_nosort/10/`, `index/between/10/`, `index/in/10/`, `index/delete/10/` subcorpora must jump significantly (projected +30K records total, byte-identical both targets).


## Phase 6al — `DEFAULT <expr>` in CREATE TABLE column

Phase 6al extends `CREATE TABLE` column definitions to accept an optional `DEFAULT <expr>` clause. When an `INSERT` omits a column (via explicit column list or `DEFAULT VALUES` form), the declared default is evaluated and used. No new VDBE opcodes. `max_invariant=43` unchanged.

### Phase 6al grammar

```
column-def := identifier [ column-type ] [ column-constraints ]
column-constraint := KEYWORD_DEFAULT default-value
                   | KEYWORD_NOT KEYWORD_NULL      (Phase 6am)
                   | KEYWORD_PRIMARY KEYWORD_KEY [ KEYWORD_AUTOINCREMENT ]  (Phase 6ar)
default-value := literal | LPAREN expression RPAREN | KEYWORD_NULL | signed-numeric-literal
```

The default value can be: a literal (integer, real, text, NULL), a parenthesized expression, or a signed numeric literal (`DEFAULT -1`). Expression-valued defaults are evaluated **at INSERT time**, once per row, in the row's empty-scope context.

### Phase 6al semantics

For each INSERT row, for each column:
- If the column appears in the explicit column list (or VALUES tuple covers all columns), use that value.
- Else if the column has a `DEFAULT <expr>`, evaluate it now.
- Else if the column has `NOT NULL` (Phase 6am), raise `RUNTIME_NOT_NULL_VIOLATION { column: "..." }`.
- Else, insert `NULL`.

New form: `INSERT INTO t DEFAULT VALUES;` — inserts one row using all columns' defaults (NULL where no default). Column list is optional in this form.

### Phase 6al compile

Store the default AST on the column definition. At INSERT compile time, for each column not covered by the source, compile the default expression and emit into the column's target register.

### Phase 6al errors

- `PARSE_UNEXPECTED_TOKEN` on malformed default.
- `COMPILE_INVALID_DEFAULT_EXPRESSION` if the expression references other columns or tables (DEFAULT must be self-contained constant-time for v1 — reject `DEFAULT (a + 1)` at compile time).

### Phase 6al non-goals

- `DEFAULT CURRENT_TIMESTAMP` etc. — deferred to Phase 6av.
- Non-constant expressions referencing other columns — non-goal.

### Test authority (Phase 6al)

`tests/cross-build/phase6al.json`.


## Phase 6am — `NOT NULL` column constraint

Phase 6am adds the `NOT NULL` column constraint. An INSERT that would place `NULL` into a `NOT NULL` column (explicitly, or via omitted-column with no DEFAULT) raises `RUNTIME_NOT_NULL_VIOLATION`. No new VDBE opcodes. `max_invariant` possibly bumped to 44 for the new runtime check (generators choose).

### Phase 6am grammar

Part of column-constraints in 6al. `NOT NULL` is a two-token phrase at the column-constraint level.

### Phase 6am semantics

At INSERT time, after evaluating each column's value:
- If the column is marked `NOT NULL` and the value is `Null`, raise `RUNTIME_NOT_NULL_VIOLATION { column: "name", table: "t" }`. Transaction rolls back to pre-INSERT state.

Interaction with DEFAULT:
- `INTEGER NOT NULL DEFAULT 0` → omitted column gets 0, no error.
- `INTEGER NOT NULL` (no default) → omitted column raises RUNTIME_NOT_NULL_VIOLATION.
- `INTEGER NOT NULL`, explicit `NULL` value → raises.

### Phase 6am compile

Store `not_null: bool` flag on column schema. At INSERT compile, emit a `OpIsNull` check on the column's target register after the value is placed; branch to a raise-error opcode if null.

### Phase 6am errors

- `RUNTIME_NOT_NULL_VIOLATION { table: str, column: str }` — new runtime error kind.

### Phase 6am non-goals

- `CHECK (col IS NOT NULL)` form — deferred to Phase 6at.
- Declarative `NULL` keyword (the inverse) — non-goal, the default is nullable.

### Test authority (Phase 6am)

`tests/cross-build/phase6am.json`.


## Phase 6ar — `INTEGER PRIMARY KEY [AUTOINCREMENT]`

Phase 6ar recognizes `INTEGER PRIMARY KEY` as a rowid-alias declaration (SQLite-standard semantics) and the optional `AUTOINCREMENT` keyword for strictly-increasing rowid assignment. Critical for file-format bidirectional compatibility — SQLite files with INT PK tables use the rowid-aliasing storage optimization; our reader must recognize it.

### Phase 6ar grammar

```
column-constraint := ... | KEYWORD_PRIMARY KEYWORD_KEY [ KEYWORD_AUTOINCREMENT ]
```

Applicable ONLY to `INTEGER`-typed columns (enforced at compile). `AUTOINCREMENT` is only valid after `INTEGER PRIMARY KEY`.

### Phase 6ar semantics

An `INTEGER PRIMARY KEY` column is a **rowid alias**: INSERTs that provide a value for this column use it as the rowid (raise `STORAGE_UNIQUE_VIOLATION` on duplicate, consistent with 9g's PK-duplicate error name); INSERTs that omit it get an auto-assigned rowid (smallest unused positive integer, or a monotonically-increasing one with AUTOINCREMENT).

**Storage layout on write**: the column's value is NOT stored in the row body; instead the rowid serves as its value. On read, the rowid is projected as the declared column. This is required for bidirectional compat with mainline SQLite.

**On read of mainline-SQLite-written files**: the engine detects `INTEGER PRIMARY KEY` in the parsed schema and projects the rowid as the column's value.

**AUTOINCREMENT semantics**: maintains an `sqlite_sequence` table recording the highest rowid ever used per table. New auto-assigned rowids are `max(rowid, sqlite_sequence.seq) + 1`. Without AUTOINCREMENT, just `max(rowid) + 1` (or smallest unused).

### Phase 6ar compile / storage

- Parser: accept optional `PRIMARY KEY [AUTOINCREMENT]` after column type.
- Schema: mark column as rowid-alias (`is_rowid_alias: bool`) and auto-increment flag.
- CREATE TABLE: if any column is rowid-alias, no separate rowid column is stored; the b-tree key IS that column's value.
- INSERT: if rowid-alias column has a provided value, use it as rowid; else auto-assign.
- SELECT / row projection: for rowid-alias columns, project the row's rowid instead of reading from the row body.
- Storage reader: when opening a file, detect rowid-alias columns in the schema (parse CREATE TABLE text) and use the alias behavior on row reads — enables reading mainline-SQLite files.

### Phase 6ar errors

- `COMPILE_AUTOINCREMENT_WITHOUT_PRIMARY_KEY` — AUTOINCREMENT without PRIMARY KEY.
- `COMPILE_MULTIPLE_PRIMARY_KEYS` — more than one PRIMARY KEY per table.
- `STORAGE_UNIQUE_VIOLATION` — INSERT with explicit rowid that collides with existing row in a rowid-alias table. **Reconciliation note (2026-04-20):** earlier drafts of 6ar specified `STORAGE_PRIMARY_KEY_CONFLICT` as a distinct error kind; the spec now unifies to `STORAGE_UNIQUE_VIOLATION` (matching Phase 9g's existing error name for PK uniqueness enforcement) so that rowid-alias tables and 9f-auto-indexed tables share the same duplicate-key error surface. Both targets must emit `STORAGE_UNIQUE_VIOLATION` for this condition; any internal `StoragePrimaryKeyConflict` variant retained for diagnostic granularity must map to `STORAGE_UNIQUE_VIOLATION` at the runner/error-name boundary.

### Phase 6ar non-goals

- `PRIMARY KEY (col1, col2, ...)` table-level composite — deferred to Phase 6au.
- Non-INTEGER column `PRIMARY KEY` — **NOT a 6ar non-goal.** Phase 9f already accepts non-INTEGER `PRIMARY KEY` and creates `sqlite_autoindex_*` for uniqueness. 6ar ONLY adds the rowid-alias optimization for the specifically-typed `INTEGER PRIMARY KEY` column form; non-INTEGER PK continues to route through the 9f path. No `COMPILE_PRIMARY_KEY_ON_NON_INTEGER` error is raised (earlier draft of 6ar specified one; reconciled out on 2026-04-20 to preserve 9f compatibility).
- `WITHOUT ROWID` tables — permanent non-goal for v1.

### Test authority (Phase 6ar)

`tests/cross-build/phase6ar.json`. After 6ar lands, bidirectional file-format compat smoke test should pass on SQLite-written tables with INT PK.

## Phase 6aj — column alias (`AS <name>`) visible in GROUP BY / ORDER BY / HAVING

Phase 6aj extends compile-time name resolution so that a projection-list alias is visible in the clauses evaluated AFTER projection. No new opcodes, no new tokens; **compiler-only phase**, `max_invariant=43`.

### Phase 6aj semantics

The SQLite resolution rule is: in GROUP BY, ORDER BY, and HAVING, try to resolve a bare identifier first against the projection-list aliases; if not found (or ambiguous under the rules below), fall through to the underlying table/column namespace.

- **WHERE** is evaluated BEFORE projection → aliases are NOT in scope. A bare identifier in WHERE that only matches a projection alias → `COMPILE_UNKNOWN_COLUMN`.
- **GROUP BY** / **ORDER BY** / **HAVING** → alias scope wins over table-column scope when there's a match.
- **Ambiguous aliases**: if two projections share the same alias name and a later clause references that alias, raise `COMPILE_AMBIGUOUS_ALIAS` at compile time. Do not silently pick either. **Tiebreak (Phase 6cc)**: if the ambiguous name ALSO matches a base column of the enclosing FROM, the base column wins; no error is raised and the reference resolves to the column. Mainline SQLite does not treat duplicate projection aliases as ambiguous when an underlying table column shares the name.
- **Aliased expressions** (not just column refs) are valid: `SELECT a*10 AS scaled FROM t ORDER BY scaled` must sort by the computed expression.

### Phase 6aj compile

Resolution of a bare identifier in GROUP BY / ORDER BY / HAVING:

1. Look up the name among the current SELECT's projection aliases.
2. If exactly one match → substitute the projection's expression (or output-row register reference) inline.
3. If multiple matches:
   a. If a base column of the enclosing FROM shares the name → leave the reference unchanged so normal column resolution binds it to that base column (Phase 6cc tiebreak).
   b. Otherwise → `COMPILE_AMBIGUOUS_ALIAS`.
4. If no match → fall through to the normal table-column resolution (existing path for 6b / 6d / 6c).

The substitution happens at compile time, before opcode emission, so there is no runtime overhead and no behavior change for queries without aliases.

### Phase 6aj errors

- `COMPILE_AMBIGUOUS_ALIAS` — two projection aliases share the same name and a post-projection clause references that name.
- `COMPILE_UNKNOWN_COLUMN` — a WHERE clause references an identifier that matches only a projection alias (aliases not in WHERE scope).

### Phase 6aj non-goals

- Window-function frame expressions — deferred (no window functions in v1).
- Alias references that would create a reference cycle (alias referring to another alias) — reject as `COMPILE_UNKNOWN_COLUMN` for v1; proper multi-pass resolution is deferred.

### Test authority (Phase 6aj)

`tests/cross-build/phase6aj.json`.

## Phase 6ai — `COUNT(DISTINCT)` / `SUM(DISTINCT)` + MIN/MAX on strings

Phase 6ai un-defers the `DISTINCT` modifier inside aggregate function calls (noted as deferred at 975 and 1328). Also fills in implementation coverage for MIN/MAX on TEXT operands (the ordering rule was already pinned in 6c semantics). No new opcodes; `max_invariant=43`. The aggregate step-state gains an optional dedup set when the aggregate is flagged DISTINCT.

### Phase 6ai grammar

```
aggregate-call := KEYWORD_COUNT LPAREN STAR RPAREN
               | aggregate-name LPAREN [ KEYWORD_DISTINCT ] expression RPAREN

aggregate-name := KEYWORD_COUNT | KEYWORD_SUM | KEYWORD_AVG | KEYWORD_MIN | KEYWORD_MAX | KEYWORD_TOTAL | KEYWORD_GROUP_CONCAT
```

The DISTINCT modifier is valid inside any aggregate EXCEPT `COUNT(*)` (which has no expression to dedup). Rejecting `COUNT(DISTINCT *)` → `COMPILE_DISTINCT_ON_STAR`.

### Phase 6ai semantics

- **COUNT(DISTINCT expr)**: number of distinct non-NULL values of expr in the input set.
- **SUM(DISTINCT expr)**: sum of the distinct non-NULL values of expr.
- **AVG(DISTINCT expr)** / **MIN(DISTINCT expr)** / **MAX(DISTINCT expr)**: dedup before reducing; for MIN/MAX the DISTINCT is semantically a no-op (same result), but must be accepted and not raise.
- Dedup equality uses the same value-equality rule as `IN (expr-list)` (Phase 6v): INTEGER↔INTEGER, REAL↔REAL, TEXT↔TEXT, with no cross-type coercion. `1 = 1.0` is NOT considered a duplicate for DISTINCT (matching SQLite).
- **MIN/MAX on TEXT**: byte-lexicographic comparison (unsigned byte-by-byte). Already pinned in 6c; 6ai ensures implementation coverage.
- **GROUP BY interaction**: the dedup set is per-aggregate-instance per-group — reset when the group's accumulator resets.

### Phase 6ai compile

- AST gains `distinct: bool` on aggregate-call nodes.
- Aggregate step-state record gains `dedup_set: optional set-of-values`, present iff `distinct=true`.
- AggStep: if distinct, skip the value if already in dedup_set; else insert and continue with normal accumulation.
- No new opcodes — this is an extension of the existing AggStep payload.

### Phase 6ai errors

- `COMPILE_DISTINCT_ON_STAR` — `COUNT(DISTINCT *)` or equivalent; DISTINCT requires a non-star argument.

### Phase 6ai non-goals

- `GROUP_CONCAT(DISTINCT expr, sep)` — deferred to 6ap (GROUP_CONCAT base).
- ORDER BY inside aggregate calls (`GROUP_CONCAT(x ORDER BY y)`) — deferred.
- Collation-aware MIN/MAX — deferred; byte-lex only in v1.

### Test authority (Phase 6ai)

`tests/cross-build/phase6ai.json`.

## Phase 6ad — `GLOB` / `NOT GLOB` pattern matching

Phase 6ad adds SQL `GLOB` (Unix-glob-style wildcard matching) alongside the existing `LIKE` (Phase 6x). **One new VDBE opcode kind `Scalar2::Glob` pinning invariant 44; `max_invariant=44`.** One new reserved keyword: `KEYWORD_GLOB`.

### Phase 6ad tokens

New reserved keyword:

- `KEYWORD_GLOB` — tokenized from the identifier `GLOB` (case-insensitive, matching LIKE's tokenization rule).

### Phase 6ad grammar

```
comparison-rhs := ... | [ KEYWORD_NOT ] KEYWORD_GLOB expression
```

`GLOB` and `NOT GLOB` take the same binding precedence as `LIKE` / `NOT LIKE`.

### Phase 6ad semantics

Pattern syntax — byte-level matcher over UTF-8:

- `*` — matches any sequence of zero-or-more BYTES.
- `?` — matches exactly one BYTE.
- `[abc]` — matches exactly one byte that appears in the set.
- `[a-z]` — range (inclusive), byte values.
- `[!abc]` / `[!a-z]` — NEGATED class (POSIX-style; NOT `[^...]`).
- Any other byte in the pattern matches itself literally.

Case-SENSITIVE (byte-equality). `'A' GLOB 'a'` → 0; `'A' GLOB 'A'` → 1.

3VL: NULL on either operand → NULL result. `NOT GLOB` desugars to `NOT (x GLOB y)` with NULL propagation preserved.

### Phase 6ad compile

- AST: `GlobOp { left, pattern }`; `NotGlobOp` desugared to `Not(GlobOp)` at parse time.
- Opcode: `Scalar2::Glob` — two operands (string, pattern), result is a boolean/NULL tri-state.

### Phase 6ad matching algorithm (reference)

Standard recursive/backtracking glob-matcher with early-exit on exhausted pattern. Byte indexes throughout. Char-class parsing returns a length and a predicate; pattern errors raise at match time, not at compile time (mirrors LIKE's handling of malformed escape sequences).

### Phase 6ad errors

- `RUNTIME_INVALID_GLOB_PATTERN` — unbalanced `[`, empty `[]`, or a reversed range (`[z-a]`).

### Phase 6ad non-goals

- `ESCAPE` clause for GLOB — not part of SQLite's GLOB syntax; permanent non-goal.
- Grapheme-level matching — byte-level only, matches SQLite.
- Custom glob functions (`glob(pattern, value)` function form) — deferred.

### Test authority (Phase 6ad)

`tests/cross-build/phase6ad.json`.

## Phase 6ao — scalar string/numeric functions `SUBSTR`, `REPLACE`, `INSTR`, `ROUND`

Phase 6ao fills in four SQLite-standard scalar functions deferred from Phase 6j / 6k / 6s. Two are 3-argument (`SUBSTR` with length, `REPLACE`), two are 1-or-2-argument (`INSTR` is 2-arg; `ROUND` accepts 1 or 2 args). **One new VDBE opcode family `Scalar3::*` pinning invariant 45; `max_invariant=45`.** No new reserved keywords (function names resolved as identifiers by the existing function-call production).

### Phase 6ao grammar

No grammar change — existing `function-call := IDENTIFIER LPAREN [expression ( COMMA expression )*] RPAREN` already accepts 1, 2, or 3 arguments. Compile-time arity check enforces the correct count per function.

### Phase 6ao semantics

**`SUBSTR(s, start [, length])`** — byte-level substring extraction, 1-based.

- `start = 1` is the first byte.
- `start = 0` is treated as `start = 1` (SQLite convention).
- `start < 0` indexes from the end: `start = -1` is the last byte; `start = -3` is the third-from-last.
- `length` omitted → from `start` to end of string.
- `length > remaining` → truncated to remaining.
- `length = 0` → empty string.
- `length < 0` — extract `|length|` bytes ending AT `start` (going backwards); for v1, treat as empty (fixtures do not exercise this edge).
- Any argument NULL → NULL result.

**`REPLACE(s, from, to)`** — replace all non-overlapping occurrences of `from` in `s` with `to`.

- Byte-level, case-sensitive.
- `from = ""` → returns `s` unchanged (SQLite convention; differs from some other SQL dialects).
- Any argument NULL → NULL result.

**`INSTR(s, needle)`** — 1-based byte-index of first occurrence of `needle` in `s`; `0` if not found.

- Byte-level, case-sensitive.
- Any argument NULL → NULL result.

**`ROUND(x [, digits])`** — round `x` to `digits` decimal places.

- `digits` defaults to `0`.
- Rule: **round-half-away-from-zero** (NOT banker's rounding). `ROUND(2.5)` = `3.0`, `ROUND(-2.5)` = `-3.0`.
- Result is always REAL, even for `digits = 0`.
- Negative `digits` rounds to the corresponding power of 10: `ROUND(1234.5, -1)` = `1230.0`.
- Integer argument accepted and returned as REAL.
- Any argument NULL → NULL result.
- Non-numeric TEXT argument → `0.0` (matches SQLite; not v1 fixture).

### Phase 6ao compile

- Function-name lookup extended to recognize `substr`, `replace`, `instr`, `round` (case-insensitive, matching existing Phase 6j pattern).
- Arity check: `SUBSTR` accepts 2 or 3 args; `REPLACE` requires 3; `INSTR` requires 2; `ROUND` accepts 1 or 2.
- Opcode lowering: 1-arg → `Scalar::*` (existing); 2-arg → `Scalar2::*` (existing); 3-arg → `Scalar3::*` (new).
- `SUBSTR(s, start)` without length compiles to either (a) a dedicated `Scalar2::Substr2` kind, or (b) `Scalar3::Substr` with a length-sentinel register preloaded with `i64::MAX` or similar. Implementation-defined.

### Phase 6ao errors

- `COMPILE_ARITY_MISMATCH { function, given, expected }` — wrong number of args. (May already exist from Phase 6j; reuse if so.)

### Phase 6ao non-goals

- Codepoint-aware `SUBSTR` — byte-level only; matches SQLite.
- `REPLACE` with collation-aware matching — byte-level only.
- `ROUND` banker's rounding mode — permanent non-goal; SQLite's `round-half-away-from-zero` is the pinned rule.
- `SUBSTRING` as a synonym for `SUBSTR` — deferred.
- Non-numeric-TEXT coercion in `ROUND` producing non-zero results — permanent SQLite-matches (0.0).

### Test authority (Phase 6ao)

`tests/cross-build/phase6ao.json`.

## Phase 6ac — `CREATE VIEW` / `DROP VIEW` (read-only views, compile-time macro substitution)

Phase 6ac adds SQL views. A view is a stored SELECT statement; references to the view name in a FROM clause substitute the SELECT at compile time. No new VDBE opcodes; `max_invariant=45` unchanged. One new reserved keyword: `KEYWORD_VIEW`. All other tokens (`CREATE`, `DROP`, `IF`, `NOT`, `EXISTS`, `AS`, `TEMP`) already reserved.

### Phase 6ac grammar

```
create-view-stmt := KEYWORD_CREATE [ KEYWORD_TEMP ] KEYWORD_VIEW
                    [ KEYWORD_IF KEYWORD_NOT KEYWORD_EXISTS ]
                    IDENTIFIER
                    [ LPAREN IDENTIFIER ( COMMA IDENTIFIER )* RPAREN ]
                    KEYWORD_AS select-stmt

drop-view-stmt := KEYWORD_DROP KEYWORD_VIEW [ KEYWORD_IF KEYWORD_EXISTS ] IDENTIFIER
```

`TEMP` is accepted and ignored in v1 (no separate temp schema).

### Phase 6ac semantics

**CREATE VIEW**:
1. Parse the SELECT subtree. Store the AST (or the SQL text — implementation-defined) in the catalog as a `ViewDef { name, columns?, select_ast, original_sql }`.
2. Column resolution within the view's SELECT is deferred until view USE site. CREATE VIEW does NOT require the referenced tables to exist at create time (SQLite permits forward-declared views); v1 may require the tables to exist — implementation-defined. If the fixture requires either, pin via test.
3. Optional `(col1, col2, …)` list: renames the view's projection. Column count MUST equal the SELECT's output arity → `COMPILE_VIEW_COLUMN_COUNT_MISMATCH` otherwise.
4. Duplicate view name (without IF NOT EXISTS) → `COMPILE_DUPLICATE_VIEW`.

**Reference resolution**: when compiling a query that references a view name in FROM, the compiler substitutes the stored SELECT AST in place of the table reference, with output columns renamed per the optional view column list. Then compiles the whole resulting query normally. Recursion limit 16 levels → `COMPILE_VIEW_RECURSIVE` (not fixture-exercised in v1).

**DROP VIEW**:
- `DROP VIEW name` → remove from catalog. If absent: `COMPILE_UNKNOWN_VIEW`.
- `DROP VIEW IF EXISTS name` → no-op if absent.

**Writability**: INSERT / UPDATE / DELETE targeting a view name → `COMPILE_VIEW_NOT_WRITABLE`. (SQLite's writable views via INSTEAD OF triggers are deferred until triggers phase.)

### Phase 6ac errors

- `COMPILE_DUPLICATE_VIEW { name }` — CREATE VIEW of an already-existing name without IF NOT EXISTS.
- `COMPILE_UNKNOWN_VIEW { name }` — DROP VIEW of a missing name without IF EXISTS.
- `COMPILE_VIEW_COLUMN_COUNT_MISMATCH { view, declared, select_output }` — explicit column list length ≠ SELECT arity.
- `COMPILE_VIEW_NOT_WRITABLE { view }` — DML targeting a view in v1.
- `COMPILE_VIEW_RECURSIVE { view }` — view-reference chain exceeds depth 16.

### Phase 6ac non-goals (v1)

- `INSTEAD OF` triggers on views → permanent deferral until triggers phase.
- Materialized views (cached result sets) → not in v1.
- TEMP semantics (separate temp schema) → accepted-and-ignored.
- View name shadowing a table of the same name → raise at CREATE.

### Test authority (Phase 6ac)

`tests/cross-build/phase6ac.json`.

## Phase 6aw — `PRAGMA` core subset (introspection + header metadata)

Phase 6aw adds a narrow, test-corpus-motivated set of PRAGMAs. One new reserved keyword: `KEYWORD_PRAGMA`. No new VDBE opcodes (PRAGMAs use existing opcodes for catalog walks and header reads). `max_invariant=45` unchanged.

### Phase 6aw grammar

```
pragma-stmt := KEYWORD_PRAGMA IDENTIFIER
             | KEYWORD_PRAGMA IDENTIFIER LPAREN pragma-arg RPAREN
             | KEYWORD_PRAGMA IDENTIFIER EQ pragma-value

pragma-arg   := IDENTIFIER | INTEGER_LITERAL | STRING_LITERAL
pragma-value := INTEGER_LITERAL | IDENTIFIER | STRING_LITERAL
```

### Phase 6aw supported PRAGMAs

**Read-only introspection** (return rows):

| PRAGMA | Form | Output columns |
|---|---|---|
| `table_info(<name>)` | function-like | `cid INTEGER, name TEXT, type TEXT, notnull INTEGER, dflt_value TEXT?, pk INTEGER` |
| `index_list(<table>)` | function-like | `seq INTEGER, name TEXT, unique INTEGER, origin TEXT, partial INTEGER` |
| `index_info(<index>)` | function-like | `seqno INTEGER, cid INTEGER, name TEXT` |
| `page_size` | bare | `INTEGER` (always 4096 in v1) |
| `page_count` | bare | `INTEGER` |

**Header metadata** (read/write):

| PRAGMA | Bare form returns | `= N` form effect |
|---|---|---|
| `application_id` | 32-bit int at file offset 68 | sets same offset |
| `user_version` | 32-bit int at file offset 60 | sets same offset |

**Accept-and-ignore**:

| PRAGMA | behavior |
|---|---|
| `foreign_keys` | stored; returned; no runtime effect in v1 |

**Unknown PRAGMA name** → silent no-op, zero rows, no error. This matches SQLite behavior and is critical for corpus compatibility.

### Phase 6aw semantics

- `<value>` in the write form: integer literal accepted verbatim; identifier `ON`/`YES`/`TRUE` folds to 1; `OFF`/`NO`/`FALSE` folds to 0.
- `table_info(nonexistent_table)` → zero rows, no error (SQLite semantics).
- `index_list` ordering: newest index first (seq 0 = most recently created). Implicit auto-indexes have origin `"u"` (UNIQUE) or `"pk"` (PRIMARY KEY).
- `dflt_value` in `table_info`: the original SQL text of the default (quoted for string literals, bare for numeric). NULL if no default declared.

### Phase 6aw errors

- `PARSE_UNEXPECTED_TOKEN` — malformed PRAGMA syntax.

No new runtime error names — unknown PRAGMAs are silently accepted.

### Phase 6aw non-goals (v1)

- `PRAGMA integrity_check` / `quick_check` — deferred (runs a full DB walk algorithm).
- `PRAGMA journal_mode`, `cache_size`, `synchronous` — accepted but no-op; not fixture-tested here.
- `PRAGMA compile_options` — deferred.
- `PRAGMA pragma_list` — deferred.
- `PRAGMA optimize` — deferred.

### Test authority (Phase 6aw)

`tests/cross-build/phase6aw.json`.

## Phase 6ah — `IN (subquery)` predicate (uncorrelated)

Extends the Phase 6v `IN (expr-list)` predicate with an `IN (SELECT …)` form. Uncorrelated-only in v1 (subquery must not reference outer-scope names; correlated IN-subquery deferred). No new VDBE opcodes if the implementation desugars to an ephemeral-set-probe using existing 9be machinery; otherwise one new opcode kind for the set probe is acceptable (flag it).

### Phase 6ah grammar

```
comparison-rhs := ... | [ KEYWORD_NOT ] KEYWORD_IN LPAREN select-stmt RPAREN
```

The select-stmt form is disambiguated from the expr-list form at parse time by looking for `KEYWORD_SELECT` as the first token after `LPAREN`.

### Phase 6ah semantics

- Subquery MUST return exactly 1 column. Otherwise → `COMPILE_SUBQUERY_WRONG_ARITY`.
- Subquery evaluated once (uncorrelated in v1), result set materialized.
- For each outer row: test membership.
- 3VL / NULL propagation: same rules as Phase 6v:
  - `x IN (subq)`: if `x = v` for any row `v`, result = 1. If `x` NULL, result = NULL. If no match and subq contains any NULL, result = NULL. If no match and no NULL, result = 0. Empty subq → 0 regardless of x.
  - `x NOT IN (subq)`: negation with NULL poison (any NULL in subq → NULL when no match found). Empty subq → 1.

### Phase 6ah errors

- `COMPILE_SUBQUERY_WRONG_ARITY { expected: 1, got: N }` — subquery in IN-form returned more than 1 column.

### Phase 6ah non-goals (v1)

- Correlated IN-subquery — deferred until the outer-scope threading mechanism can be generalized from 6ag.
- Row-valued `(a, b) IN (SELECT x, y FROM t)` — permanent non-goal for v1.

### Test authority (Phase 6ah)

`tests/cross-build/phase6ah.json`.

## Phase 6aq — `NATURAL JOIN` and `JOIN ... USING (col-list)`

Parser + compile desugar to existing JOIN ON machinery. No new VDBE opcodes. Two new reserved keywords: `KEYWORD_NATURAL`, `KEYWORD_USING`. `max_invariant=45` unchanged.

### Phase 6aq grammar

```
join-source := table-source [ KEYWORD_NATURAL ] [ join-type ] KEYWORD_JOIN table-source join-constraint?
join-constraint := KEYWORD_ON expression
                 | KEYWORD_USING LPAREN IDENTIFIER ( COMMA IDENTIFIER )* RPAREN
                 | (nothing — only valid after NATURAL)
```

`NATURAL` is a prefix modifier on the JOIN keyword; the resulting JoinSource carries a `natural: bool` flag. `USING (…)` is an alternative to `ON <expr>` as the join-constraint.

### Phase 6aq semantics

**NATURAL JOIN**: at compile time, compute the set `shared = columns(left) ∩ columns(right)` by name. Synthesize `ON left.col = right.col AND …` for each shared column. If `shared` is empty, synthesize `ON 1` (cross-product). Matches SQLite.

**JOIN USING (col1, col2, …)**: each `col_i` must appear in BOTH left and right columns → `COMPILE_USING_COLUMN_NOT_FOUND` otherwise. Synthesize `ON left.col1 = right.col1 AND left.col2 = right.col2 AND …`.

**Column-coalescing rule (SQLite)**: for both NATURAL and USING, the shared/using columns are projected exactly ONCE in `SELECT *` output (coalesced, typically from the left side). v1 must implement this for `*`-projection correctness; for explicit-column SELECTs the rule is inactive. Fixture uses explicit projections — coalescing is dormant in the test.

**LEFT variant**: `NATURAL LEFT JOIN` / `LEFT JOIN … USING (…)` inherit Phase 6e's LEFT-join NULL-emission semantics.

### Phase 6aq errors

- `COMPILE_USING_COLUMN_NOT_FOUND { column }` — USING column not in both tables.

### Phase 6aq non-goals (v1)

- `FULL OUTER JOIN` — permanent v1 non-goal (mainline SQLite also lacks it until 3.39).
- `RIGHT OUTER JOIN` — permanent v1 non-goal (mainline SQLite also lacks it until 3.39).
- Three-way NATURAL JOIN chain with transitive column-name resolution — v1 handles pairwise only.

### Test authority (Phase 6aq)

`tests/cross-build/phase6aq.json`.

## Phase 6ap — `GROUP_CONCAT` + `TOTAL` aggregates

Two new aggregate functions. No new VDBE opcode kind — reuses existing AggStep infrastructure. No new keywords (resolved as identifiers). `max_invariant=45` unchanged.

### Phase 6ap semantics

**GROUP_CONCAT**:
- `GROUP_CONCAT(expr)` — concatenate string-coerced values with default separator `","`.
- `GROUP_CONCAT(expr, sep)` — explicit separator (constant TEXT expression, evaluated once).
- Skip NULL values silently.
- Empty input (or all-NULL after skip) → NULL (standard aggregate).
- Non-text coerced to text via existing standard coercion (int → decimal, real → 6r's `%!.15g`).
- Order is implementation-defined per SQLite; v1 uses insertion / scan order.

**TOTAL**:
- Numerically equivalent to SUM, with ONE difference: empty / all-NULL input → `0.0` (not NULL). Always returns REAL.

### Phase 6ap errors

No new error kinds.

### Phase 6ap non-goals (v1)

- `GROUP_CONCAT(DISTINCT x)` — defer to follow-up; requires 6ai DISTINCT machinery integrated with text-accumulator.
- `GROUP_CONCAT(x ORDER BY y)` — permanent non-goal in v1.

### Test authority (Phase 6ap)

`tests/cross-build/phase6ap.json`.

## Phase 6as — compound SELECT with heterogeneous column types

Phase 6as relaxes the implicit per-column type-equality assumption across UNION / UNION ALL / EXCEPT / INTERSECT branches. SQLite permits type divergence across branches. Dedup uses the existing **affinity equality** rule (same rules as the `=` operator, same as 6g numeric coercion) — NOT the stricter 6bc IN-list rule. No grammar change, no new opcodes, no keyword change.

### Phase 6as semantics

- Branch arity MUST still match (same number of projected columns per branch); only types may differ. Arity mismatch → existing `COMPILE_COMPOUND_ARITY_MISMATCH`.
- Rows with mixed types across branches are unified in the output with their original types preserved — no coercion.
- Dedup uses **affinity equality** via the existing SortValueEq infrastructure: `1 == 1.0` (both numeric, equal magnitude → dedup), `1 != '1'` (TEXT vs numeric → distinct), `NULL ↔ NULL` treated as equal for dedup purposes. First-seen value wins when a dedup collision occurs.
- Do NOT introduce strict type-aware equality for this phase — the 6bc IN-list rule is specifically scoped to IN-list and does not extend to compound-SELECT dedup. Reusing the existing affinity equality path is both correct and keeps 6o's cross-type numeric dedup passing.
- NULL behavior unchanged.
- Result-set typestring (for the runner): `?` or GENERIC for columns whose branch-types diverge.

### Phase 6as non-goals

- Strict type-aware equality for compound-SELECT dedup (permanent — would contradict SQLite and 6o).
- FULL JOIN-style type widening across branches.

### Test authority (Phase 6as)

`tests/cross-build/phase6as.json`.

## Phase 6bf — `ALTER TABLE` subset: RENAME TABLE, RENAME COLUMN, ADD COLUMN

Catalog mutator. `max_invariant=45` unchanged. One new reserved keyword: `KEYWORD_ALTER`. **`RENAME`, `TO`, `ADD`, `COLUMN` are matched contextually as IDENTIFIER text inside the alter-table parser** (they are NOT reserved) — this preserves Phase 6t's `ROLLBACK TO savepoint-name` which pins `TO` lexing as an IDENTIFIER. Both C and Rust generators independently converged on this (cross-corroborated).

Catalog mutation is dispatched via **one or more new VDBE opcodes** — implementation choice: the C target uses a single multiplexed `OP_ALTERTABLE` with an action-discriminator field; the Rust target uses three separate opcodes `AlterRenameTable` / `AlterRenameColumn` / `AlterAddColumn`. Both are valid. The pre-amendment spec claim of "no new opcodes" was wrong — a catalog mutator needs a dispatch site, and generators may pick either style. `max_invariant=45` is nonetheless preserved since the new opcode(s) ride invariant 42's non-empty-name check.

### Phase 6bf grammar

```
alter-table-stmt := KEYWORD_ALTER KEYWORD_TABLE IDENTIFIER alter-action

alter-action := KEYWORD_RENAME KEYWORD_TO IDENTIFIER
              | KEYWORD_RENAME [ KEYWORD_COLUMN ] IDENTIFIER KEYWORD_TO IDENTIFIER
              | KEYWORD_ADD    [ KEYWORD_COLUMN ] column-def
```

### Phase 6bf semantics

**RENAME TABLE**: mutate catalog entry; update index entries that reference the old table name; no data movement (rowid-keyed). Missing table → `COMPILE_UNKNOWN_TABLE`; target name collision → `COMPILE_DUPLICATE_TABLE`.

**RENAME COLUMN**: mutate catalog's column name; update index entries; no data movement. Missing table/column → corresponding `COMPILE_UNKNOWN_*`.

**ADD COLUMN**: append to catalog's column-list. Existing rows get NULL (or DEFAULT if declared) on read — lazy fill via short-serial-type-array handling. Duplicate name → `COMPILE_DUPLICATE_COLUMN`.

### Phase 6bf errors

- `COMPILE_UNKNOWN_TABLE`, `COMPILE_UNKNOWN_COLUMN` — canonical compile-time errors when a table/column reference resolves against a dropped, renamed-away, or never-existed name. NOTE: the existing `STORAGE_TABLE_NOT_FOUND` / `STORAGE_COLUMN_NOT_FOUND` continue to exist for storage-layer (runtime) misses; generators bridge compile → storage via either a tombstone-in-catalog mechanism (C) or a harness error-name alias layer (Rust). Both approaches have been cross-corroborated across Phase 6ac and Phase 6bf; the canonical rule is: **compile-phase resolution misses raise `COMPILE_UNKNOWN_*`; runtime storage misses raise `STORAGE_*`**.
- `COMPILE_DUPLICATE_TABLE`, `COMPILE_DUPLICATE_COLUMN` — **new canonical error kinds in 6bf** (the pre-amendment spec incorrectly labeled these as "reused"). Both generators independently added the same names with identical wording, confirming the canonical form.

### Phase 6bf non-goals (v1)

- `DROP COLUMN` (SQLite 3.35+) — deferred.
- ADD COLUMN with `PRIMARY KEY` or `UNIQUE` — permanent v1 non-goal (would require data rewrite).
- ADD COLUMN with CHECK — deferred until after 6at.
- `ALTER TABLE … ALTER COLUMN … <TYPE>` — permanent non-goal (SQLite doesn't support at all).

### Test authority (Phase 6bf)

`tests/cross-build/phase6bf.json`.

## Phase 6bg — `RETURNING` clause on INSERT / UPDATE / DELETE

Extends DML statements with a SELECT-like projection of affected rows. No new VDBE opcodes — reuses ResultRow emission. `max_invariant=45` unchanged. One new reserved keyword: `KEYWORD_RETURNING`.

### Grammar

```
insert-stmt | update-stmt | delete-stmt := <existing> [ returning-clause ]
returning-clause := KEYWORD_RETURNING projection-list [ KEYWORD_ORDER KEYWORD_BY ordering-term ( COMMA ordering-term )* ]
```

`ORDER BY` on RETURNING mirrors SELECT's ORDER BY grammar (no LIMIT). Fixtures exercise this form.

### Semantics

- **INSERT RETURNING**: emit one result row per inserted tuple, using POST-INSERT values (defaults applied, AUTOINCREMENT rowid populated). Row-capture mechanism: read from the still-positioned table cursor after `InsertRow` + index maintenance. (Both C and Rust generators converged on this timing — cross-corroborated.)
- **UPDATE RETURNING**: emit one result row per WHERE-matched row, using POST-UPDATE values. Row-capture: read from the in-place-mutated cursor inside the per-row loop, after `UpdateRow`.
- **DELETE RETURNING**: emit one result row per deleted row, using PRE-DELETE values. Row-capture: emit ResultRow (or SorterInsert if ORDER BY is present) BEFORE `DeleteRow`, while cursor is still on the live row.
- `RETURNING *` = all columns of the target table in declared order.
- Expressions: same expression grammar as SELECT projection (arithmetic, CASE, functions, column-refs to the target-row columns).
- When `ORDER BY` is present, the generator opens a sorter at statement start, routes per-row RETURNING projections through SorterInsert instead of ResultRow, then after the DML loop emits a standard SorterSort/SorterRewind/SorterRead/ResultRow/SorterNext drain loop. This is the canonical mechanism; generators that rely on natural emit-order coincidentally matching the ORDER BY key are fragile and will regress under non-natural-key ORDER BY fixtures.

### Errors

No new error kinds.

### Non-goals (v1)

- Subqueries in RETURNING expressions — accepted if free from existing expression parser, not explicitly tested.
- `RETURNING` combined with `ON CONFLICT DO UPDATE` is EXPLICITLY supported (both 6bg and 6bh can appear in the same INSERT); fixtures do not exercise it but the grammar composes via `insert-stmt := <existing> [ upsert-clause ] [ returning-clause ]` and both generators correctly emit RETURNING on both UPSERT branches.

### Test authority (Phase 6bg)

`tests/cross-build/phase6bg.json`.

## Phase 6bh — UPSERT: `ON CONFLICT(target) DO NOTHING | DO UPDATE SET …`

Extends Phase 6ab's OR-IGNORE/OR-REPLACE INSERT forms with SQL-standard UPSERT: an explicit `conflict_target` column-list and an action (DO NOTHING or DO UPDATE with optional WHERE). Pseudo-table `excluded.*` refers to the would-be-inserted row inside the DO UPDATE action.

No new VDBE opcodes; reuses 9g UNIQUE-probe + UpdateRow + InsertRow + DeleteRow. `max_invariant=45` unchanged. One new reserved keyword: `KEYWORD_EXCLUDED`. `ON`, `CONFLICT`, `DO`, `NOTHING`, `SET`, `UPDATE` may already be reserved — verify.

### Grammar

```
insert-stmt := <existing-insert-grammar> [ upsert-clause ] [ returning-clause ]

upsert-clause := KEYWORD_ON KEYWORD_CONFLICT LPAREN IDENTIFIER ( COMMA IDENTIFIER )* RPAREN upsert-action

upsert-action := KEYWORD_DO KEYWORD_NOTHING
               | KEYWORD_DO KEYWORD_UPDATE KEYWORD_SET assignment ( COMMA assignment )* [ KEYWORD_WHERE expression ]

assignment := IDENTIFIER EQ expression
```

### Semantics

**Conflict-target resolution** (compile time): the column-list must correspond to either the table's PRIMARY KEY or a UNIQUE index's key columns. Unmatched → `COMPILE_NO_CONFLICT_TARGET`.

**DO NOTHING**: on conflict with the named target, skip the row silently. Conflicts with DIFFERENT targets still propagate (differs from OR IGNORE which swallows any conflict).

**DO UPDATE SET**: on conflict with the named target:
1. Fetch the existing row.
2. Evaluate the assignments with two scopes: bare column-refs = existing-row values; `excluded.col` = would-be-inserted values.
3. If a WHERE predicate is present, evaluate (same dual scope). If false, skip the update (row unchanged, no error).
4. If true, emit UpdateRow.

**No conflict**: UPSERT clause is inert; normal INSERT.

### Errors

- `COMPILE_NO_CONFLICT_TARGET { columns }` — conflict-target doesn't match any PK / UNIQUE index.
- `COMPILE_EXCLUDED_COLUMN_NOT_FOUND` — `excluded.<col>` references a non-existent column.

### Non-goals (v1)

- Multi-constraint (target-less) ON CONFLICT — permanent non-goal.
- UPSERT combined with INSERT ... SELECT — deferred.
- WHERE on DO NOTHING — not meaningful; permanent non-goal.

### Test authority (Phase 6bh)

`tests/cross-build/phase6bh.json`.

## Phase 6bi — STRICT tables (type enforcement at INSERT/UPDATE)

Extends CREATE TABLE with a `STRICT` modifier that enforces declared types at row-write time, matching SQLite 3.37+. One new reserved keyword `KEYWORD_STRICT`. One new runtime error `RUNTIME_STRICT_TYPE_MISMATCH`. No new VDBE opcodes. `max_invariant=45` unchanged.

### Grammar

```
create-table-stmt := <existing> [ KEYWORD_STRICT ]
```

### Semantics

- Non-STRICT tables: classic SQLite type-affinity permissiveness. Includes **TEXT→numeric coercion via parse-attempt** — when a TEXT value is inserted into an INTEGER column and parses cleanly as `int64`, it is stored as INTEGER; similarly TEXT parsing cleanly as `float64` goes into REAL columns. Non-parseable TEXT into a numeric column still raises `STORAGE_TYPE_MISMATCH`. REAL→INTEGER (e.g., `1.5` into INTEGER) is NOT coerced in non-strict mode either — matches SQLite's "loose affinity" rules. Both C and Rust generators independently discovered and added this path for the `non-strict-table-still-permissive` fixture — cross-corroborated.
- STRICT tables: declared column type enforced literally.
  - `INT` / `INTEGER` → INTEGER only.
  - `REAL` → REAL; INTEGER accepted and widened to REAL.
  - `TEXT` → TEXT only.
  - `BLOB` → BLOB only.
  - `ANY` → any type accepted (no enforcement).
- NULL always accepted unless NOT NULL is also declared.
- Mismatch at INSERT / UPDATE → `RUNTIME_STRICT_TYPE_MISMATCH`.
- Enforcement site: storage layer (`insert_row` / `update_row_at`), not compile-time. Both generators converged on this.
- Parse-point for STRICT modifier: lexed as a full reserved keyword (`KEYWORD_STRICT`). Checked contextually by the CREATE TABLE parser after the closing RPAREN. Both generators chose full reservation; a column named `strict` will fail parse. No existing fixture needs `strict` as an identifier.

### Non-goals (v1)

- Storage-layer fast-path for strict tables (same-size integers, packed reals) — deferred.
- ALTER TABLE turning non-strict strict or vice versa — permanent non-goal (SQLite doesn't support).

### Test authority (Phase 6bi)

`tests/cross-build/phase6bi.json`.

## Phase 6bj — GENERATED (virtual) columns

Computed columns whose value is derived from an expression over the row's other columns; evaluated on every read. VIRTUAL only in v1. One new reserved keyword `KEYWORD_GENERATED`. One new runtime error `RUNTIME_CANNOT_INSERT_INTO_GENERATED_COLUMN`. No new VDBE opcodes.

### Grammar

```
column-def := IDENTIFIER [ type-decl ] ( column-constraint | generated-clause )*
generated-clause := [ KEYWORD_GENERATED KEYWORD_ALWAYS ] KEYWORD_AS LPAREN expression RPAREN [ KEYWORD_VIRTUAL ]
```

`STORED` keyword is permanent non-goal in v1 — reject at parse time.

### Semantics

- **Storage slot for a generated column**: implementation choice. Either (a) physically omit the slot from the row's serial-type array (spec's original prescription), or (b) keep the slot position but permanently carry `Null` there as a placeholder (harmless — the substitution pass below ensures no code path ever reads it). Both C and Rust generators independently chose (b); canonized as valid.
- INSERT / UPDATE explicitly naming a generated column → `RUNTIME_CANNOT_INSERT_INTO_GENERATED_COLUMN`.
- SELECT / WHERE / ORDER BY / GROUP BY reference: **substitute the generated expression inline at compile time** via either an AST pre-pass (Rust approach) or in-place substitution at column-ref resolution (C approach). Both target styles are valid. The runtime row decoder does not know about generated columns — every read is lowered to the stored expression by the compiler.
- Generated expression must reference only other columns of the same row; no subqueries, no aggregates, no cross-row refs. No references to other generated columns (compile-time cycle detection → `COMPILE_GENERATED_COLUMN_RECURSIVE` — reserved; v1 fixtures don't exercise, generators may leave cycle detection unwired).
- Positional INSERT (no explicit column list) into a table with generated columns: the compiler must pad the user's N-wide tuple with Null at each generated slot position so the tuple matches the catalog's column count. Both generators do this.

### Non-goals (v1)

- STORED generated columns — reject (permanent v1 non-goal).
- Generated column in UNIQUE / PRIMARY KEY / INDEX — defer.
- References to other generated columns — defer.

### Test authority (Phase 6bj)

`tests/cross-build/phase6bj.json`.

## Phase 6at — CHECK constraints

Adds `CHECK (expression)` as a column-constraint and as a table-constraint. Evaluated on INSERT / UPDATE. One new reserved keyword `KEYWORD_CHECK`. One new runtime error `RUNTIME_CHECK_CONSTRAINT_FAILED`. No new VDBE opcodes (expression-compile reused from WHERE path).

### Grammar

```
column-constraint := <existing> | KEYWORD_CHECK LPAREN expression RPAREN
table-constraint  := <existing> | KEYWORD_CHECK LPAREN expression RPAREN
```

### Semantics

- For each CHECK on the table (in declaration order), evaluate expression over the new-row values. Result TRUE → pass. Result NULL → **pass** (SQLite three-valued-logic: CHECK fails only on strict FALSE). Result FALSE → fail with `RUNTIME_CHECK_CONSTRAINT_FAILED { table, constraint_index }`.
- Column-level CHECK may reference any column of the row, not only its own column.
- Expression constraints: no subqueries, no aggregates, no cross-row references.
- Evaluation halts at first failing constraint; statement aborted with no side effects (caller's transactional scope rolls back its own row changes).

### Non-goals (v1)

- Named CHECK via `CONSTRAINT <name> CHECK (…)` — name is parsed and discarded; error reports index only.
- CHECK referencing other tables or `sqlite_master` — defer.
- Deferred CHECK (evaluated at statement boundary) — not supported by SQLite either.

### Test authority (Phase 6at)

`tests/cross-build/phase6at.json`.

## Phase 6au — multi-column table-level PRIMARY KEY

Table-level `PRIMARY KEY (col, …)` declares a composite PK. Composite PK = tuple UNIQUE + every member NOT NULL; an auto-index is created over the composite key.

### Grammar

```
table-constraint := <existing>
                  | KEYWORD_PRIMARY KEYWORD_KEY LPAREN column-name ( COMMA column-name )* RPAREN
```

### Semantics

- Each member column is implicitly NOT NULL. NULL in any member on INSERT/UPDATE → `RUNTIME_NOT_NULL_VIOLATION { table, column }` (first NULL member).
- The tuple of PK columns must be unique across the table. Duplicate → `RUNTIME_UNIQUE_VIOLATION { table, columns }` — **new canonical error kind in 6au**, split from the pre-existing `STORAGE_UNIQUE_VIOLATION { index, key }`. Route the new runtime-name only when the violating UNIQUE index's columns exactly match the table's `primary_key_columns` list; non-PK UNIQUE violations continue to raise `STORAGE_UNIQUE_VIOLATION` (preserves prior phase fixtures). Both generators independently hit this split — canonize.
- Auto-created UNIQUE index named `sqlite_autoindex_<table>_1` over PK columns in declaration order. Participates in query planner like any other composite index (Phase 9d).
- Only one PRIMARY KEY clause per table. Combining column-level PRIMARY KEY with table-level PRIMARY KEY → `COMPILE_MULTIPLE_PRIMARY_KEYS { table }`.
- Composite PK tables are rowid tables (not `WITHOUT ROWID`). The implicit rowid remains the physical row identifier; the composite PK is a UNIQUE index.

### Non-goals (v1)

- `WITHOUT ROWID` — defer.
- Per-member ASC / DESC in the PK column list — accepted and ignored.
- Composite foreign-key referencing a composite PK — defer.

### Test authority (Phase 6au)

`tests/cross-build/phase6au.json`.

## Phase 6av — date/time functions (core subset)

Five scalar functions: `date()`, `time()`, `datetime()`, `julianday()`, `strftime()`. Timestring grammar accepts ISO-8601 forms and the literal `'now'` (pinned to a constant in v1). Modifier grammar supports day/hour/minute/second arithmetic and `start of <unit>` truncations. No timezone support in v1.

### Function signatures

```
date(timestring, modifier, ...)      → TEXT 'YYYY-MM-DD'
time(timestring, modifier, ...)      → TEXT 'HH:MM:SS'
datetime(timestring, modifier, ...)  → TEXT 'YYYY-MM-DD HH:MM:SS'
julianday(timestring, modifier, ...) → REAL (UT julian day number)
strftime(format, timestring, modifier, ...) → TEXT
```

Any NULL argument → NULL result.

### Timestring forms accepted

- `'YYYY-MM-DD'` (midnight of that date)
- `'YYYY-MM-DD HH:MM:SS'`, `'YYYY-MM-DDTHH:MM:SS'`, `'YYYY-MM-DD HH:MM'`
- real number → julian day
- `'now'` → constant `2026-04-19 00:00:00` in v1 (deterministic)

Unparseable → `RUNTIME_INVALID_TIMESTRING { input }`.

### Modifier forms

- `'+N days'`, `'-N days'`, `'+N hours'`, `'-N hours'`, `'+N minutes'`, `'-N minutes'`, `'+N seconds'`, `'-N seconds'`
- `'start of day'`, `'start of month'`, `'start of year'`
- `'unixepoch'` (interprets prior numeric arg as unix seconds; must be first modifier)

Unknown modifier → `RUNTIME_INVALID_TIMESTRING`.

### strftime format specifiers

`%Y`, `%m`, `%d`, `%H`, `%M`, `%S`, `%j`, `%w`, `%%`. Any other `%X` → `RUNTIME_INVALID_TIMESTRING { format }`.

### Non-goals (v1)

- `localtime` / `utc` modifiers (no tz database).
- `'weekday N'` modifier.
- Fractional seconds in output.
- `'DDDDDDDDDD'` 10-digit unix-timestamp auto-detect.

### Test authority (Phase 6av)

`tests/cross-build/phase6av.json`.

## Phase 6ax — sqlite_master / sqlite_schema introspection

Two read-only catalog tables with identical content: `sqlite_master` (historical name) and `sqlite_schema` (modern alias).

### Schema

```
sqlite_master(
  type     TEXT,     -- 'table' | 'index' | 'view' | 'trigger'
  name     TEXT,
  tbl_name TEXT,     -- owning table (self for table/view rows)
  rootpage INTEGER,  -- 0 for views / auto-indexes in v1
  sql      TEXT      -- original CREATE text; NULL for implicit objects
)
```

### Semantics

- Rowset is the current catalog snapshot at query start. Insertion order unless caller specifies ORDER BY.
- `sqlite_schema` is an alias: same rowset, same column layout.
- Implicit objects (auto-indexes from PRIMARY KEY / UNIQUE) have `sql = NULL`.
- The introspection tables themselves do not appear in their own rowset.
- `rootpage` = real b-tree root for tables / user indexes; 0 for views and auto-indexes.
- Supports full SELECT grammar (WHERE, ORDER BY, JOIN against user tables, subqueries).
- Write attempts (INSERT / UPDATE / DELETE / DROP) → `RUNTIME_READONLY_TABLE { table }`.

### Non-goals (v1)

- Writable schema via `PRAGMA writable_schema=ON`.
- `sqlite_temp_master` / `sqlite_temp_schema` (no temp DB in v1).
- `sqlite_stat1` / `sqlite_stat4` (no ANALYZE yet).

### Test authority (Phase 6ax)

`tests/cross-build/phase6ax.json`.

## Phase 6bk — WINDOW functions (minimal: ROW_NUMBER)

Adds an `OVER (…)` clause to function-call syntax and the single window function `ROW_NUMBER()`. Supports `PARTITION BY` and `ORDER BY` inside OVER. No explicit frame clause. New reserved keywords `KEYWORD_OVER`, `KEYWORD_PARTITION`, `KEYWORD_WINDOW`.

### Grammar

```
function-expr := IDENTIFIER LPAREN [ expression-list ] RPAREN [ over-clause ]
over-clause   := KEYWORD_OVER LPAREN [ partition-clause ] [ order-by-clause ] RPAREN
partition-clause := KEYWORD_PARTITION KEYWORD_BY expression ( COMMA expression )*
```

`ROW_NUMBER()` without an OVER → `COMPILE_WINDOW_FUNCTION_WITHOUT_OVER { function }`. Any window-function identifier other than `ROW_NUMBER` in v1 → `COMPILE_UNSUPPORTED_WINDOW_FUNCTION { function }`.

### Semantics

- Sort-and-scan materialization: materialize the SELECT's rowset, optionally partition, sort within partition by the OVER's ORDER BY, emit 1-based row number per partition.
- The outer SELECT's own ORDER BY runs after the window pass.
- Window runs after GROUP BY (v1 fixtures do not mix GROUP BY + window).
- No frame clause support; parser rejects `ROWS / RANGE / GROUPS BETWEEN …` syntax with `COMPILE_UNSUPPORTED_WINDOW_FRAME`.

### Implementation level (mandatory)

**This phase must be implemented at ENGINE level in both targets**, not at test-harness level. Specifically:
- Tokenizer must reserve `OVER`, `PARTITION`, `WINDOW` as proper keywords (not leave them as plain IDENTIFIERs matched contextually inside a phase driver).
- Parser must add `parse_optional_over_clause` or equivalent that runs for any function call in the main expression parser — not only for recognized window-function names inside the phase driver.
- Compiler must add a `compile_select_window` dispatch that emits real VDBE opcodes (existing sorter / SortValueEq / Add / Copy / JumpIfFalse / ResultRow suffice — no new opcodes needed).
- The phase-6bk fixture driver must be a plain `compile → execute → assert` loop using the main engine — same shape as `phase6bi_main.c` / `phase6bi_test.rs` — NOT a mini-parser + window executor.

Rationale: the sqlite-leap stunt claims "same spec generates equivalent implementations in both languages". A harness-only implementation means sqllogictest queries containing `ROW_NUMBER() OVER (…)` would fail at the real engine while passing inside the phase driver, breaking the equivalence claim. **This rule applies to every future phase: implementations live in the engine; the phase driver is only a fixture runner.**

### Non-goals (v1)

- RANK, DENSE_RANK, LAG, LEAD, NTILE, aggregate-OVER (SUM/COUNT/… OVER), FIRST_VALUE, LAST_VALUE, NTH_VALUE.
- Explicit frame clauses (ROWS/RANGE/GROUPS BETWEEN).
- Named windows via `WINDOW w AS (…)` clause; parsed-and-rejected.
- Multiple OVER specs per SELECT sharing a common WINDOW clause.

### Test authority (Phase 6bk)

`tests/cross-build/phase6bk.json`.

## Phase 6bl — WITH RECURSIVE (recursive CTE)

Extends Phase 6aa (non-recursive CTEs) with self-referential CTE bodies. A CTE is recursive iff its body references itself in any branch of a top-level compound SELECT (UNION / UNION ALL). Evaluation is iterative fixed-point: anchor produces the initial rows; recursive-select reads from the working-set; loop until empty. One new reserved keyword `KEYWORD_RECURSIVE`. No new VDBE opcodes (reuses sorter + ResultRow infra).

### Grammar

```
with-clause := KEYWORD_WITH [ KEYWORD_RECURSIVE ] cte-decl ( COMMA cte-decl )*
cte-decl    := IDENTIFIER [ LPAREN column-name ( COMMA column-name )* RPAREN ] KEYWORD_AS LPAREN select-stmt RPAREN
```

`RECURSIVE` is a parse-time hint; recursion is decided at compile time by scanning for self-references, not by keyword presence.

### Semantics

Execution for `WITH RECURSIVE r AS (anchor UNION ALL rec)`:

1. Materialize anchor into ACC (accumulator) and WS (working-set).
2. Loop: compile-rec with `r` bound to WS (NOT ACC); append output to ACC; replace WS with output; exit when WS is empty.
3. Outer query reads `r` as ACC.

- `UNION ALL` keeps all rows; `UNION` dedups against ACC at each step (affinity equality, same rule as Phase 6as).
- Iteration cap 1000; exceed → `RUNTIME_RECURSIVE_CTE_LIMIT { cte }`.
- Column-list after CTE name pins result column names; otherwise anchor-select names flow through.
- Column counts must match across anchor and recursive branches → else `COMPILE_RECURSIVE_CTE_ARITY_MISMATCH { cte, anchor_cols, rec_cols }`.
- Self-referential CTE with no non-self-referential branch → `COMPILE_RECURSIVE_CTE_MISSING_ANCHOR { cte }`.
- CTE self-reference resolution: when compiling the recursive-select, a reference to `r` emits a sorter-rewind/read/next over WS, not ACC. This asymmetry is the core of fixed-point iteration.

### Non-goals (v1)

- Mutually recursive CTEs (a references b, b references a) — defer.
- Recursive CTE inside a subquery — defer.
- EXCEPT / INTERSECT as the compound operator in a recursive CTE — v1 supports UNION and UNION ALL only.
- Fast-path materialization — defer.

### Test authority (Phase 6bl)

`tests/cross-build/phase6bl.json`.

## Phase 6bm — Modulo operator `%` (canonized via cross-corroboration from 6bl)

During Phase 6bl implementation, both C and Rust generators independently added the `%` (modulo) infix operator — triggered by fixture `recursive-union-dedup` which uses `(n % 3) + 1`. Both targets reached identical decisions:

- New token `PERCENT` (lexed from `%`).
- New BinOp `Mod` / AST binary-op tag `"%"`.
- New VDBE opcode `Modulo` / `OP_MOD`, reusing the arithmetic operand-shape invariant (level 10 in the well-formedness ladder).
- Integer `x % 0` → NULL (SQLite-compat quirk; matches integer `x / 0` and mainline SQLite behaviour). The `EVAL_DIVISION_BY_ZERO` error kind is NOT raised for this case.
- Real path via `fmod(f64, f64)`.
- Operator at multiplicative precedence alongside `*` and `/`.

### Grammar

Already reflected in the expression grammar above: `multiplicative := concat (( STAR | SLASH | PERCENT ) concat)*`.

### Semantics

- Integer `%` rounds toward zero (consistent with C `%` and Rust `%`). `i64::MIN % -1` is defined as `0` to avoid intrinsic panics.
- Mixed-type integer/real promotes to real and uses `fmod`.
- NULL propagates as with other arithmetic.
- Division-by-zero: integer `x % 0` yields NULL per the SQLite-compat quirk (see §"Phase 2c-1 evaluation semantics" — Division by zero). `EVAL_DIVISION_BY_ZERO` is NOT raised.

### Test authority (Phase 6bm)

Covered by the `recursive-union-dedup` case in `tests/cross-build/phase6bl.json`. No standalone fixture authored in v1; if a future regression shows up, add `tests/cross-build/phase6bm.json` then.

## Phase 6bn — Parser gaps from random corpus analysis

Three parser gaps identified via 89-file random/ sqllogictest-corpus analysis (608k `PARSE_UNEXPECTED_TOKEN` failures out of 639k total, 95%). All three are parser/tokenizer-level; no new opcodes, no new errors. `max_invariant` unchanged.

### 6bn.1 — Unary `+` prefix

Grammar change (both multiplicative-tier unary productions):

```
unary := MINUS unary | PLUS unary | primary
```

Semantics: unary `+` is a no-op pass-through. Applies to all value types including NULL.

### 6bn.2 — Implicit column alias (no `AS`)

SQLite accepts `SELECT expr alias` as equivalent to `SELECT expr AS alias`. Grammar:

```
projection-item := expression [ [ KEYWORD_AS ] IDENTIFIER ]
```

Parser rule: after parsing the projection expression, if the next token is `AS`, consume it and read an IDENTIFIER (existing path). If it's a plain IDENTIFIER token that is NOT a reserved keyword and NOT one of the projection terminators (FROM, WHERE, GROUP, ORDER, LIMIT, COMMA, SEMICOLON, EOF, UNION, INTERSECT, EXCEPT, HAVING, WINDOW, OVER), consume it as the alias. Alias is visible in ORDER BY / GROUP BY / HAVING per existing Phase 6aj.

### 6bn.3 — CAST type liberality

`CAST(x AS T)` accepts any IDENTIFIER (plus the existing KEYWORD_INTEGER/REAL/TEXT special cases) as the type name, optionally followed by parenthesized size params that are parsed-and-discarded (mirroring Phase 6af for CREATE TABLE column types).

The type name is mapped to a storage affinity via the standard SQLite rule (case-insensitive substring match, first rule that matches wins):

| Type name contains | Affinity |
|---|---|
| `INT` | INTEGER |
| `CHAR`, `CLOB`, `TEXT` | TEXT |
| `BLOB`, or missing + no other rule | BLOB |
| `REAL`, `FLOA`, `DOUB` | REAL |
| else (DECIMAL, NUMERIC, BOOLEAN, …) | NUMERIC |

NUMERIC cast semantics: if the value is text, try parsing as INTEGER then REAL; on success, coerce. Else keep value unchanged. TEXT cast: use existing 6r Real→Text or integer→text paths. INTEGER / REAL casts: existing 6r paths.

Grammar:
```
cast-type := IDENTIFIER [ LPAREN INTEGER_LITERAL ( COMMA INTEGER_LITERAL )? RPAREN ]
```

### Non-goals

- CREATE TABLE column-declaration type liberality is out of scope here (already partially handled by 6af; this phase is CAST-only).
- Complex type expressions (e.g., `CAST(x AS SQL_DECIMAL)`) — v1 limits to `IDENTIFIER [LPAREN nums RPAREN]`.
- Detecting alias-name collisions with existing column names — match SQLite's permissive behavior.

### Test authority (Phase 6bn)

`tests/cross-build/phase6bn.json`.

### Open engine-level refactor

Phase 6aa, 6ac, 6bl all currently orchestrate their top-level AST forms (WITH, WITH RECURSIVE, CREATE VIEW) via driver/compile-pass interception rather than through the main `compile → vdbe-run` path. `Ast::With` returns `COMPILE_UNKNOWN_TABLE` when handed to `compile()`. This means a user query containing `WITH …` sent through the main engine (not via the phase driver) fails to compile. Same class of issue as the 6bk harness-level shortcut that was rejected, at a different scope. Fixing this requires moving CTE materialization machinery into the main compiler path — tracked as a follow-up, not part of 6bl v1.

## Phase 6bo — CROSS JOIN, ALL quantifier, bare GROUP BY columns (post-6bn residual)

Three residual gaps from random-corpus analysis after Phase 6bn landed. Each is a small targeted fix; combined they close the bulk of remaining parser + group-by failures on random/select, random/aggregates, random/groupby. No new opcodes. No new reserved keywords. `max_invariant` unchanged.

### Gap 1 — CROSS JOIN

Extend the join-op grammar to accept `CROSS JOIN` as a keyword-only cartesian product:

```
join-op := COMMA
         | KEYWORD_CROSS KEYWORD_JOIN
         | KEYWORD_INNER? KEYWORD_JOIN  ( KEYWORD_ON expr | KEYWORD_USING LPAREN col-list RPAREN )?
         | ( KEYWORD_LEFT | KEYWORD_RIGHT | KEYWORD_FULL ) KEYWORD_OUTER? KEYWORD_JOIN
             ( KEYWORD_ON expr | KEYWORD_USING LPAREN col-list RPAREN )?
         | KEYWORD_NATURAL ...
```

Semantics: `t1 CROSS JOIN t2` is identical to `t1 , t2`. **No `ON` or `USING` clause is permitted** after `CROSS JOIN`; parser rejects (falls through to `PARSE_UNEXPECTED_TOKEN`).

### Gap 2 — ALL quantifier inside aggregate function arguments

Aggregate-call grammar gains an `ALL` alternative next to `DISTINCT`:

```
aggregate-call := IDENTIFIER LPAREN [ KEYWORD_ALL | KEYWORD_DISTINCT ] expression RPAREN
                | IDENTIFIER LPAREN STAR RPAREN    (* COUNT(*) *)
```

Semantics: `ALL` is the default multiset qualifier — AST emits the same node as the unqualified form. Applies uniformly to SUM/AVG/MIN/MAX/COUNT/TOTAL/GROUP_CONCAT.

### Gap 3 — Bare column references with GROUP BY

SQLite relaxes the SQL-92 rule that every non-aggregate select-item must appear in the GROUP BY list. When a GROUP BY is present, any bare column reference is permitted and returns **a value from some row within the group** (implementation-defined which row; last-row-seen in the accumulator is fine for `rowsort`-comparing tests).

Compiler change:
- When `group_by` is present, do not raise `COMPILE_COLUMN_NOT_IN_GROUP_BY` for bare column references in SELECT / HAVING / ORDER BY.
- For a bare column *that is a group-key column*: compile as today — load from the key register.
- For a bare column *not in the group-key set* (the new case being relaxed): the emitted value must be the column's value from **the last row consumed before the group boundary**. Emitting `NULL` is **incorrect** — real sqllogictest random/groupby queries hash-compare these columns and will diverge from SQLite. Required lowering:
  1. Scan the post-group expressions (SELECT items, HAVING, ORDER BY) to identify the set of bare-non-key column references.
  2. Allocate one register per such column.
  3. In the per-row loop over a group, emit a column-load-into-register for each on every row (overwriting; no accumulator).
  4. After the group boundary, the register holds the value of the last row consumed. The emit-group body reads it as an ordinary register load.
- Aggregates continue to evaluate normally. `COMPILE_BARE_COLUMN_IN_AGGREGATE` for the *no-GROUP-BY* case is unaffected.

Error `COMPILE_COLUMN_NOT_IN_GROUP_BY` becomes unreachable by the new compiler path; generators may delete it or leave it defined-but-unreached — tests do not cover it anymore.

### Fixtures

`tests/cross-build/phase6bo.json` — 11 cases covering CROSS JOIN (basic, multi-table compose, product, alias), AGG(ALL …) across SUM/MAX/COUNT/nested-unary, and bare-column GROUP BY (plain, with aggregate, HAVING).

## Phase 6bp — SELECT without FROM + Rust dedup-slot fix (post-6bo residual)

Two narrow gaps after Phase 6bo, surfaced by investigating "timed-out" random/expr and random/aggregates files (most were actually crashing, not slow).

### Gap 1 — SELECT without FROM

SQLite accepts `SELECT <expression-list>` with no FROM clause. Produces exactly one output row built from exactly **one synthetic input row** (no columns, but its existence is what lets aggregates operate). Projection expressions evaluate against this synthetic row.

Aggregates in the projection list are applied over a set containing one element — the value of their argument expression evaluated against the synthetic row. Standard NULL-skipping rules apply:

| Aggregate | Semantics on no-FROM (one synthetic row) |
|---|---|
| `COUNT(*)` | `1` (counts rows, always 1 here) |
| `COUNT(expr)` | `1` if `expr` is non-NULL, else `0` |
| `SUM(expr)` | `expr` (or `NULL` if `expr` is NULL) |
| `TOTAL(expr)` | `expr` as REAL (or `0.0` if `expr` is NULL, per 6ap SQLite-compat) |
| `MIN(expr)` / `MAX(expr)` | `expr` (or `NULL` if `expr` is NULL) |
| `AVG(expr)` | `expr` as REAL (or `NULL` if `expr` is NULL) |
| `GROUP_CONCAT(expr [, sep])` | `expr` as TEXT (or `NULL` if `expr` is NULL) |

Non-aggregate scalar expressions evaluate normally — literals, arithmetic, CASE, COALESCE, function calls on constants. Bare column references raise `EVAL_COLUMN_WITHOUT_TABLE` (no table to resolve against).

Rationale: corpus evidence — `SELECT SUM(79)` expects `79`; `SELECT SUM(DISTINCT 11)` expects `11`; the random/expr label-6 query expects `MIN(-30) = -30`. These results are inconsistent with zero-row semantics; they require the synthetic-row model.

**Convergent-contradiction note (2026-04-20):** the first version of this spec section specified zero-row semantics. Both C and Rust generator agents independently implemented it as written and failed the two corpus-shape fixtures (`coalesce-agg-no-from`, `case-agg-no-from`). That cross-corroboration signal revealed the spec error, which was corrected here. Per project methodology, when both agents independently converge on the same implementation that fails the same fixtures, the spec is buggy, not the generators.

Compiler:
- For a SELECT with no FROM, emit one synthetic iteration: no cursor open, no scan loop, but aggregate accumulators are initialized AND updated once with the projection's argument expressions before projection emit.
- After the single update, evaluate the projection list, emit `ResultRow`, `Halt`.
- Do not dereference any table name — the C segfault via `sl_strdup(NULL)` is the proximate crash symptom.

No grammar change. This is a compiler lowering gap — the parser already accepts `SELECT` without `FROM`.

### Gap 2 — Rust dedup-slot allocation in joined-aggregated-no-GROUP-BY

Rust-only fix. `compile_joined_aggregated_no_group_by` in `src-rust/src/compiler.rs` hardcodes `num_dedup_sets: 0` but emits `AggDedupReset { dedup_slot }` when any aggregate is DISTINCT — slot indexing panics at VDBE startup.

Fix matches the pattern at the three other correct sites (lines 13749, 14401, 17448):

```
num_dedup_sets = if aggregates.iter().any(|(_, _, d)| *d) { aggregates.len() } else { 0 }
```

C target is correct for this case; single-line Rust fix.

### Fixtures

`tests/cross-build/phase6bp.json` — 11 cases: literal/expr/COUNT*/SUM/MIN/COALESCE/CASE/multi-col no-FROM shapes; SUM(DISTINCT) and COUNT(DISTINCT) over multi-table FROMs; composed `COUNT(*) + SUM(DISTINCT)` matching the random-corpus label-2081 shape.

## Phase 6bq — Parenthesized FROM expressions (post-6bp random-corpus residual)

Parser-only extension. 4596 queries in random/aggregates/ wrap their FROM source in parentheses: `SELECT … FROM (tab0 AS cor0 CROSS JOIN tab1)`. Required to unblock that corpus.

### Grammar

```
from-clause := KEYWORD_FROM from-source ( COMMA from-source )*
from-source := table-reference
             | LPAREN join-tree RPAREN
join-tree   := table-reference ( join-op table-reference )*
             | LPAREN join-tree RPAREN
```

### Semantics

The parenthesized group is identical to its unparenthesized form — parens are grouping tokens with no semantic effect. No AST node needed; parser "unwraps" on recognition. Aliasing, scoping, join-order are unchanged.

### Non-goals

- Derived tables `FROM (SELECT …)` — parser should treat a SELECT/WITH/VALUES token after LPAREN as PARSE_UNEXPECTED_TOKEN until a later phase lands proper derived-table support (see pending #61).
- Trailing alias on a parenthesized group — deferred.

### Fixtures

`tests/cross-build/phase6bq.json` — 8 cases: single-table-with-parens, parens-with-aliased-table, parens-CROSS-JOIN, parens-JOIN-ON, parens-composed-with-comma, parens-aliased-tables-cross (exact random-corpus shape), parens-aggregate-over-group, parens-nested.

## Phase 6br — Subquery-in-FROM (derived tables)

SQLite permits `SELECT … FROM (<select-stmt>) AS alias` — a parenthesized SELECT in the FROM position that materializes to a virtual table. Closes pending #61. Required for hand-written test suites (index/, evidence/) and for several random-corpus residuals.

### Grammar

Extends Phase 6bq's from-source production with a derived-table branch:

```
from-source := table-reference
             | LPAREN join-tree RPAREN                               -- Phase 6bq
             | LPAREN select-stmt RPAREN [ KEYWORD_AS ] IDENTIFIER   -- Phase 6br (this)
```

Parser disambiguates at `LPAREN` by peeking the next token: `SELECT` / `WITH` / `VALUES` ⇒ derived-table branch; anything else ⇒ join-group branch. Derived-table form **requires** a trailing alias. Missing trailing alias raises `PARSE_UNEXPECTED_TOKEN`.

### Semantics

The inner select-stmt is executed as a self-contained query and its result-set is materialized into a temporary sorter. The outer query reads from that sorter as if it were a regular table-reference with the given alias.

Column-name binding:
- Inside the derived table: the inner SELECT's own scope (columns from its FROM, its WHERE, etc.).
- Outside: only alias-qualified access — `alias.colname`. Outer query cannot reach inner FROM.
- Names come from the inner SELECT's projection items in order: explicit `AS name` pins the name; plain column refs keep the column's name; other expressions get an implementation-defined column name (SQLite uses the SQL text; we accept either the SQL text or `column_<index>` — both are consistent with SQLite fixtures since those tests either use `*` or explicitly alias the expressions).

Correlated derived tables (inner SELECT references outer columns) — **deferred**. V1 treats the inner body as self-contained.

### Errors

- `PARSE_UNEXPECTED_TOKEN` — derived-table form without a trailing alias.

No new error kinds. No new opcodes — materialization reuses the existing CTE-sorter machinery (Phase 6aa lowering).

### Implementation

- **Parser**: in `parse_from_source` (Phase 6bq's entry point), when LPAREN is followed by SELECT/WITH/VALUES, recursively parse the select-stmt, consume RPAREN, require and parse the trailing alias. Emit an AST form that downstream compile paths recognize as a derived-table reference. One reasonable lowering: synthesize a unique private CTE name per derived table and register a binding in the same namespace as real CTEs.
- **Compiler**: lower a derived table like an anonymous non-recursive CTE — materialize the inner body into a sorter before the outer scan opens, then emit the outer scan reading from that sorter via the alias.
- **Runtime**: no change; sorter-read path is unchanged.

### Non-goals (v1)

- Correlated derived tables (`FROM (SELECT * FROM t WHERE t.k = outer.k) …`). Defer.
- Column-list-on-alias (`AS sub(c1, c2)`). Defer.
- `VALUES (…)` as a derived table. Defer (candidate for 6bs).
- Derived tables inside `WITH RECURSIVE`. Defer.

### Fixtures

`tests/cross-build/phase6br.json` — 10 cases: simple passthrough, WHERE inside, ORDER BY+LIMIT inside, aggregate inside, outer WHERE referencing alias.col, two derived tables joined, derived joined with real table, explicit inner alias, missing-alias rejection.

## Phase 6bu — `NULLIF` scalar builtin

Phase 6bu adds a single two-argument scalar function: `NULLIF(x, y)`. The random-corpus analysis from 2026-04-20 identified `NULLIF` as the single most common missing function across `random/expr/*.test`: 120 of 120 files use it, and its absence accounts for the largest `RUNTIME_COMPILE_UNKNOWN_FUNCTION` bucket in the full-corpus gate on both C and Rust targets (cross-corroboration signal — the gap is in the spec, not in either generator).

Phase 6bu extends `Scalar2Kind` with one new sub-kind, reusing the existing `Scalar2` opcode. No new top-level opcode, no new invariants, no new error kinds, no new tokens. `max_invariant = 45` unchanged.

### Grammar

Unchanged. `NULLIF` is an `IDENTIFIER` in call position, resolved at compile time by the same name-dispatch table as `IFNULL` / `COALESCE` (see Phase 6s § "compile-time dispatch"). The function-call grammar already admits variadic arguments since Phase 6s.

### Compile-time dispatch

Name resolution (case-insensitive) is extended with one new entry in the two-arg scalar bucket (Phase 6s item 3):

- `nullif` → `Scalar2 { kind: Nullif, arg1_reg, arg2_reg, dest }`. Exactly 2 args. Wrong count → `COMPILE_SCALAR_ARG_COUNT_MISMATCH { function: "NULLIF", expected: 2, got: <n> }`. STAR in argument position → `COMPILE_SCALAR_ARG_MISMATCH { function: "NULLIF", reason: "star-not-allowed" }` (same rule as `IFNULL`).

Compilation shape mirrors `IFNULL`:

1. Allocate register `arg1_reg`; compile `x` into `arg1_reg`.
2. Allocate register `arg2_reg`; compile `y` into `arg2_reg`.
3. Emit `Scalar2 { kind: Nullif, arg1_reg, arg2_reg, dest }`.

Register aliasing rules match `IFNULL`: any pair or triple of `{arg1_reg, arg2_reg, dest}` may coincide; the VDBE dispatch must read both source registers before writing `dest`.

### Evaluation semantics

`NULLIF(x, y)` returns:

- **`Null`** if `x` is `Null`. (NULL-in → NULL-out on the first argument.)
- **`Null`** if `x` and `y` compare as equal under the same-tier equality rule defined below.
- **`x`** (value-clone) otherwise — including the case where `x` is non-`Null` and `y` is `Null` (since any comparison involving `Null` is not-equal under this rule, except the explicit `x is Null` case above).

Equality rule (matches the `SortValueEq` semantics pinned in Phase 6as, re-stated here for authority):

- Both `Null` → treat as equal (consistent with the `x is Null` short-circuit above — the result is `Null` either way).
- One `Null`, other non-`Null` → not equal.
- Both numeric (`Integer` or `Real`) → compare by numeric value with cross-type promotion. `1 = 1.0` → equal; `1 = 2` → not equal. Integer-vs-Integer compares exactly as integers (no precision loss).
- Both `Text` → byte-wise equality (no collation, no case folding, no trimming).
- One numeric, one `Text` → **not equal**. No affinity coercion. This mirrors SQLite's `NULLIF` semantics: `NULLIF(5, '5')` returns `5`, not `Null`. The coercion-free comparison is what distinguishes this equality from the SQL `=` operator (which raises `EVAL_TYPE_ERROR` on heterogeneous numeric/text operands in our VDBE).

Rationale for the coercion-free rule: `NULLIF` must never raise. The `=` opcode (`OP_EQ`) raises `EVAL_TYPE_ERROR` on a numeric-vs-text pair. `NULLIF` predates the VDBE's 3VL-with-type-error semantics (it originates from SQL-92) and in SQLite's mainline implementation the comparison is affinity-aware in a way that happens to resolve numeric-vs-text as "not equal" on the literal-vs-literal case in our corpus. We adopt the simpler rule: no coercion, same-tier equality only. This is observationally equivalent to mainline SQLite on all literal pairs in the random corpus (verified on `sqlite3 :memory:` with `NULLIF(5, '5')`, `NULLIF(5, '5.0')`, `NULLIF('5', 5)` all returning their first argument). The rule is also a strict subset of SCALAR2_SORTVALUEEQ (Phase 6as), so generators MAY reuse that comparator.

**Never raises.** `Scalar2 { kind: Nullif }` is a pure choice function. No type errors, no overflow, no allocation failures (the result is either `Null` or a value-clone of an already-live register).

### AST shape

No new AST kinds. `FunctionCall { name: "NULLIF", args: [e1, e2] }` is the existing `FunctionCall` node with its two-argument arg-list shape (Phase 6s widening already permits this).

### Error conditions

- **`COMPILE_SCALAR_ARG_COUNT_MISMATCH { function: "NULLIF", expected: 2, got: <n> }`** — wrong arg count (reused from Phase 6s).
- **`COMPILE_SCALAR_ARG_MISMATCH { function: "NULLIF", reason: "star-not-allowed" }`** — STAR argument (reused).
- **`COMPILE_UNKNOWN_FUNCTION`** — unreachable after this phase for the `nullif` name; still the error for other unknown names.

No runtime errors are introduced. `Scalar2 { kind: Nullif }` cannot raise.

### Non-goals (Phase 6bu)

- **Affinity-aware comparison** (numeric-vs-text coercion on `NULLIF(5, '5')` yielding `Null`): rejected. The coercion-free rule matches mainline SQLite on every literal-vs-literal case present in the random corpus, is simpler to specify language-neutrally, and keeps `NULLIF` non-raising. If a later corpus exposes a column-vs-literal case that demands affinity coercion, a follow-up phase can revisit.
- **Generalising `NULLIF` to a non-strict form** (e.g. `NULLIF(x, y, z)`): no SQL surface admits this. Out of scope.
- **A dedicated `OP_NULLIF` top-level opcode**: rejected. Reusing `Scalar2` via a new `Scalar2Kind` extension keeps the VDBE ISA fixed-shape, matches the Phase 6s / 6x / 6ad / 6ao / 6as pattern (every 2-arg pure scalar rides `Scalar2`), and requires no invariant bump.

### Cross-corroboration origin

`NULLIF` missing from the builtin roster was identified by both C and Rust full-corpus runs on 2026-04-20, each surfacing the same bucket: `random/expr/slt_good_*.test` files consistently emit `NULLIF(...)` in their SELECT lists, producing `COMPILE_UNKNOWN_FUNCTION` on every such line. Per the project-memory rule (`feedback_cross_corroboration_signal`), when both targets hit the same gap, the fix is a spec addition, not a per-generator patch. This phase closes the spec gap; both generators implement the new `Scalar2Kind` sub-kind following the existing `IFNULL` pattern.

### Test authority (Phase 6bu)

`tests/cross-build/phase6bu-nullif.json` is the executable specification for Phase 6bu. All prior phase fixtures MUST stay green.

