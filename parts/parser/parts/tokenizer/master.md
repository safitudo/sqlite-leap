---
name: tokenizer
kind: leaf
emits:
  rust: { path: src-rust/parser/tokenizer.rs }
---

# SQL tokenizer (full scope)

Lexes a UTF-8 byte buffer of SQL source into a flat token stream. Full
SQLite-compatible scope: 147 keywords, all operators (including two-char
`<= >= <> != == ||  << >>`), integer + real + string + blob + identifier
literals, parameter placeholders, and position tracking. Emits a list of
tokens terminated by exactly one `Eof` on success, or returns a `LexError`
on the first lexical failure.

## Declared shapes (in `shapes.json`)

- `TokenKind` — 178-case variant: 147 keyword kinds (`KwAbort` … `KwWithout`),
  6 literal kinds with a `text: str` field (`Integer`, `Real`, `Str`, `Blob`,
  `Ident`, `Param`), and 25 punctuation/operator unit kinds (`LParen` …
  `ShiftR`, plus `Eof`).
- `Token` — `{ kind, byte_start, byte_end, line, column }`. The byte span +
  source buffer reconstructs the token text without re-walking.
- `LexError` — `{ byte_offset, line, column, message }`. `message` is
  **owned** (`string`) so the error outlives the source buffer.
- `tokenize(source: str) -> result<list<Token>, LexError>`.

## Lexing rules

Single-pass left-to-right over `source`, with a small lookahead (up to 2
bytes) to disambiguate two-char operators and hex / blob prefixes.

1. **Whitespace** (`' '`, `'\t'`, `'\r'`, `'\n'`): skip. On `'\n'`, increment
   line, reset column to 1. All four whitespace bytes advance the cursor by
   one byte and column by one.
2. **Line comment** (`-- ... \n`): skip to end of line (or EOF). The trailing
   `\n` counts as a line break.
3. **Block comment** (`/* ... */`): skip until `*/`. Block comments do NOT
   nest. Unterminated block comment ⇒ `LexError` pointing at the opening
   `/*`.
4. **Decimal digit** (`0..=9`): integer or real literal.
   - If the first two bytes are `0x` or `0X` followed by a hex digit, consume
     `0x` + `[0-9A-Fa-f]+` → `Integer` (text includes the `0x` prefix).
   - Otherwise consume `[0-9]+`. If followed by `.` and another digit,
     consume `.[0-9]+` → `Real`. If followed by `e`/`E` with optional `+`/`-`
     and digits, consume the exponent → `Real`. Otherwise → `Integer`.
5. **ASCII alpha or `_`**: identifier or keyword. Consume `[A-Za-z0-9_]*`.
   Case-insensitive lookup against the 147-entry keyword table (see below);
   on hit emit the keyword kind, else `Ident` with the raw text.
   - Special case: if the identifier is exactly `X` or `x` (ASCII, length 1)
     and the next byte is `'`, treat as the start of a BLOB literal — consume
     `'[0-9A-Fa-f]*'` → `Blob`. The text span covers the leading `X`/`x` and
     both quotes.
6. **Single quote** (`'`): string literal. Consume until a matching `'`.
   If the next byte after `'` is another `'`, that's an escaped single quote
   — consume both and continue. Unterminated string ⇒ `LexError` pointing at
   the opening quote.
7. **Double quote** (`"`): quoted identifier. Consume until matching `"`.
   Escape is doubled `""`. Emit `Ident` with the text including surrounding
   quotes. Unterminated ⇒ `LexError`.
8. **Backtick** (`` ` ``) or open bracket (`[`): quoted identifier
   variants. Backtick uses matching `` ` `` (doubled `` `` `` is the escape);
   bracket uses matching `]` (no escape — brackets do not nest). Emit
   `Ident` with surrounding quotes in the text span.
9. **Parameter sigil** (`?`, `:`, `@`, `$`): parameter placeholder.
   - `?` alone → `Param` with text `"?"`.
   - `?` followed by digits → `Param` with text `"?NNN"`.
   - `:`, `@`, `$` followed by `[A-Za-z_][A-Za-z0-9_]*` → `Param` with text
     including the sigil.
10. **Two-char operators** (lookahead-driven; prefer longer match):
    - `<=` → `LtEq`, `<>` → `NotEq`, `<<` → `ShiftL`, else `<` → `Lt`.
    - `>=` → `GtEq`, `>>` → `ShiftR`, else `>` → `Gt`.
    - `==` → `EqEq`, else `=` → `Eq`.
    - `!=` → `NotEqBang`; bare `!` is NOT a token — `!` not followed by `=`
      is a `LexError`.
    - `||` → `Concat`, else `|` → `BitOr`.
11. **Single-char punctuation**: `(` `LParen`, `)` `RParen`, `,` `Comma`,
    `;` `Semi`, `.` `Dot`, `*` `Star`, `+` `Plus`, `-` `Minus`, `/` `Slash`
    (after ruling out `/*` block comment), `%` `Percent`, `&` `BitAnd`,
    `~` `BitNot`.
12. **Anything else**: `LexError` with message `"unexpected byte"`.

At end-of-source: emit one `Eof` with `byte_start == byte_end ==
source.len()` and the final cursor's line/column.

## Keyword table (case-insensitive ASCII)

Byte-string comparison uppercases the ASCII bytes of the identifier lexeme,
then looks up in a flat table. 147 entries (full SQLite keyword set):

| Source (any case) | TokenKind |
|---|---|
| `ABORT` | `KwAbort` |
| `ACTION` | `KwAction` |
| `ADD` | `KwAdd` |
| `AFTER` | `KwAfter` |
| `ALL` | `KwAll` |
| `ALTER` | `KwAlter` |
| `ALWAYS` | `KwAlways` |
| `ANALYZE` | `KwAnalyze` |
| `AND` | `KwAnd` |
| `AS` | `KwAs` |
| `ASC` | `KwAsc` |
| `ATTACH` | `KwAttach` |
| `AUTOINCREMENT` | `KwAutoincrement` |
| `BEFORE` | `KwBefore` |
| `BEGIN` | `KwBegin` |
| `BETWEEN` | `KwBetween` |
| `BY` | `KwBy` |
| `CASCADE` | `KwCascade` |
| `CASE` | `KwCase` |
| `CAST` | `KwCast` |
| `CHECK` | `KwCheck` |
| `COLLATE` | `KwCollate` |
| `COLUMN` | `KwColumn` |
| `COMMIT` | `KwCommit` |
| `CONFLICT` | `KwConflict` |
| `CONSTRAINT` | `KwConstraint` |
| `CREATE` | `KwCreate` |
| `CROSS` | `KwCross` |
| `CURRENT` | `KwCurrent` |
| `CURRENT_DATE` | `KwCurrentDate` |
| `CURRENT_TIME` | `KwCurrentTime` |
| `CURRENT_TIMESTAMP` | `KwCurrentTimestamp` |
| `DATABASE` | `KwDatabase` |
| `DEFAULT` | `KwDefault` |
| `DEFERRABLE` | `KwDeferrable` |
| `DEFERRED` | `KwDeferred` |
| `DELETE` | `KwDelete` |
| `DESC` | `KwDesc` |
| `DETACH` | `KwDetach` |
| `DISTINCT` | `KwDistinct` |
| `DO` | `KwDo` |
| `DROP` | `KwDrop` |
| `EACH` | `KwEach` |
| `ELSE` | `KwElse` |
| `END` | `KwEnd` |
| `ESCAPE` | `KwEscape` |
| `EXCEPT` | `KwExcept` |
| `EXCLUDE` | `KwExclude` |
| `EXCLUSIVE` | `KwExclusive` |
| `EXISTS` | `KwExists` |
| `EXPLAIN` | `KwExplain` |
| `FAIL` | `KwFail` |
| `FILTER` | `KwFilter` |
| `FIRST` | `KwFirst` |
| `FOLLOWING` | `KwFollowing` |
| `FOR` | `KwFor` |
| `FOREIGN` | `KwForeign` |
| `FROM` | `KwFrom` |
| `FULL` | `KwFull` |
| `GENERATED` | `KwGenerated` |
| `GLOB` | `KwGlob` |
| `GROUP` | `KwGroup` |
| `GROUPS` | `KwGroups` |
| `HAVING` | `KwHaving` |
| `IF` | `KwIf` |
| `IGNORE` | `KwIgnore` |
| `IMMEDIATE` | `KwImmediate` |
| `IN` | `KwIn` |
| `INDEX` | `KwIndex` |
| `INDEXED` | `KwIndexed` |
| `INITIALLY` | `KwInitially` |
| `INNER` | `KwInner` |
| `INSERT` | `KwInsert` |
| `INSTEAD` | `KwInstead` |
| `INTERSECT` | `KwIntersect` |
| `INTO` | `KwInto` |
| `IS` | `KwIs` |
| `ISNULL` | `KwIsnull` |
| `JOIN` | `KwJoin` |
| `KEY` | `KwKey` |
| `LAST` | `KwLast` |
| `LEFT` | `KwLeft` |
| `LIKE` | `KwLike` |
| `LIMIT` | `KwLimit` |
| `MATCH` | `KwMatch` |
| `MATERIALIZED` | `KwMaterialized` |
| `NATURAL` | `KwNatural` |
| `NO` | `KwNo` |
| `NOT` | `KwNot` |
| `NOTHING` | `KwNothing` |
| `NOTNULL` | `KwNotnull` |
| `NULL` | `KwNull` |
| `NULLS` | `KwNulls` |
| `OF` | `KwOf` |
| `OFFSET` | `KwOffset` |
| `ON` | `KwOn` |
| `OR` | `KwOr` |
| `ORDER` | `KwOrder` |
| `OTHERS` | `KwOthers` |
| `OUTER` | `KwOuter` |
| `OVER` | `KwOver` |
| `PARTITION` | `KwPartition` |
| `PLAN` | `KwPlan` |
| `PRAGMA` | `KwPragma` |
| `PRECEDING` | `KwPreceding` |
| `PRIMARY` | `KwPrimary` |
| `QUERY` | `KwQuery` |
| `RAISE` | `KwRaise` |
| `RANGE` | `KwRange` |
| `RECURSIVE` | `KwRecursive` |
| `REFERENCES` | `KwReferences` |
| `REGEXP` | `KwRegexp` |
| `REINDEX` | `KwReindex` |
| `RELEASE` | `KwRelease` |
| `RENAME` | `KwRename` |
| `REPLACE` | `KwReplace` |
| `RESTRICT` | `KwRestrict` |
| `RETURNING` | `KwReturning` |
| `RIGHT` | `KwRight` |
| `ROLLBACK` | `KwRollback` |
| `ROW` | `KwRow` |
| `ROWS` | `KwRows` |
| `SAVEPOINT` | `KwSavepoint` |
| `SELECT` | `KwSelect` |
| `SET` | `KwSet` |
| `TABLE` | `KwTable` |
| `TEMP` | `KwTemp` |
| `TEMPORARY` | `KwTemporary` |
| `THEN` | `KwThen` |
| `TIES` | `KwTies` |
| `TO` | `KwTo` |
| `TRANSACTION` | `KwTransaction` |
| `TRIGGER` | `KwTrigger` |
| `UNBOUNDED` | `KwUnbounded` |
| `UNION` | `KwUnion` |
| `UNIQUE` | `KwUnique` |
| `UPDATE` | `KwUpdate` |
| `USING` | `KwUsing` |
| `VACUUM` | `KwVacuum` |
| `VALUES` | `KwValues` |
| `VIEW` | `KwView` |
| `VIRTUAL` | `KwVirtual` |
| `WHEN` | `KwWhen` |
| `WHERE` | `KwWhere` |
| `WINDOW` | `KwWindow` |
| `WITH` | `KwWith` |
| `WITHOUT` | `KwWithout` |

Anything that looks like an identifier but isn't in this table is `Ident`.

## Position tracking

Maintain an internal cursor `{ byte: u32, line: u32, column: u32 }`. `byte`
is the byte offset from source start. `line` starts at 1 and increments on
`'\n'` consumption. `column` starts at 1, resets to 1 after `'\n'`, and
increments by 1 per consumed byte (NOT per grapheme).

Each emitted `Token` carries the cursor snapshot **at its first byte**.

## Output contract

`tokenize(source)` returns a list of `Token`s terminated by exactly one
`Eof` on success, or a `LexError` on the first failure. Byte spans MUST be
non-overlapping and strictly monotonic. Sum of all token spans + whitespace
+ comments == `source.len()`.

## Correctness pins

1. **147-keyword recognition, case-insensitive** — `SELECT`, `Select`,
   `select`, `SeLeCt` all emit `KwSelect`. Same rule for every entry in the
   keyword table. Multi-word keywords `CURRENT_DATE` / `CURRENT_TIME` /
   `CURRENT_TIMESTAMP` are recognized as single tokens (the underscore is
   part of the identifier lexeme).
2. **Keyword-vs-identifier disambiguation** — after consuming an identifier
   lexeme, the keyword-table lookup happens exactly once; non-matches become
   `Ident { text: <span> }`.
3. **Two-char operator greed** — `<=`, `>=`, `<>`, `!=`, `==`, `||`, `<<`,
   `>>` lex as a single token when their two-byte form is present. The
   single-char alternative only wins on a one-byte-lookahead miss.
4. **Hex integer** — `0x1F` and `0X1f` both lex as `Integer` with the full
   text including the `0x` prefix. `0x` with no following hex digits is a
   `LexError`.
5. **Blob literal gate** — `X'ABCD'` and `x'abcd'` lex as `Blob`. Text span
   covers the `X`/`x` and both quotes. The `X` / `x` must be exactly one
   byte (not part of a longer ident). `X'GG'` is a `LexError` (non-hex in
   blob body).
6. **String escapes** — `'can''t'` lexes as ONE `Str` with text span
   covering the full `'can''t'` (7 bytes). Unescaping is the parser's job.
7. **Quoted identifiers** — `"foo"`, `[foo]`, `` `foo` `` lex as `Ident`.
   Text span includes the surrounding delimiters.
8. **Parameter forms** — `?`, `?5`, `:name`, `@name`, `$name` all lex as
   `Param` with text including the leading sigil.
9. **Position accuracy** — `Token.line` and `Token.column` name the **first
   byte** of the token. Line increments only on `\n` consumption.
10. **Byte-span disjointness + monotonicity** — every token's `byte_start`
    >= previous `byte_end`. The gap contains only whitespace + comments.
    Eof has `byte_start == byte_end == source.len()`.
11. **Unterminated string / block comment / quoted identifier ⇒ LexError**
    — points at the opening delimiter, not the end of input.
12. **EOF sentinel** — emitted exactly once at end of successful lex.
13. **Owned error message** — `LexError.message` is an owned `string` per
    `shapes.json`, not a borrow.
14. **Generation scope** — per `spec/part-conventions.spec.md`: no regex
    crates, no state-machine DSLs, no hand-rolled keyword trees beyond the
    147-entry flat table. No inline tests. Plain byte-indexed single-pass
    code.

15. **Keyword lookup is O(bucket) not O(147)** — the keyword-table lookup
    of pin 1+2 MUST run in expected O(k) where k is the average size of a
    same-first-letter bucket (≈ 6 entries), NOT O(147). Targets MUST
    precompute a 26-entry first-letter index `[A..Z] → (lo, hi)` from the
    sorted KEYWORDS table at first call (lazy `OnceLock` / static-init /
    equivalent), then probe only the bucket whose first byte matches the
    upper-cased lexeme's first byte. The flat KEYWORDS table from pin 14
    remains the source of truth; the index is a precomputed bucket map
    over it, not a separate data structure. Empirically: at the L4 INSERT
    bench (100k inserts, single shape), linear lookup costs ~430ns/insert;
    bucketed lookup costs ~180ns/insert (-58%). Targets MAY use a perfect
    hash or trie if it achieves the same bound; linear scan is forbidden.

## Regeneration envelope

- Line budget: **~450–650 lines** of Rust. The 178-case enum alone is
  ~180 lines at one line per variant; the keyword-table array is ~150 lines
  at one line per entry. The lexer body itself is ~200-300 lines.
- No dependencies beyond std.
- The emitted file must declare the module surface consumed by
  `src-rust/examples/tokenize_smoke.rs`: public items are `TokenKind`,
  `Token`, `LexError`, and `tokenize`.

## Smoke probe

`src-rust/examples/tokenize_smoke.rs` (hand-written, not regenerated this
wave) tokenizes four SQL snippets:

```sql
-- snippet 1: basic select + comparison
SELECT * FROM t WHERE id = 1;

-- snippet 2: create-table with PK + quoted ident
CREATE TABLE "my t" (id INTEGER PRIMARY KEY, name TEXT);

-- snippet 3: insert with string escape + blob + hex
INSERT INTO t VALUES (1, 'alice'), (0x10, X'abcd'), (3, 'can''t');

-- snippet 4: expression with two-char operators
SELECT a <= b AND c <> d OR e != f || g FROM t WHERE x >= 10 AND y << 2 > 0;
```

Expected non-`Eof` token counts: 9 / 13 / 22 / 27 (plus one `Eof` each).
The runner verifies kind sequences plus span monotonicity and emits
`OK: all N snippets tokenize correctly` on success.
