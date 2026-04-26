# 5-target corpus run 2026-04-25 (post runner-format upgrade)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | PASS rate |
| --- | --- | --- | --- | --- | --- | --- |
| rust | 1488379 | 64826 | 4848 | 88464 | 1646517 | 90.40% |
| c | 1031361 | 467325 | 20390 | 90336 | 1609412 | 64.08% |
| go | 1016313 | 332417 | 19008 | 39873 | 1407611 | 72.20% |
| zig | 0 | 0 | 0 | 0 | 0 | 0.00% |
| python | 932662 | 608637 | 113919 | 134851 | 1790069 | 52.10% |

## Top 10 DEFER reasons per target

### rust
- 3130	compile: deferred: compound SELECT with CTE or derived FROM
- 256	compile: deferred: DISTINCT across JOIN sources
- 197	parse: <pos> deferred: parenthesized table-ref / subquery in FROM
- 89	compile: unknown table: t2 (schema is for t1)
- 85	compile: unknown table: t6 (schema is for t1)
- 80	compile: unknown table: t7 (schema is for t1)
- 79	compile: unknown table: t4 (schema is for t1)
- 74	compile: deferred: IN subquery
- 74	compile: unknown table: t8 (schema is for t1)
- 72	compile: unknown table: t3 (schema is for t1)

### c
- 7988	compile: deferred: unsupported expression kind in aggregate projection/HAVING
- 2606	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 2139	compile: deferred: scalar subquery
- 1146	compile: ambiguous column: col0
- 855	compile: deferred: function call MIN_distinct
- 809	compile: deferred: function call SUM_distinct
- 802	compile: deferred: function call MAX_distinct
- 455	compile: ambiguous column: pk
- 435	compile: deferred: complex expression in JOIN context
- 426	compile: deferred: <n>-or-more-way JOIN with aggregation

### go
- 2260	compile: deferred: <n>-or-more-way JOIN
- 1879	compile: deferred α23: correlated subquery with aggregate / GROUP BY / compound
- 490	parse: parse error at token <n> (line <n> col <n>): unexpected token after SELECT statement
- 327	compile: deferred: function call MIN_distinct
- 320	compile: ambiguous column: pk
- 282	compile: deferred: function call SUM_distinct
- 277	compile: deferred: function call AVG_distinct
- 271	compile: deferred: function call MAX_distinct
- 159	compile: deferred: unknown expression node
- 128	compile: deferred: <n>-or-more-way JOIN with aggregation

### zig

### python
- 52785	compile: internal: unhandled Expr variant ExprInSubquery
- 10103	parse: expected prefix expression
- 5795	compile: internal: unhandled Expr variant ExprCast
- 3638	compile: unknown table in JOIN: tab2
- 3581	compile: unknown table in JOIN: tab0
- 3566	compile: unknown table in JOIN: tab1
- 3287	compile: INSERT from SELECT requires source schema
- 2440	compile: internal: unhandled TableRef TableRefSubquery
- 2304	parse: deferred: DISTINCT in SUM() unsupported
- 2285	parse: deferred: DISTINCT in MIN() unsupported


## Top 10 FAIL reasons per target

### rust
- 28563	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=[]
- 5959	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 3534	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=[]
- 3494	got(<n>)=[] expected(<n>)=["<s>", "<s>", "<s>"]
- 2582	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 1600	got(<n>)=[] expected(<n>)=["<s>"]
- 1587	got(<n>)=["<s>"] expected(<n>)=[]
- 1130	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=b833e3a3ba082b2c0028b4cd08f...
- 682	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>"]
- 630	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=c6c0a4111b36d04dbc811a11e4d...

### c
- 338286	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 67173	got(<n>) expected(<n>): cell <n> got=-<n> expected=-<n>
- 39345	row count mismatch: <n> cells vs expected <n>
- 7873	got(<n>) expected(<n>): cell <n> got=<n> expected=NULL
- 1120	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=b833e3a3ba082b2c0028b4cd08f...
- 870	got(<n>) expected(<n>): cell <n> got=<n> expected=-<n>
- 629	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=c6c0a4111b36d04dbc811a11e4d...
- 619	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=75c998aa53ac83218cbf2feb962...
- 618	got(<n>) expected(<n>): cell <n> got=-<n> expected=<n>
- 538	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=c4b42765dff94eaaa46040e537f...

### go
- 46985	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 43177	got(<n>)=["<s>" "<s>"] expected(<n>)=["<s>" "<s>"]
- 38116	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 37787	got(<n>)=["<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>"]
- 37576	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>...
- 31223	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 25292	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 19411	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"]
- 17420	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 7325	execute: no such view "<s>"

### zig

### python
- 194312	got=[] expected=['<s>']
- 80810	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=e20b902b49a98b1a05ed62804c7...
- 29740	got=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s...
- 24852	got(<n>)=[] expected(<n>)=['<s>']
- 17248	got=[] expected=['<s>', '<s>']
- 15380	got(<n>)=[] expected(<n>)=['<s>', '<s>']
- 15103	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 14853	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>']
- 14760	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 14605	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>']
