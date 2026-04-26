# 5-target corpus run 2026-04-25 (post runner-format upgrade)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | PASS rate |
| --- | --- | --- | --- | --- | --- | --- |
| rust | 1375331 | 169498 | 13224 | 88464 | 1646517 | 83.53% |
| c | 906113 | 553722 | 116951 | 90421 | 1667207 | 54.35% |
| go | 911446 | 424382 | 41990 | 42293 | 1420111 | 64.18% |
| zig | 187122 | 125891 | 60944 | 31854 | 405811 | 46.11% |
| python | 1364187 | 194068 | 231471 | 8 | 1789734 | 76.22% |

## Top 10 DEFER reasons per target

### rust
- 3130	compile: deferred: compound SELECT with CTE or derived FROM
- 3043	compile: projection references column not in GROUP BY
- 1086	compile: aggregate without FROM is unsupported
- 996	compile: deferred: function call MIN_distinct
- 961	compile: deferred: function call SUM_distinct
- 960	compile: deferred: function call MAX_distinct
- 490	compile: non-aggregate column in projection of aggregate query
- 452	compile: deferred: function call AVG_distinct
- 346	compile: HAVING references column not in GROUP BY
- 272	compile: deferred: DISTINCT across JOIN sources

### c
- 52711	compile: deferred: IN subquery
- 17839	compile: compile_select: FROM is a JOIN; use compile_select_multi
- 7346	compile: deferred: unsupported expression kind in aggregate projection/HAVING
- 7335	statement: unsupported leading kw CREATE
- 4112	compile: deferred: function call
- 2854	compile: projection references column not in GROUP BY: col0
- 2803	compile: projection references column not in GROUP BY: col2
- 2743	compile: projection references column not in GROUP BY: col1
- 2440	compile: internal: compile_select_buffered without g_subctx
- 1760	compile: deferred: scalar subquery

### go
- 10760	compile: deferred: compound SELECT
- 7348	statement: unsupported leading kw "<s>"
- 2980	compile: projection references column not in GROUP BY
- 2440	compile: deferred: derived-table subquery in FROM
- 1701	compile: deferred α23: correlated subquery with aggregate / GROUP BY / compound
- 1553	compile: aggregate without FROM is unsupported
- 1399	compile: JOIN requires multi-schema compile path; use CompileSelectMulti
- 766	compile: deferred: function call avg
- 601	parse: parse error at token <n> (line <n> col <n>): unexpected token after SELECT statement
- 388	compile: deferred: unknown expression node

### zig
- 10760	compile: deferred: compound SELECT
- 9249	compile: deferred: IN subquery
- 8945	compile: aggregate without FROM is unsupported
- 7335	statement: unsupported leading kw CREATE
- 2815	compile: projection references column not in GROUP BY
- 2440	compile: deferred: derived-table subquery in FROM
- 2369	compile: deferred: DISTINCT/ORDER BY without FROM
- 1719	compile: deferred: scalar subquery
- 1704	compile: deferred: JOIN with aggregation
- 630	compile: unknown table in JOIN: tab1

### python
- 52711	compile: internal: unhandled Expr variant ExprInSubquery
- 47752	compile: aggregate without FROM is unsupported
- 26185	parse: unexpected token after SELECT statement
- 19318	parse: expected prefix expression
- 14655	statement: unsupported leading kw '<s>'
- 11266	compile: internal: unhandled Expr variant ExprCast
- 9126	compile: projection references column not in GROUP BY
- 4492	parse: deferred: DISTINCT in SUM() unsupported
- 4457	parse: deferred: DISTINCT in MIN() unsupported
- 4429	parse: deferred: DISTINCT in MAX() unsupported


## Top 10 FAIL reasons per target

### rust
- 28563	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=[]
- 12290	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 5479	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 3926	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>"]
- 3457	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=[]
- 3444	got(<n>)=[] expected(<n>)=["<s>", "<s>", "<s>"]
- 3166	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 2926	got(<n>)=["<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>"]
- 2617	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>...
- 2250	hash mismatch: count got=<n> expected=<n>, md5 got=2f8e5bef97f41cd641eafba46c99a49d expected=ee724f9f159f8cdef185b42c43b...

### c
- 332783	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 62858	got(<n>) expected(<n>): cell <n> got=-<n> expected=-<n>
- 39164	row count mismatch: <n> cells vs expected <n>
- 11780	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 7868	got(<n>) expected(<n>): cell <n> got=<n> expected=NULL
- 2200	hash mismatch: count got=<n> expected=<n>, md5 got=2f8e5bef97f41cd641eafba46c99a49d expected=ee724f9f159f8cdef185b42c43b...
- 2100	hash mismatch: count got=<n> expected=<n>, md5 got=f40a1ef6542491a0f490c50802955a8e expected=fd5ef87ee372019414f0b3de2d9...
- 1925	hash mismatch: count got=<n> expected=<n>, md5 got=287c225018dcf5275d60795ef673033b expected=665eeefca657f1f6c2d4f2ba683...
- 1925	hash mismatch: count got=<n> expected=<n>, md5 got=376a57a72b63bbd0b53390c7ee72216a expected=ac073ee6ea28ef0ed712cb7c239...
- 1925	hash mismatch: count got=<n> expected=<n>, md5 got=337cd209751d7466f9299dacb931e8a3 expected=ba461e878c0df14081008c4853f...

### go
- 48490	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 43384	got(<n>)=["<s>" "<s>"] expected(<n>)=["<s>" "<s>"]
- 37976	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 37638	got(<n>)=["<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>"]
- 37399	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>...
- 32785	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 25292	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 19266	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"]
- 17265	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 12290	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...

### zig
- 74384	got(<n>) expected(<n>) first got=<n> expected=<n>
- 17379	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 4337	got(<n>) expected(<n>) first got=<n> expected=<none>
- 2347	got(<n>) expected(<n>) first got=<n> expected=NULL
- 1997	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 1136	got(<n>) expected(<n>) first got=-<n> expected=<none>
- 569	got(<n>) expected(<n>) first got=<none> expected=<n>
- 383	hash mismatch: count got=<n> expected=<n>, md5 got=efbd3c7dcd524b8e5a7ac0ff665c4d2b expected=4489461d3189f4bad5a97addbf2...
- 375	hash mismatch: count got=<n> expected=<n>, md5 got=f40a1ef6542491a0f490c50802955a8e expected=fd5ef87ee372019414f0b3de2d9...
- 350	hash mismatch: count got=<n> expected=<n>, md5 got=9450c60ae45c2a048a168cafd074de70 expected=7498563d8adaf267407406c5a67...

### python
- 30993	got(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>'] expected(<n>)=[]
- 11780	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 10195	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 8934	index '<s>' already exists
- 3734	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>']
- 3732	got(<n>)=['<s>', '<s>', '<s>'] expected(<n>)=[]
- 3705	got(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 3125	got(<n>)=['<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>']
- 2796	got(<n>)=['<s>', '<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>', '<s>']
- 2582	got(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>...
