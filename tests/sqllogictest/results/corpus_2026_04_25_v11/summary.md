# v10 corpus run 2026-04-25 (5 leap targets + mainline sqlite baseline)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP | excl-SKIP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rust | 1548925 | 4280 | 4848 | 88464 | 1646517 | 94.07% | 99.41% |
| c | 1459541 | 4863 | 7405 | 83229 | 1555038 | 93.86% | 99.17% |
| go | 1486757 | 16765 | 20998 | 83741 | 1608261 | 92.45% | 97.52% |
| zig | 408036 | 2284 | 23352 | 36843 | 470515 | 86.72% | 94.09% |
| python | 1081938 | 558818 | 11062 | 134851 | 1786669 | 60.56% | 65.50% |
| sqlite | 1655199 | 19 | 0 | 134851 | 1790069 | 92.47% | 100.00% |

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
- 2139	compile: deferred: scalar subquery
- 1627	compile: ambiguous column: col0
- 552	compile: deferred: complex expression in JOIN context
- 455	compile: ambiguous column: pk
- 328	compile: deferred: EXISTS subquery
- 197	parse: <pos> deferred: parenthesized table-ref
- 188	compile: deferred: <n>-or-more-way JOIN with aggregation
- 86	compile: unknown table: t2 (schema is for t1)
- 80	compile: unknown table: t6 (schema is for t1)
- 77	compile: unknown table: t4 (schema is for t1)

### go
- 3368	parse: parse error at token <n> (line <n> col <n>): unexpected token after SELECT statement
- 1879	compile: deferred α23: correlated subquery with aggregate / GROUP BY / compound
- 1856	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 576	compile: ambiguous column: col0
- 428	compile: deferred: unknown expression node
- 345	compile: ambiguous column: pk
- 197	parse: parse error at token <n> (line <n> col <n>): deferred: parenthesized table-ref / subquery in FROM
- 70	parse: parse error at token <n> (line <n> col <n>): expected '<s>' after IN
- 39	compile: deferred: star projection in aggregate query
- 13	statement: unsupported leading kw "<s>"

### zig
- 2052	compile: deferred: derived-table subquery in FROM
- 1998	compile: deferred: JOIN with aggregation
- 1371	compile: deferred: aggregate in scalar context
- 1054	compile: unknown table in JOIN: tab2
- 1043	compile: unknown table in JOIN: tab1
- 947	compile: unknown table in JOIN: tab0
- 796	compile: deferred: mixed INTERSECT/EXCEPT/UNION in one compound SELECT
- 550	compile: deferred: IN subquery
- 229	compile: unknown table in JOIN: t2
- 228	compile: deferred: DISTINCT/ORDER BY across JOIN

### python
- 3287	compile: INSERT from SELECT requires source schema
- 2595	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 2351	compile: deferred: correlated subquery (Python pre-execute model)
- 1146	compile: ambiguous column: col0
- 455	compile: ambiguous column: pk
- 426	compile: deferred: <n>-or-more-way JOIN with aggregation
- 410	compile: deferred: expression ExprCast across JOIN sources
- 197	parse: expected SELECT after '<s>' in FROM (parenthesized JOIN deferred)
- 70	parse: expected '<s>' after IN
- 41	compile: deferred: star projection in aggregate query

### sqlite


## Top 10 FAIL reasons per target

### rust
- 945	hash mismatch: count got=<n> expected=<n>, md5 got=b833e3a3ba082b2c0028b4cd08f0834d expected=db761b746c7d0f18810c20311a9...
- 168	hash mismatch: count got=<n> expected=<n>, md5 got=8b75136b2b51c77345c03804ec1cda5c expected=cd7a7901e47c15155404aff0d21...
- 68	hash mismatch: count got=<n> expected=<n>, md5 got=e2568b01dd411b5a206068697d0ed0d2 expected=16be8868a1e6f4e8850509f9327...
- 28	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 27	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=[]
- 21	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>...
- 20	hash mismatch: count got=<n> expected=<n>, md5 got=bcacc2835f645a422e7c49b22a4249ee expected=c28bfbaaee0fa364e85ac2df047...
- 15	got(<n>)=["<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>"]
- 15	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>"]
- 13	hash mismatch: count got=<n> expected=<n>, md5 got=1f117f467f45d8c6b7553e2e3c842942 expected=cb33c30d6f52bbb24338a293c74...

### c
- 1917	row count mismatch: <n> cells vs expected <n>
- 945	hash mismatch: count got=<n> expected=<n>, md5 got=b833e3a3ba082b2c0028b4cd08f0834d expected=db761b746c7d0f18810c20311a9...
- 32	install: too many tables
- 20	execute: halt rc=<n>
- 20	hash mismatch: count got=<n> expected=<n>, md5 got=bcacc2835f645a422e7c49b22a4249ee expected=c28bfbaaee0fa364e85ac2df047...
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=141999cb1d7a52c7485621f955e65308 expected=74b4b1d1e049d57b3610b70a67a...
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=3374e1a1fb9e3a97f5c3a1ba7aaec518 expected=a8508bcdf86e494dd5feccb5ca8...
- 10	schema: unknown table t33
- 10	schema: unknown table t34
- 10	schema: unknown table t35

### go
- 1596	got(<n>)=["<s>"] expected(<n>)=[]
- 1155	got(<n>)=["<s>" "<s>"] expected(<n>)=[]
- 945	hash mismatch: count got=<n> expected=<n>, md5 got=b833e3a3ba082b2c0028b4cd08f0834d expected=db761b746c7d0f18810c20311a9...
- 830	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=[]
- 645	got(<n>)=["<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 510	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 420	got(<n>)=["<s>" "<s>"] expected(<n>)=["<s>"]
- 390	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 285	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 260	got(<n>)=["<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>"]

### zig
- 290	hash mismatch: count got=<n> expected=<n>, md5 got=b833e3a3ba082b2c0028b4cd08f0834d expected=db761b746c7d0f18810c20311a9...
- 241	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 203	got(<n>) expected(<n>) first got=<n> expected=<n>
- 60	got(<n>) expected(<n>) first got=<n> expected=NULL
- 26	hash mismatch: count got=<n> expected=<n>, md5 got=8b75136b2b51c77345c03804ec1cda5c expected=cd7a7901e47c15155404aff0d21...
- 21	got(<n>) expected(<n>) first got=-<n> expected=<n>
- 16	got(<n>) expected(<n>) first got=<n> expected=-<n>
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=bcacc2835f645a422e7c49b22a4249ee expected=c28bfbaaee0fa364e85ac2df047...
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=5ba796b544ceea43d0af7fb3eaf92919 expected=9a6afb6b859fc856aafb6a7af11...
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=141999cb1d7a52c7485621f955e65308 expected=74b4b1d1e049d57b3610b70a67a...

### python
- 99286	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=e20b902b49a98b1a05ed62804c7...
- 34304	got(<n>)=[] expected(<n>)=['<s>', '<s>']
- 30940	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>']
- 30472	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 30456	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 27980	got(<n>)=[] expected(<n>)=['<s>']
- 15988	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>']
- 14488	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>']
- 14180	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 9832	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=9d3557642e57f7f03e636d9ae90...

### sqlite
- 13	OperationalError: no such table: t1
- 3	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 1	OperationalError: integer overflow
- 1	expected error, got success
- 1	OperationalError: no such trigger: t1r1
