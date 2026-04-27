---
name: scalar-builtins/fts5
kind: leaf
emits:
  rust:   { path: src-rust/fts5_query.rs }
  c:      { path: src-c/fts5/query.c }
  zig:    { path: src-zig/fts5_query.zig }
  go:     { path: src-go/fts5/query.go }
  python: { path: src-python/leap_sqlite/fts5_query.py }
---

# Part: scalar-builtins/fts5 — query surface

SQLite-compatible FTS5 full-text search query surface. This leaf owns
three things: (a) the `CREATE VIRTUAL TABLE … USING fts5(…)` parse
path, (b) the `MATCH` operator and its query-string grammar, and (c)
the `rank` synthetic column / `bm25(…)` ranking function. The
on-disk segment format and tokenizer implementations live in sibling
parts:

- `parts/storage/parts/fts5-index/` — segments, doclists, prefix
  indexes, content-table strategies (external, contentless,
  columnsize), shadow tables `t_data` / `t_content` / `t_idx` /
  `t_docsize` / `t_config`.
- `parts/storage/parts/fts5-tokenizer/` — built-in tokenizers
  (`unicode61`, `ascii`, `porter`).

This part takes parsed AST + a tokenizer + an open index and answers
SELECT-time queries. It does NOT itself read or write segment bytes;
it asks the index part for posting iterators by term.

## Surface declared by this part

The compiler treats `MATCH` as a binary expression and `rank` as a
synthetic column on every FTS5 virtual table. The runtime opcode
family is `OpcodeFts::*` (declared in
`parts/vdbe/parts/opcodes-fts/shapes.json` — a sibling spec edit
required by this part). No new `ScalarKind` variants — `bm25` is
dispatched through the FTS5 cursor, not the generic scalar path.

## Correctness pins

1. **Module name.** Only the literal lowercase `fts5` registers as a
   virtual-table module name. `FTS5`, `Fts5`, `FtsFive` are not
   recognised by case-insensitive comparison only at the USING-clause
   site (mainline behavior). Other identifiers in the schema remain
   case-insensitive per the SQL standard.

2. **CREATE VIRTUAL TABLE parse.** The grammar accepted is

   ```
   create-fts5 := "CREATE" "VIRTUAL" "TABLE" [if-not-exists] qname
                  "USING" "fts5" "(" arg-list ")"
   arg-list    := arg ("," arg)*
   arg         := column-name [column-options]
                | option-name "=" option-value
   column-options := ("UNINDEXED")*
   option-name    := identifier
   option-value   := identifier | quoted-string | "(" balanced-tokens ")"
   ```

   Bare identifiers in `arg-list` are columns of the FTS5 table
   in left-to-right order. `name=value` pairs are module options.
   Option names are case-insensitive; column names are
   case-preserving for output and case-insensitive for resolution.

3. **Recognised module options.** Closed set, all case-insensitive
   on the LHS:
   - `tokenize` — value is a quoted string; first whitespace-separated
     token names the tokenizer (`unicode61`, `ascii`, `porter`),
     remaining tokens are tokenizer arguments. Default
     `tokenize='unicode61'`.
   - `prefix` — value is a quoted string of comma- or
     whitespace-separated positive integers; each integer N causes a
     prefix index of length N to be maintained. Default empty.
   - `content` — value is a quoted string. Empty string `''` selects
     the *contentless* strategy. Otherwise the value names an
     external content table. Default: internal (an FTS5-owned
     `<name>_content` shadow table is built).
   - `content_rowid` — value is a column name in the external
     content table to use as the rowid; only meaningful with a
     non-empty `content=`.
   - `columnsize` — `0` or `1`. When `0`, suppress the
     `<name>_docsize` shadow table and treat all columns as
     equal-weight in BM25. Default `1`.
   - `detail` — `full`, `column`, or `none`. Controls how positions
     are stored in the doclist (full = per-token offsets, column =
     per-column membership only, none = doclist-only). Default
     `full`.

   Any other LHS or any malformed RHS raises
   `Fts5ConfigError` at CREATE time.

4. **Column declarations.** A column may be followed by the literal
   `UNINDEXED`. An UNINDEXED column is stored in the content table
   but never tokenized and never appears in any postings. There is
   no per-column type — every column is `TEXT` semantically.

5. **Shadow tables created.** On `CREATE VIRTUAL TABLE foo USING
   fts5(…)`, the FTS5 module asks the storage layer to create
   `foo_data`, `foo_idx`, `foo_config`, and (unless suppressed by
   options) `foo_content` and `foo_docsize`. Layout is owned by
   `parts/storage/parts/fts5-index`; this part only requests them.

6. **The `MATCH` operator.** `expr MATCH query-text` is valid only
   when `expr` resolves to a column of an FTS5 table or to the table
   name itself. `tbl MATCH 'q'` searches every indexed column.
   `tbl.col MATCH 'q'` constrains the search to that column. Any
   other LHS raises `Fts5MatchOnNonFts`.

7. **Query-string grammar.** The RHS of `MATCH` is a UTF-8 string
   parsed by this part:

   ```
   query     := disjunction
   disjunction := conjunction ("OR" conjunction)*
   conjunction := unary (("AND" | space-implicit) unary)*
   unary     := "NOT" unary | atom
   atom      := phrase
              | column-filter
              | near
              | "(" disjunction ")"
   column-filter := identifier ":" atom
                  | "{" identifier ("," identifier)* "}" ":" atom
   near      := "NEAR" "(" phrase phrase+ ("," integer)? ")"
   phrase    := bare-term | quoted-term
   bare-term := token-chars+ ["*"]
   quoted-term := "\"" (token | space)* "\""
   ```

   Whitespace between conjuncts is implicit AND. `OR`, `AND`, `NOT`,
   `NEAR` are reserved when bare; quote them to use as terms.
   Operator precedence (tightest first): `NOT`, `AND`, `OR`. A
   trailing `*` on a bare term means prefix-match.

8. **Column-filter evaluation.** `col:atom` restricts the inner
   atom to postings from column `col` only. `{a,b,c}:atom` is the
   union over those columns. UNINDEXED columns rejected with
   `Fts5UnindexedFilter`. Unknown columns raise `Fts5UnknownColumn`.

9. **Phrase semantics.** A quoted multi-token phrase matches when the
   tokens appear in adjacency in the order written, in the same
   column. Token positions are 0-based per (rowid, column). A bare
   single-token phrase is the special case of length-1.

10. **Prefix `*`.** A bare term ending in `*` matches every indexed
    term that begins with the prefix-stripped form. Prefix on a
    quoted phrase is only allowed on the *last* token
    (`"foo bar*"`). Prefix on an earlier token raises
    `Fts5PrefixInternal`. If a prefix index of the matching length
    exists for the table, it is used; otherwise the index part falls
    back to a doclist scan.

11. **NEAR(p1 p2 [p3 …] [, N]).** Matches when every phrase appears
    in the same column of the same row, and the maximum span
    between any two of the phrase occurrences is ≤ `N` token
    positions. Default `N` is 10. `N` is a positive integer literal;
    otherwise `Fts5NearArg`.

12. **Tokenization of the query.** Query-side phrases are tokenized
    with the same tokenizer the table was created with, applied to
    each phrase atom independently. Empty token streams (e.g. a
    phrase that is entirely separator under the active tokenizer)
    produce a phrase that matches nothing — but does not error.

13. **Rowid filter.** `MATCH` produces a stream of (rowid, score)
    pairs ascending by rowid; the planner may further intersect with
    `WHERE rowid = …` or `WHERE rowid BETWEEN …`. Equality and
    range on `rowid` are pushed down to the iterator as start/stop
    bounds.

14. **`rank` synthetic column.** Every FTS5 table exposes a column
    named `rank` whose value on a `MATCH` row equals the value of
    the active ranking function applied to that row. Outside a
    `MATCH` query, `rank` is SQL `NULL`. `ORDER BY rank` is the
    canonical idiom.

15. **`bm25(tbl[, w0, w1, …])`** — ranking function. With a single
    argument (the table) it returns BM25 with `k1=1.2`, `b=0.75`,
    and per-column weights all `1.0`. Additional positional args
    set the weight for column 0, 1, … in declaration order. Excess
    weights are ignored; missing weights default to `1.0`. The
    function is only valid in the SELECT list of a query that
    contains a `MATCH` on the same table; elsewhere it returns SQL
    `NULL`.

16. **BM25 formula.** For a row matching phrases `p_1..p_M`:

    ```
    score = sum over phrases p_i of:
              w(col_i) * idf(p_i) *
              (f(p_i, row) * (k1 + 1)) /
              (f(p_i, row) + k1 * (1 - b + b * dl(row) / avgdl))
    idf(p) = log( (N - n(p) + 0.5) / (n(p) + 0.5) )
    ```

    where `N` = total rows in the table, `n(p)` = rows containing
    phrase `p`, `f(p,row)` = phrase occurrence count in `row`,
    `dl(row)` = total token count of the row across indexed columns
    (read from `_docsize`), `avgdl` = mean `dl` across all rows. The
    sign of `idf` is preserved (it can go negative for very common
    terms; mainline preserves this; we follow). When `_docsize` is
    absent (`columnsize=0`), `dl(row)/avgdl` collapses to `1.0`.

17. **Score sign convention.** `bm25` returns the *negative* of the
    raw BM25 sum so that `ORDER BY rank` sorts most-relevant first
    by default. Matches mainline FTS5 exactly.

18. **`rank=` table option (post-create).** The active ranking
    function may be customised via `INSERT INTO tbl(tbl) VALUES
    ('rank', 'bm25(2.0, 1.0)')` — the `tbl` magic-column write
    protocol. Recognised commands: `'rank'` (set ranking
    expression), `'integrity-check'`, `'optimize'`, `'merge'`,
    `'pgsz'`, `'usermerge'`, `'crisismerge'`. Only `'rank'`,
    `'integrity-check'` and `'optimize'` are mandatory for v1; the
    rest may parse-and-ignore.

19. **Auxiliary functions on the cursor.** Aside from `bm25`, FTS5
    exposes `highlight(tbl, col, before, after)` and
    `snippet(tbl, col, before, after, omit, ntok)`. These are
    spec'd in this part as cursor-context functions that read the
    current row's tokens; v1 implementation may return SQL `NULL`
    when the cursor lacks position info (`detail=column` or
    `detail=none`). v1 mandatory: `bm25` only.

20. **Error conditions** (closed set, all surface as
    `RuntimeCondition::Fts5*`):
    `Fts5ConfigError`, `Fts5MatchOnNonFts`, `Fts5UnknownColumn`,
    `Fts5UnindexedFilter`, `Fts5PrefixInternal`, `Fts5NearArg`,
    `Fts5QuerySyntax`, `Fts5UnknownTokenizer`,
    `Fts5RankExprInvalid`.

21. **NULL inputs to MATCH.** `tbl MATCH NULL` evaluates to SQL
    `NULL` (UNKNOWN), producing zero rows; not an error.

22. **Prepared-statement caching.** The parsed query AST is owned
    by the prepared statement and shared across executions when the
    statement is rebound; a query-string change forces re-parse.

## Generation scope

Leaf. Each target's `parts/targets/<lang>/mapping.md` specifies how
the query AST is represented, how the iterator over (rowid, score)
is exposed to the VDBE, and which idiomatic ordered-collection it
uses for the multi-phrase merge. The on-disk reads run via the
sibling `fts5-index` API; this part imports `Fts5IndexHandle` and
`Fts5PostingIter` from there.
