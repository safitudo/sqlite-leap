# 5-target corpus run 2026-04-25 (post runner-format upgrade)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | PASS rate |
| --- | --- | --- | --- | --- | --- | --- |
| rust | 1544650 | 8555 | 4848 | 88464 | 1646517 | 93.81% |
| c | 1086385 | 430517 | 20348 | 90220 | 1627470 | 66.75% |
| go | 1050530 | 297380 | 19003 | 39724 | 1406637 | 74.68% |
| zig | 245908 | 108668 | 21772 | 30194 | 406542 | 60.49% |
| python | 1012042 | 530001 | 113175 | 134851 | 1790069 | 56.54% |

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
- 7954	compile: deferred: unsupported expression kind in aggregate projection/HAVING
- 2606	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 2139	compile: deferred: scalar subquery
- 1146	compile: ambiguous column: col0
- 854	compile: deferred: function call MIN_distinct
- 806	compile: deferred: function call SUM_distinct
- 799	compile: deferred: function call MAX_distinct
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
- 272	compile: deferred: function call AVG_distinct
- 271	compile: deferred: function call MAX_distinct
- 159	compile: deferred: unknown expression node
- 128	compile: deferred: <n>-or-more-way JOIN with aggregation

### zig
- 1827	compile: deferred: derived-table subquery in FROM
- 1565	compile: deferred: JOIN with aggregation
- 1308	compile: deferred: aggregate in scalar context
- 796	compile: deferred: mixed INTERSECT/EXCEPT/UNION in one compound SELECT
- 714	compile: unknown table in JOIN: tab1
- 702	compile: unknown table in JOIN: tab2
- 682	compile: unknown table in JOIN: tab0
- 517	compile: deferred: IN subquery
- 356	compile: deferred: function call MAX_distinct
- 355	compile: deferred: function call SUM_distinct

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
- 2603	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 945	hash mismatch: count got=<n> expected=<n>, md5 got=b833e3a3ba082b2c0028b4cd08f0834d expected=db761b746c7d0f18810c20311a9...
- 664	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>"]
- 393	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>"]
- 260	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 168	hash mismatch: count got=<n> expected=<n>, md5 got=8b75136b2b51c77345c03804ec1cda5c expected=cd7a7901e47c15155404aff0d21...
- 151	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>"]
- 68	hash mismatch: count got=<n> expected=<n>, md5 got=e2568b01dd411b5a206068697d0ed0d2 expected=16be8868a1e6f4e8850509f9327...
- 54	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>", "<s>"]
- 36	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]

### c
- 349256	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 69874	got(<n>) expected(<n>): cell <n> got=-<n> expected=-<n>
- 8455	got(<n>) expected(<n>): cell <n> got=<n> expected=NULL
- 945	hash mismatch: count got=<n> expected=<n>, md5 got=b833e3a3ba082b2c0028b4cd08f0834d expected=db761b746c7d0f18810c20311a9...
- 33	execute: halt rc=<n>
- 32	install: too many tables
- 20	hash mismatch: count got=<n> expected=<n>, md5 got=bcacc2835f645a422e7c49b22a4249ee expected=c28bfbaaee0fa364e85ac2df047...
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=141999cb1d7a52c7485621f955e65308 expected=74b4b1d1e049d57b3610b70a67a...
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=3374e1a1fb9e3a97f5c3a1ba7aaec518 expected=a8508bcdf86e494dd5feccb5ca8...
- 10	schema: unknown table t33

### go
- 48218	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 43301	got(<n>)=["<s>" "<s>"] expected(<n>)=["<s>" "<s>"]
- 38202	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 37826	got(<n>)=["<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>"]
- 37601	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>...
- 31934	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 19471	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"]
- 17465	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 7325	execute: no such view "<s>"
- 1596	got(<n>)=["<s>"] expected(<n>)=[]

### zig
- 82685	got(<n>) expected(<n>) first got=<n> expected=<n>
- 20754	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 3527	got(<n>) expected(<n>) first got=<n> expected=NULL
- 265	hash mismatch: count got=<n> expected=<n>, md5 got=b833e3a3ba082b2c0028b4cd08f0834d expected=db761b746c7d0f18810c20311a9...
- 55	got(<n>) expected(<n>) first got=-<n> expected=<n>
- 20	got(<n>) expected(<n>) first got=<n> expected=-<n>
- 17	hash mismatch: count got=<n> expected=<n>, md5 got=8b75136b2b51c77345c03804ec1cda5c expected=cd7a7901e47c15155404aff0d21...
- 16	(no detail)
- 11	got(<n>) expected(<n>) first got=<n> expected=<none>
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=bcacc2835f645a422e7c49b22a4249ee expected=c28bfbaaee0fa364e85ac2df047...

### python
- 92554	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=e20b902b49a98b1a05ed62804c7...
- 32419	got(<n>)=[] expected(<n>)=['<s>', '<s>']
- 29324	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>']
- 28764	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 28644	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 27263	got(<n>)=[] expected(<n>)=['<s>']
- 15056	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>']
- 13530	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>']
- 13196	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 9424	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=9d3557642e57f7f03e636d9ae90...
