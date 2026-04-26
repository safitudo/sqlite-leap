# 5-target corpus run 2026-04-25 (post runner-format upgrade)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | PASS rate |
| --- | --- | --- | --- | --- | --- | --- |
| rust | 1378654 | 170034 | 9365 | 88464 | 1646517 | 83.73% |
| c | 963290 | 560788 | 32513 | 90421 | 1647012 | 58.49% |
| go | 926385 | 426952 | 23937 | 42255 | 1419529 | 65.26% |
| zig | 197369 | 106809 | 32928 | 17547 | 354653 | 55.65% |
| python | 1464349 | 203852 | 119687 | 8 | 1787896 | 81.90% |

## Top 10 DEFER reasons per target

### rust
- 3130	compile: deferred: compound SELECT with CTE or derived FROM
- 3036	compile: projection references column not in GROUP BY
- 1172	compile: aggregate without FROM is unsupported
- 309	compile: HAVING references column not in GROUP BY
- 256	compile: deferred: DISTINCT across JOIN sources
- 197	parse: <pos> deferred: parenthesized table-ref / subquery in FROM
- 89	compile: unknown table: t2 (schema is for t1)
- 85	compile: unknown table: t6 (schema is for t1)
- 80	compile: unknown table: t7 (schema is for t1)
- 79	compile: unknown table: t4 (schema is for t1)

### c
- 7584	compile: deferred: unsupported expression kind in aggregate projection/HAVING
- 4361	compile: deferred: <n>-or-more-way JOIN
- 2854	compile: projection references column not in GROUP BY: col0
- 2803	compile: projection references column not in GROUP BY: col2
- 2743	compile: projection references column not in GROUP BY: col1
- 2606	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 2139	compile: deferred: scalar subquery
- 860	compile: deferred: function call MIN_distinct
- 811	compile: deferred: function call SUM_distinct
- 809	compile: deferred: function call MAX_distinct

### go
- 2860	compile: projection references column not in GROUP BY
- 2260	compile: deferred: <n>-or-more-way JOIN
- 1879	compile: deferred α23: correlated subquery with aggregate / GROUP BY / compound
- 1553	compile: aggregate without FROM is unsupported
- 583	parse: parse error at token <n> (line <n> col <n>): unexpected token after SELECT statement
- 410	compile: deferred: unknown expression node
- 347	compile: deferred: function call MIN_distinct
- 320	compile: ambiguous column: pk
- 319	compile: deferred: function call SUM_distinct
- 299	compile: deferred: function call MAX_distinct

### zig
- 9295	compile: deferred: IN subquery
- 2724	compile: projection references column not in GROUP BY
- 1786	compile: deferred: derived-table subquery in FROM
- 1771	compile: deferred: scalar subquery
- 1654	compile: deferred: JOIN with aggregation
- 796	compile: deferred: mixed INTERSECT/EXCEPT/UNION in one compound SELECT
- 617	compile: unknown table in JOIN: tab1
- 612	compile: unknown table in JOIN: tab2
- 599	compile: deferred: EXISTS subquery
- 590	compile: unknown table in JOIN: tab0

### python
- 26185	parse: unexpected token after SELECT statement
- 19318	parse: expected prefix expression
- 14655	statement: unsupported leading kw '<s>'
- 11266	compile: internal: unhandled Expr variant ExprCast
- 9760	compile: unknown column: pk
- 9126	compile: projection references column not in GROUP BY
- 4492	parse: deferred: DISTINCT in SUM() unsupported
- 4457	parse: deferred: DISTINCT in MIN() unsupported
- 4429	parse: deferred: DISTINCT in MAX() unsupported
- 3758	compile: deferred: <n>-or-more-way JOIN


## Top 10 FAIL reasons per target

### rust
- 28563	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=[]
- 12290	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 5926	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 3926	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>"]
- 3503	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=[]
- 3461	got(<n>)=[] expected(<n>)=["<s>", "<s>", "<s>"]
- 3167	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 2926	got(<n>)=["<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>"]
- 2617	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>...
- 2250	hash mismatch: count got=<n> expected=<n>, md5 got=2f8e5bef97f41cd641eafba46c99a49d expected=ee724f9f159f8cdef185b42c43b...

### c
- 340666	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 64363	got(<n>) expected(<n>): cell <n> got=-<n> expected=-<n>
- 39250	row count mismatch: <n> cells vs expected <n>
- 12290	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 7872	got(<n>) expected(<n>): cell <n> got=<n> expected=NULL
- 2250	hash mismatch: count got=<n> expected=<n>, md5 got=2f8e5bef97f41cd641eafba46c99a49d expected=ee724f9f159f8cdef185b42c43b...
- 2150	hash mismatch: count got=<n> expected=<n>, md5 got=f40a1ef6542491a0f490c50802955a8e expected=fd5ef87ee372019414f0b3de2d9...
- 2075	hash mismatch: count got=<n> expected=<n>, md5 got=69ea35c77af3760266d28e7abca05b5f expected=41188ae9f1de9f62c029b0ba1e6...
- 2000	hash mismatch: count got=<n> expected=<n>, md5 got=287c225018dcf5275d60795ef673033b expected=665eeefca657f1f6c2d4f2ba683...
- 1975	hash mismatch: count got=<n> expected=<n>, md5 got=376a57a72b63bbd0b53390c7ee72216a expected=ac073ee6ea28ef0ed712cb7c239...

### go
- 48887	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 43653	got(<n>)=["<s>" "<s>"] expected(<n>)=["<s>" "<s>"]
- 38121	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 37788	got(<n>)=["<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>"]
- 37579	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>...
- 33460	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 25292	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 19411	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"]
- 17421	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 12290	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...

### zig
- 67586	got(<n>) expected(<n>) first got=<n> expected=<n>
- 13233	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 4295	got(<n>) expected(<n>) first got=<n> expected=<none>
- 1993	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 1578	got(<n>) expected(<n>) first got=<n> expected=NULL
- 1134	got(<n>) expected(<n>) first got=-<n> expected=<none>
- 558	got(<n>) expected(<n>) first got=<none> expected=<n>
- 375	hash mismatch: count got=<n> expected=<n>, md5 got=f40a1ef6542491a0f490c50802955a8e expected=fd5ef87ee372019414f0b3de2d9...
- 367	hash mismatch: count got=<n> expected=<n>, md5 got=efbd3c7dcd524b8e5a7ac0ff665c4d2b expected=4489461d3189f4bad5a97addbf2...
- 350	hash mismatch: count got=<n> expected=<n>, md5 got=9450c60ae45c2a048a168cafd074de70 expected=7498563d8adaf267407406c5a67...

### python
- 31004	got(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>'] expected(<n>)=[]
- 12290	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 11468	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 8934	index '<s>' already exists
- 4072	got(<n>)=[] expected(<n>)=['<s>']
- 3932	got(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 3745	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>']
- 3736	got(<n>)=['<s>', '<s>', '<s>'] expected(<n>)=[]
- 3181	got(<n>)=['<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>']
- 2926	got(<n>)=['<s>', '<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>', '<s>']
