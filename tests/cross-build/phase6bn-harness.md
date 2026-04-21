# Phase 6bn harness — parser gaps from random sqllogictest analysis

Three parser gaps identified via 89-file random-corpus analysis (608k PARSE_UNEXPECTED_TOKEN failures out of 639k total). All three are parser/tokenizer-level — no VDBE changes. Expected to close a large fraction of random/ failures.

No new reserved keywords. No new opcodes. No new errors. `max_invariant` unchanged. Gate: 12 fixtures green both targets.

## Gap 1 — Unary `+` prefix operator

SQLite accepts `SELECT + col FROM t` as a no-op unary prefix. Our parser only accepts unary `-`. Add `+` at the same unary precedence level.

Grammar:
```
unary := MINUS unary | PLUS unary | primary
```

Semantics: unary `+` is a no-op. `+ NULL` = NULL. `+ 'abc'` = 'abc'. Applies uniformly across INTEGER, REAL, TEXT, BLOB, NULL.

## Gap 2 — Implicit column alias (no AS keyword)

SQLite allows `SELECT expr alias` as shorthand for `SELECT expr AS alias`. Our parser rejects the bare IDENTIFIER after the projection expr.

Grammar:
```
projection-item := expression [ [ KEYWORD_AS ] IDENTIFIER ]
```

When the AS is omitted, the IDENTIFIER directly following the expression becomes the column's alias. The alias must not be a reserved keyword (parser resolves by lookahead: if the next token is a keyword that would end the projection — FROM / COMMA / etc. — stop; only accept a bare IDENTIFIER token).

Semantics: identical to `expr AS alias`. Alias is visible in ORDER BY / GROUP BY / HAVING per existing Phase 6aj rules.

## Gap 3 — CAST type liberality

`CAST(x AS T)` currently rejects many type names (DECIMAL, NUMERIC, VARCHAR, CHAR, FLOAT, DOUBLE, BOOLEAN, etc.). Per SQLite, ANY identifier is accepted in the type slot; the resulting cast-type is determined by applying **affinity rules**:

| Type name contains (case-insensitive) | Resulting affinity |
|---|---|
| `INT` | INTEGER |
| `CHAR`, `CLOB`, `TEXT` | TEXT |
| `BLOB`, or empty/unrecognized + no other rule | BLOB |
| `REAL`, `FLOA`, `DOUB` | REAL |
| anything else (DECIMAL, NUMERIC, BOOLEAN, …) | NUMERIC (no conversion — keep value type as-is; integer stays integer, real stays real) |

Grammar:
```
cast-type := IDENTIFIER [ LPAREN INTEGER_LITERAL ( COMMA INTEGER_LITERAL )? RPAREN ]
```

Optional parenthesized size parameters are **parsed and discarded** (per existing Phase 6af pattern for `VARCHAR(30)`).

Semantics:
- INTEGER affinity: coerce value to i64 when possible (text that parses as int → int; real → int truncate; int → int). Unconvertible text → NULL (SQLite-compatible).
- TEXT affinity: coerce via existing 6r Real→Text or integer→text path.
- REAL affinity: coerce via integer→real promotion or text parse.
- BLOB affinity: keep value as-is (we don't have blob storage for text, so TEXT passes through).
- NUMERIC affinity: if value is text that parses as int → int; text parses as real → real; else keep as text.

### Implementation

- Parser `unary` rule: add `+` alternative alongside `-`. Emit `UnaryOp { op: "+", expr }` or fold to a no-op passthrough.
- Parser projection: after parsing an expression, peek next token. If it's `AS` keyword, consume and parse IDENTIFIER (existing path). If it's a plain IDENTIFIER (NOT a keyword that would end the projection list: FROM, WHERE, GROUP, ORDER, LIMIT, COMMA, SEMICOLON, EOF, UNION, INTERSECT, EXCEPT), consume it as an alias. Else no alias.
- Parser CAST: after `AS` inside CAST, accept any IDENTIFIER (including existing KEYWORD_INTEGER/REAL/TEXT etc. as special-cased keyword-identifiers). If followed by LPAREN, consume the size params and discard. Map the type name to affinity via the table above.
- Compiler CAST: existing affinity-based cast logic likely already exists for INTEGER/TEXT/REAL; extend to route DECIMAL/NUMERIC/VARCHAR/etc. through the same paths.

No new opcodes. No new error kinds.

### Non-goals

- Full SQLite type-affinity resolution for CREATE TABLE column declarations (that's a separate phase; here we're only doing CAST).
- `CAST(x AS <complex-type-expr>)` — v1 keeps it to identifier-with-optional-size-params.
- Implicit alias that shadows an existing column name — behaves per SQLite, no special conflict detection.
