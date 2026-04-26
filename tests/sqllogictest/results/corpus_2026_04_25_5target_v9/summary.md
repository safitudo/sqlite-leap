# 5-target corpus run 2026-04-25 (post runner-format upgrade)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | PASS rate |
| --- | --- | --- | --- | --- | --- | --- |
| rust | 1544650 | 8555 | 4848 | 88464 | 1646517 | 93.81% |
| c | 1070236 | 385140 | 13077 | 83549 | 1552002 | 68.96% |
| go | 1050530 | 297380 | 19003 | 39724 | 1406637 | 74.68% |
| zig | 250572 | 111617 | 22644 | 32221 | 417054 | 60.08% |
| python | 1064231 | 567405 | 21744 | 134851 | 1788231 | 59.51% |

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
- 2606	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 2139	compile: deferred: scalar subquery
- 1146	compile: ambiguous column: col0
- 1109	compile: deferred: function call MIN_distinct
- 1039	compile: deferred: function call MAX_distinct
- 1028	compile: deferred: function call SUM_distinct
- 455	compile: ambiguous column: pk
- 453	compile: deferred: function call AVG_distinct
- 435	compile: deferred: complex expression in JOIN context
- 328	compile: deferred: EXISTS subquery

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
- 1907	compile: deferred: derived-table subquery in FROM
- 1666	compile: deferred: JOIN with aggregation
- 1347	compile: deferred: aggregate in scalar context
- 796	compile: deferred: mixed INTERSECT/EXCEPT/UNION in one compound SELECT
- 768	compile: unknown table in JOIN: tab1
- 760	compile: unknown table in JOIN: tab2
- 719	compile: unknown table in JOIN: tab0
- 520	compile: deferred: IN subquery
- 385	compile: deferred: function call SUM_distinct
- 375	compile: deferred: function call MAX_distinct

### python
- 3649	compile: deferred: <n>-or-more-way JOIN
- 3287	compile: INSERT from SELECT requires source schema
- 2595	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 2362	parse: deferred: DISTINCT in SUM() unsupported
- 2351	compile: deferred: correlated subquery (Python pre-execute model)
- 2343	parse: deferred: DISTINCT in MIN() unsupported
- 2336	parse: deferred: DISTINCT in MAX() unsupported
- 874	parse: deferred: DISTINCT in AVG() unsupported
- 455	compile: ambiguous column: pk
- 426	compile: deferred: <n>-or-more-way JOIN with aggregation


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
- 316395	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 56048	got(<n>) expected(<n>): cell <n> got=-<n> expected=-<n>
- 9799	got(<n>) expected(<n>): cell <n> got=<n> expected=NULL
- 945	hash mismatch: count got=<n> expected=<n>, md5 got=b833e3a3ba082b2c0028b4cd08f0834d expected=db761b746c7d0f18810c20311a9...
- 32	install: too many tables
- 20	hash mismatch: count got=<n> expected=<n>, md5 got=bcacc2835f645a422e7c49b22a4249ee expected=c28bfbaaee0fa364e85ac2df047...
- 10	schema: unknown table t33
- 10	schema: unknown table t34
- 10	schema: unknown table t35
- 10	schema: unknown table t36

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
- 83847	got(<n>) expected(<n>) first got=<n> expected=<n>
- 22235	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 3751	got(<n>) expected(<n>) first got=<n> expected=NULL
- 285	hash mismatch: count got=<n> expected=<n>, md5 got=b833e3a3ba082b2c0028b4cd08f0834d expected=db761b746c7d0f18810c20311a9...
- 57	got(<n>) expected(<n>) first got=-<n> expected=<n>
- 20	got(<n>) expected(<n>) first got=<n> expected=-<n>
- 18	hash mismatch: count got=<n> expected=<n>, md5 got=8b75136b2b51c77345c03804ec1cda5c expected=cd7a7901e47c15155404aff0d21...
- 11	got(<n>) expected(<n>) first got=<n> expected=<none>
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=bcacc2835f645a422e7c49b22a4249ee expected=c28bfbaaee0fa364e85ac2df047...
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=141999cb1d7a52c7485621f955e65308 expected=74b4b1d1e049d57b3610b70a67a...

### python
- 99286	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=e20b902b49a98b1a05ed62804c7...
- 34511	got(<n>)=[] expected(<n>)=['<s>', '<s>']
- 30940	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>']
- 30476	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 30456	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 29579	got(<n>)=[] expected(<n>)=['<s>']
- 15988	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>']
- 14528	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>']
- 14180	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 9832	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=9d3557642e57f7f03e636d9ae90...
