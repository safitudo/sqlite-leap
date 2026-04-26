# 5-target corpus run 2026-04-25 (post runner-format upgrade)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | PASS rate |
| --- | --- | --- | --- | --- | --- | --- |
| rust | 1488378 | 64826 | 4848 | 88464 | 1646516 | 90.40% |
| c | 1031330 | 464717 | 22814 | 90211 | 1609072 | 64.09% |
| go | 1016313 | 332417 | 19008 | 39873 | 1407611 | 72.20% |
| zig | 4694 | 1788 | 3991 | 10 | 10483 | 44.78% |
| python | 990669 | 551374 | 113175 | 134851 | 1790069 | 55.34% |

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
- 7571	compile: deferred: unsupported expression kind in aggregate projection/HAVING
- 2606	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 2139	compile: deferred: scalar subquery
- 1146	compile: ambiguous column: col0
- 963	compile: unknown column in aggregate projection: col1
- 957	compile: unknown column in aggregate projection: col2
- 927	compile: unknown column in aggregate projection: col0
- 854	compile: deferred: function call MIN_distinct
- 806	compile: deferred: function call SUM_distinct
- 801	compile: deferred: function call MAX_distinct

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
- 1207	compile: deferred: aggregate in scalar context
- 796	compile: deferred: mixed INTERSECT/EXCEPT/UNION in one compound SELECT
- 124	compile: unknown table in JOIN: t4
- 110	compile: unknown table in JOIN: t2
- 109	compile: unknown table in JOIN: t5
- 106	compile: unknown table in JOIN: t6
- 100	compile: unknown table in JOIN: t3
- 98	compile: unknown table in JOIN: t7
- 95	compile: unknown table in JOIN: t9
- 89	compile: unknown table in JOIN: t1

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
- 336537	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 66301	got(<n>) expected(<n>): cell <n> got=-<n> expected=-<n>
- 39331	row count mismatch: <n> cells vs expected <n>
- 7860	got(<n>) expected(<n>): cell <n> got=<n> expected=NULL
- 1120	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=b833e3a3ba082b2c0028b4cd08f...
- 889	got(<n>) expected(<n>): cell <n> got=<n> expected=-<n>
- 637	got(<n>) expected(<n>): cell <n> got=-<n> expected=<n>
- 629	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=c6c0a4111b36d04dbc811a11e4d...
- 619	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=75c998aa53ac83218cbf2feb962...
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
- 615	got(<n>) expected(<n>) first got=<n> expected=<n>
- 26	got(<n>) expected(<n>) first got=<n> expected=NULL
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=141999cb1d7a52c7485621f955e65308 expected=74b4b1d1e049d57b3610b70a67a...
- 8	expected error, got success
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=b826057329a4e68017a62a931747cb26 expected=5026537fcfcc7d06e2928e16f9b...
- 8	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=c09f5d015b20412d5607cb222a4d526e expected=d4ce8ba735d9acaa3b10b7b1a10...
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=f9dd945f07c787fd3686e2672098de10 expected=e48615ff8ca5cfc049146260f31...
- 7	hash mismatch: count got=<n> expected=<n>, md5 got=62ae97a879cc9060e9c1fc2084546d94 expected=fd6d6825820cf653aceb2d72af4...
- 6	hash mismatch: count got=<n> expected=<n>, md5 got=bd98bbe0961d3ef375f3ce1a261ae628 expected=efdbaa4d180e7867bec1c4d897b...

### python
- 92554	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=e20b902b49a98b1a05ed62804c7...
- 32628	got(<n>)=[] expected(<n>)=['<s>', '<s>']
- 29341	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>']
- 29047	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 28648	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 27812	got(<n>)=[] expected(<n>)=['<s>']
- 16973	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>']
- 15063	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>']
- 13202	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 9424	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=9d3557642e57f7f03e636d9ae90...
