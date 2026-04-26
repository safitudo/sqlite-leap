# v10 corpus run 2026-04-25 (5 leap targets + mainline sqlite baseline)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP | excl-SKIP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rust | 1544650 | 8555 | 4848 | 88464 | 1646517 | 93.81% | 99.14% |
| c | 1076716 | 391370 | 13077 | 83549 | 1564712 | 68.81% | 72.69% |
| go | 1330909 | 17001 | 19003 | 39724 | 1406637 | 94.62% | 97.37% |
| zig | 159269 | 46020 | 5432 | 10 | 210731 | 75.58% | 75.58% |
| python | 1074576 | 563512 | 13732 | 134849 | 1786669 | 60.14% | 65.05% |
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
- 1347	compile: deferred: aggregate in scalar context
- 796	compile: deferred: mixed INTERSECT/EXCEPT/UNION in one compound SELECT
- 407	compile: deferred: IN subquery
- 229	compile: unknown table in JOIN: t2
- 227	compile: unknown table in JOIN: t4
- 214	compile: unknown table in JOIN: t9
- 204	compile: unknown table in JOIN: t8
- 200	compile: unknown table in JOIN: t5
- 193	compile: unknown table in JOIN: t6
- 188	compile: unknown table in JOIN: t3

### python
- 3287	compile: INSERT from SELECT requires source schema
- 2595	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 2594	compile: internal: unhandled Expr variant ExprInSubquery
- 2351	compile: deferred: correlated subquery (Python pre-execute model)
- 1146	compile: ambiguous column: col0
- 455	compile: ambiguous column: pk
- 426	compile: deferred: <n>-or-more-way JOIN with aggregation
- 410	compile: deferred: expression ExprCast across JOIN sources
- 197	parse: expected SELECT after '<s>' in FROM (parenthesized JOIN deferred)
- 99	statement: unsupported leading kw '<s>'

### sqlite


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
- 322585	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 56048	got(<n>) expected(<n>): cell <n> got=-<n> expected=-<n>
- 9799	got(<n>) expected(<n>): cell <n> got=<n> expected=NULL
- 945	hash mismatch: count got=<n> expected=<n>, md5 got=b833e3a3ba082b2c0028b4cd08f0834d expected=db761b746c7d0f18810c20311a9...
- 40	execute: halt rc=<n>
- 32	install: too many tables
- 20	hash mismatch: count got=<n> expected=<n>, md5 got=bcacc2835f645a422e7c49b22a4249ee expected=c28bfbaaee0fa364e85ac2df047...
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=141999cb1d7a52c7485621f955e65308 expected=74b4b1d1e049d57b3610b70a67a...
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=3374e1a1fb9e3a97f5c3a1ba7aaec518 expected=a8508bcdf86e494dd5feccb5ca8...
- 10	schema: unknown table t33

### go
- 1596	got(<n>)=["<s>"] expected(<n>)=[]
- 1155	got(<n>)=["<s>" "<s>"] expected(<n>)=[]
- 915	hash mismatch: count got=<n> expected=<n>, md5 got=b833e3a3ba082b2c0028b4cd08f0834d expected=db761b746c7d0f18810c20311a9...
- 830	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=[]
- 645	got(<n>)=["<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 510	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 420	got(<n>)=["<s>" "<s>"] expected(<n>)=["<s>"]
- 390	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 314	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 285	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]

### zig
- 44650	got(<n>) expected(<n>) first got=<n> expected=<n>
- 26	got(<n>) expected(<n>) first got=<n> expected=NULL
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=141999cb1d7a52c7485621f955e65308 expected=74b4b1d1e049d57b3610b70a67a...
- 8	expected error, got success
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=b826057329a4e68017a62a931747cb26 expected=5026537fcfcc7d06e2928e16f9b...
- 8	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=c09f5d015b20412d5607cb222a4d526e expected=d4ce8ba735d9acaa3b10b7b1a10...
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=f9dd945f07c787fd3686e2672098de10 expected=e48615ff8ca5cfc049146260f31...
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=223d1e2bb9f666c7d541a3820d49118b expected=7ece664b68f1d5dd5df20c38b45...
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=a6ab8660ce234346838d3361d4915eec expected=33946dd780d80a44b8a5a40324a...

### python
- 98414	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=e20b902b49a98b1a05ed62804c7...
- 30528	got(<n>)=[] expected(<n>)=['<s>', '<s>']
- 28576	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 28144	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 27804	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>']
- 27340	got(<n>)=[] expected(<n>)=['<s>']
- 20048	got=[] expected=['<s>']
- 15532	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>']
- 14072	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>']
- 13732	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']

### sqlite
- 13	OperationalError: no such table: t1
- 3	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 1	OperationalError: integer overflow
- 1	expected error, got success
- 1	OperationalError: no such trigger: t1r1
