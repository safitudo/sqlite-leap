# Part: tokenizer

Transforms a string of SQL input into a sequence of tokens per `spec/sql-grammar.spec.md` (section "Tokens").

## Contract

- **Input:** one string of SQL text. Phase 1 assumes the string is pure ASCII. On any byte with value `> 0x7F`, the tokenizer MUST terminate unsuccessfully with `LEX_UNEXPECTED_CHARACTER` at the 0-based index of that byte. This preserves cross-build equivalence on non-ASCII input.
- **Output on success:** an ordered sequence of tokens conforming to `schema/tokens.schema.json`. The sequence ends with exactly one `EOF` token whose `pos` equals the length of the input.
- **Output on failure:** one of the error conditions enumerated in the "Error conditions (tokenizer)" section of the grammar spec, carrying the fields that spec requires.

Each language target represents "success or failure" in its own idiomatic way (tagged union, `Result`, sum of return code + out-parameter, etc.). The part's schema (`schema.json` alongside this file) describes the abstract contract; the language target is free to translate it.

## Required behaviour

The tokenizer MUST:

- Produce tokens left-to-right in source order
- Consume and discard whitespace between tokens
- Attach a `pos` field (0-based index of the token's first character) to every token
- Emit exactly one `EOF` at the end
- Terminate unsuccessfully with `LEX_UNEXPECTED_CHARACTER`, `LEX_UNTERMINATED_STRING`, or `LEX_INTEGER_OVERFLOW` on the conditions defined in the grammar spec
- Be pure: it MUST NOT mutate the input, read global state, or perform I/O

The tokenizer MUST NOT:

- Look ahead beyond what the grammar rules require
- Interpret meaning beyond what the spec defines (e.g. no escape sequences other than `''` → `'`)
- Combine adjacent tokens into higher-level structures — that is the parser's job
- Import or reference any other part's generated code

## Part independence

The tokenizer does not know about the parser, the executor, storage, or any future component. It only depends on:

- `spec/sql-grammar.spec.md` (the rules — Phase 1 section + Phase 2a "Phase 2a tokens" section for the expanded token set)
- `schema/tokens.schema.json` (the output contract)

## Phase 2a note

Phase 2a expands the token set (keywords CREATE, TABLE, INSERT, INTO, VALUES, FROM, INTEGER, TEXT; plus IDENTIFIER, LPAREN, RPAREN, COMMA, STAR). See `spec/sql-grammar.spec.md` § "Phase 2a tokens" for rules. The contract in this file is unchanged; only the recognised token set grew. The keyword-vs-identifier precedence rule in the spec (longest ALPHANUM-run with `_`, match against keyword table case-insensitively; otherwise IDENTIFIER with case preserved in `name`) is authoritative for disambiguation.

## Phase 2c-1 note

Phase 2c-1 adds operator tokens: PLUS (`+`), MINUS (`-`), SLASH (`/`), EQ (`=`), NEQ (`!=`), LT (`<`), LE (`<=`), GT (`>`), GE (`>=`). See `spec/sql-grammar.spec.md` § "Phase 2c-1 tokens" for rules. Multi-character tokens (`!=`, `<=`, `>=`) require one-character lookahead and obey maximal-munch: `<=` is `LE`, not `LT` followed by `EQ`. A bare `!` (not followed by `=`) raises `LEX_UNEXPECTED_CHARACTER` at the `!`'s position. The contract of this part is unchanged; only the token set grew.

## Implementation freedom

The tokenizer MAY maintain opaque internal state (a cursor, a lookahead buffer, an explicit lexer struct, a closure over mutable variables, etc.) as an implementation detail of its entry point. This state is NOT part of the public contract. Each language target is free to express it as a free-function-plus-mutable-cursor, a struct-with-methods, a class, a coroutine, or any equivalent form. A reviewer MUST NOT treat "the tokenizer has (or lacks) a state object" as a correctness question — it is a stylistic choice delegated to the target.

## Output location

Generated code lives in `src-{lang}/tokenizer/` (path convention may be adjusted per language target, e.g. `src-rust/src/tokenizer/`, `src-c/tokenizer/`). It exposes exactly one public entry point that accepts the input string and returns the token sequence or the named error.
