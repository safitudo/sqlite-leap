# 5-target corpus run 2026-04-25 (post runner-format upgrade)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | PASS rate |
| --- | --- | --- | --- | --- | --- | --- |
| rust | 1485142 | 64718 | 8193 | 88464 | 1646517 | 90.20% |
| c | 937231 | 555417 | 32040 | 90095 | 1614783 | 58.04% |
| go | 926385 | 425494 | 22049 | 40355 | 1414283 | 65.50% |
| zig | 196763 | 107510 | 33174 | 17634 | 355081 | 55.41% |
| python | 808393 | 753592 | 228084 | 0 | 1790069 | 45.16% |

## Top 10 DEFER reasons per target

### rust
- 3130	compile: deferred: compound SELECT with CTE or derived FROM
- 3036	compile: projection references column not in GROUP BY
- 309	compile: HAVING references column not in GROUP BY
- 256	compile: deferred: DISTINCT across JOIN sources
- 197	parse: <pos> deferred: parenthesized table-ref / subquery in FROM
- 89	compile: unknown table: t2 (schema is for t1)
- 85	compile: unknown table: t6 (schema is for t1)
- 80	compile: unknown table: t7 (schema is for t1)
- 79	compile: unknown table: t4 (schema is for t1)
- 74	compile: deferred: IN subquery

### c
- 7752	compile: deferred: unsupported expression kind in aggregate projection/HAVING
- 4361	compile: deferred: <n>-or-more-way JOIN
- 2854	compile: projection references column not in GROUP BY: col0
- 2803	compile: projection references column not in GROUP BY: col2
- 2743	compile: projection references column not in GROUP BY: col1
- 2606	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 2139	compile: deferred: scalar subquery
- 853	compile: deferred: function call MIN_distinct
- 803	compile: deferred: function call SUM_distinct
- 798	compile: deferred: function call MAX_distinct

### go
- 2860	compile: projection references column not in GROUP BY
- 2260	compile: deferred: <n>-or-more-way JOIN
- 1879	compile: deferred α23: correlated subquery with aggregate / GROUP BY / compound
- 583	parse: parse error at token <n> (line <n> col <n>): unexpected token after SELECT statement
- 327	compile: deferred: function call MIN_distinct
- 320	compile: ambiguous column: pk
- 282	compile: deferred: function call SUM_distinct
- 271	compile: deferred: function call MAX_distinct
- 262	compile: deferred: function call AVG_distinct
- 159	compile: deferred: unknown expression node

### zig
- 9254	compile: deferred: IN subquery
- 2829	compile: projection references column not in GROUP BY
- 1796	compile: deferred: derived-table subquery in FROM
- 1771	compile: deferred: scalar subquery
- 1719	compile: deferred: JOIN with aggregation
- 796	compile: deferred: mixed INTERSECT/EXCEPT/UNION in one compound SELECT
- 641	compile: unknown table in JOIN: tab1
- 631	compile: unknown table in JOIN: tab2
- 604	compile: unknown table in JOIN: tab0
- 599	compile: deferred: EXISTS subquery

### python
- 55545	statement: unsupported leading kw '<s>'
- 52785	compile: internal: unhandled Expr variant ExprInSubquery
- 26192	parse: unexpected token after SELECT statement
- 19318	parse: expected prefix expression
- 11266	compile: internal: unhandled Expr variant ExprCast
- 9126	compile: projection references column not in GROUP BY
- 4492	parse: deferred: DISTINCT in SUM() unsupported
- 4457	parse: deferred: DISTINCT in MIN() unsupported
- 4429	parse: deferred: DISTINCT in MAX() unsupported
- 3928	compile: unknown table in JOIN: tab0


## Top 10 FAIL reasons per target

### rust
- 28563	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=[]
- 5959	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 3503	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=[]
- 3461	got(<n>)=[] expected(<n>)=["<s>", "<s>", "<s>"]
- 2571	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 1596	got(<n>)=[] expected(<n>)=["<s>"]
- 1586	got(<n>)=["<s>"] expected(<n>)=[]
- 1130	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=b833e3a3ba082b2c0028b4cd08f...
- 670	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>"]
- 630	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=c6c0a4111b36d04dbc811a11e4d...

### c
- 335468	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 64331	got(<n>) expected(<n>): cell <n> got=-<n> expected=-<n>
- 39250	row count mismatch: <n> cells vs expected <n>
- 12290	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 7850	got(<n>) expected(<n>): cell <n> got=<n> expected=NULL
- 2250	hash mismatch: count got=<n> expected=<n>, md5 got=2f8e5bef97f41cd641eafba46c99a49d expected=ee724f9f159f8cdef185b42c43b...
- 2150	hash mismatch: count got=<n> expected=<n>, md5 got=f40a1ef6542491a0f490c50802955a8e expected=fd5ef87ee372019414f0b3de2d9...
- 2075	hash mismatch: count got=<n> expected=<n>, md5 got=69ea35c77af3760266d28e7abca05b5f expected=41188ae9f1de9f62c029b0ba1e6...
- 2000	hash mismatch: count got=<n> expected=<n>, md5 got=287c225018dcf5275d60795ef673033b expected=665eeefca657f1f6c2d4f2ba683...
- 1975	hash mismatch: count got=<n> expected=<n>, md5 got=376a57a72b63bbd0b53390c7ee72216a expected=ac073ee6ea28ef0ed712cb7c239...

### go
- 47654	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 43432	got(<n>)=["<s>" "<s>"] expected(<n>)=["<s>" "<s>"]
- 38121	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 37788	got(<n>)=["<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>"]
- 37579	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>...
- 33456	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 25292	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 19411	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"]
- 17421	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 12290	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...

### zig
- 68076	got(<n>) expected(<n>) first got=<n> expected=<n>
- 13619	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 4241	got(<n>) expected(<n>) first got=<n> expected=<none>
- 1992	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 1606	got(<n>) expected(<n>) first got=<n> expected=NULL
- 1134	got(<n>) expected(<n>) first got=-<n> expected=<none>
- 565	got(<n>) expected(<n>) first got=<none> expected=<n>
- 383	hash mismatch: count got=<n> expected=<n>, md5 got=efbd3c7dcd524b8e5a7ac0ff665c4d2b expected=4489461d3189f4bad5a97addbf2...
- 375	hash mismatch: count got=<n> expected=<n>, md5 got=f40a1ef6542491a0f490c50802955a8e expected=fd5ef87ee372019414f0b3de2d9...
- 350	hash mismatch: count got=<n> expected=<n>, md5 got=9003cd84b3ceed4984f6b3ec56c14ab9 expected=9d88223741eaf4864dd05243683...

### python
- 365881	got=[] expected=['<s>']
- 78136	got=['<s>', '<s>', '<s>'] expected=['<s>', '<s>', '<s>']
- 42139	got=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s...
- 32776	got=[] expected=['<s>', '<s>']
- 30795	got=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>'] expected=['<s>']
- 29342	got=[] expected=['<s>', '<s>', '<s>', '<s>']
- 29101	got=[] expected=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 28656	got=[] expected=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 17232	got=[] expected=['<s>', '<s>', '<s>']
- 16242	got=['<s>'] expected=['<s>']
