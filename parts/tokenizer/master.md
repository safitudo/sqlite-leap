---
name: tokenizer
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /schema/tokens.schema.json
emits:
  c:
    path: src-c/tokenizer.c
    headers: [src-c/tokenizer.h]
  rust:
    path: src-rust/src/tokenizer.rs
---

# Part: tokenizer

Consumes SQL source text. Produces a token stream conforming to
`/schema/tokens.schema.json`.

## Public interface

- **Input:** a byte slice borrowed from the caller (`'src` lifetime).
- **Output on success:** an ordered sequence of tokens. Each token
  carries its kind, its byte span in the source (start offset +
  length), and — for identifier, literal, and numeric tokens — a
  borrowed reference to the matching slice of source.
- **Output on failure:** named error condition `TOKENIZER_INVALID`
  with fields `{offset, reason}`. Named conditions
  `TOKENIZER_UNTERMINATED_STRING`, `TOKENIZER_UNTERMINATED_COMMENT`
  are subtypes.

## Token kinds (closed set)

- **Keywords:** case-insensitive match against the SQL reserved
  word list. Canonical form is uppercase; the emitted token
  normalizes but the source slice is preserved for diagnostics.
- **Identifiers:** `[A-Za-z_][A-Za-z0-9_]*` unquoted; `"..."` or
  `` `...` `` or `[...]` quoted. Quote form is preserved in a
  secondary field so the parser can apply case-folding rules
  correctly.
- **Numeric literals:** integer (`\d+`), decimal (`\d+\.\d*` or
  `\.\d+`), exponent (`...[eE][+-]?\d+`), hex (`0x[0-9A-Fa-f]+`).
- **String literals:** `'...'` with `''` escape. No SQLite-specific
  string concatenation at lex time.
- **Blob literals:** `x'...'` / `X'...'` — hex byte sequence.
- **Punctuation:** `( ) , ; . * + - / % & | < > = != <> <= >= <<
  >> || ?`. Multi-character forms are lexed atomically.
- **Whitespace and comments:** skipped, not emitted. `--` line
  comments to end-of-line. `/* ... */` block comments, non-nesting.
- **Parameter markers:** `?` (positional), `?NNN` (indexed),
  `:name`, `@name`, `$name` — all emitted as a
  `ParameterMarker` token with the marker kind and name.

## Required behavior

The tokenizer MUST:

- Emit tokens in strict source order.
- Never allocate per-token heap memory for the source slice — token
  spans reference the input buffer.
- Preserve case of identifier source text (the parser handles
  case-folding).
- Reject unterminated strings/comments with a precise offset.
- Treat keywords as context-insensitive (no parser-driven
  keywording); conflicts with identifiers are resolved by the
  parser.

The tokenizer MUST NOT:

- Interpret literal values (no numeric conversion, no escape
  processing beyond `''` in strings — the parser owns that).
- Depend on any other part.
- Allocate a dynamic token buffer if the target language's idiomatic
  iterator model is available (Rust: iterator; C: callback or
  reusable next-token call).

## Lexical ambiguity rules

- Longest match wins: `<=` beats `<`; `!=` beats `!` + `=`.
- Keyword vs identifier: if a source slice matches a keyword AND
  it is not preceded by a disambiguating context (`.` for column
  qualification), emit the keyword token. Context is not a lexer
  concern; the parser reinterprets as identifier where needed (this
  is called the "keywords-as-identifiers" rule in the parser).

## Regeneration envelope

- Target leaf size: ~500–800 lines per target.
- Spec size budget: this file < 500 lines total.
- Regeneration atomicity: a fresh sub-agent with this file + the
  schema + the inherits chain must produce a passing tokenizer.
