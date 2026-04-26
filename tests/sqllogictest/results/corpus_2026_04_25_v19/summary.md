# v10 corpus run 2026-04-25 (5 leap targets + mainline sqlite baseline)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP | excl-SKIP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rust | 1556175 | 160 | 1718 | 88464 | 1646517 | 94.51% | 99.88% |
| c | 1471483 | 74 | 4206 | 83229 | 1558992 | 94.39% | 99.71% |
| go | 1504995 | 379 | 19146 | 83741 | 1608261 | 93.58% | 98.72% |
| zig | 1496630 | 1513 | 92776 | 99785 | 1690704 | 88.52% | 94.07% |
| python | 986941 | 530582 | 137695 | 134851 | 1790069 | 55.13% | 59.63% |
| sqlite | 1655199 | 19 | 0 | 134851 | 1790069 | 92.47% | 100.00% |

## Top 10 DEFER reasons per target

### rust
- 256	compile: deferred: DISTINCT across JOIN sources
- 197	parse: <pos> deferred: parenthesized table-ref / subquery in FROM
- 89	compile: unknown table: t2 (schema is for t1)
- 85	compile: unknown table: t6 (schema is for t1)
- 80	compile: unknown table: t7 (schema is for t1)
- 79	compile: unknown table: t4 (schema is for t1)
- 74	compile: deferred: IN subquery
- 74	compile: unknown table: t8 (schema is for t1)
- 72	compile: unknown table: t3 (schema is for t1)
- 71	compile: unknown table: t9 (schema is for t1)

### c
- 1627	compile: ambiguous column: col0
- 552	compile: deferred: complex expression in JOIN context
- 455	compile: ambiguous column: pk
- 197	parse: <pos> deferred: parenthesized table-ref
- 188	compile: deferred: <n>-or-more-way JOIN with aggregation
- 86	compile: unknown table: t2 (schema is for t1)
- 80	compile: unknown table: t6 (schema is for t1)
- 77	compile: unknown table: t4 (schema is for t1)
- 74	compile: deferred: subquery in non-SELECT context
- 72	compile: unknown table: t8 (schema is for t1)

### go
- 2595	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 1879	compile: deferred α23: correlated subquery with aggregate / GROUP BY / compound
- 1146	compile: ambiguous column: col0
- 523	compile: deferred: unknown expression node
- 455	compile: ambiguous column: pk
- 197	parse: parse error at token <n> (line <n> col <n>): deferred: parenthesized table-ref / subquery in FROM
- 70	parse: parse error at token <n> (line <n> col <n>): expected '<s>' after IN
- 39	compile: deferred: star projection in aggregate query
- 13	statement: unsupported leading kw "<s>"
- 6	parse: parse error at token <n> (line <n> col <n>): deferred: blob literal

### zig
- 73169	compile: deferred: GROUP BY
- 4880	compile: deferred: compound SELECT with CTE or derived FROM
- 4372	compile: deferred: function call COUNT_star
- 2811	compile: deferred: DISTINCT/ORDER BY across JOIN
- 2622	compile: deferred: aggregate in scalar context
- 639	compile: deferred: function call COUNT
- 630	compile: deferred: function call MAX
- 620	compile: deferred: function call SUM
- 576	compile: deferred: function call MIN
- 226	compile: deferred: function call COUNT_distinct

### python
- 52785	compile: internal: unhandled Expr variant ExprInSubquery
- 48220	statement: unsupported leading kw '<s>'
- 3663	compile: unknown table in JOIN: tab2
- 3607	compile: unknown table in JOIN: tab0
- 3591	compile: unknown table in JOIN: tab1
- 3287	compile: INSERT from SELECT requires source schema
- 2440	compile: internal: unhandled TableRef TableRefSubquery
- 2139	compile: internal: unhandled Expr variant ExprSubquery
- 709	compile: internal: unhandled Expr variant ExprExists
- 591	compile: deferred: DISTINCT or ORDER BY across JOIN sources

### sqlite


## Top 10 FAIL reasons per target

### rust
- 28	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 27	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=[]
- 21	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>...
- 15	got(<n>)=["<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>"]
- 15	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>"]
- 10	expected error, got success
- 9	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 5	schema: unknown table "<s>"
- 5	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>"]
- 4	hash mismatch: count got=<n> expected=<n>, md5 got=9280c475ce2d1388246d2e490a7412b8 expected=d4ce8ba735d9acaa3b10b7b1a10...

### c
- 30	execute: halt rc=<n>
- 8	expected error, got success
- 8	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 6	row count mismatch: <n> cells vs expected <n>
- 5	schema: unknown table t1
- 4	hash mismatch: count got=<n> expected=<n>, md5 got=9e2d6381b04ea314cd79c5fc9325b30e expected=2c390d67360189455801dde3eab...
- 3	got(<n>) expected(<n>): cell <n> got=NULL expected=<n>
- 2	got(<n>) expected(<n>): cell <n> got=-<n>.<n> expected=-<n>.<n>
- 1	drop: no such view view2
- 1	drop: no such view view3

### go
- 195	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 91	execute: CursorClosed
- 16	got(<n>)=["<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 14	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 11	got(<n>)=["<s>" "<s>"] expected(<n>)=["<s>" "<s>"]
- 8	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 8	expected error, got success
- 6	got(<n>)=["<s>"] expected(<n>)=["<s>" "<s>"]
- 5	schema: unknown table "<s>"
- 4	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"]

### zig
- 520	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 505	got(<n>) expected(<n>) first got=<n> expected=<n>
- 80	got(<n>) expected(<n>) first got=NULL expected=NULL
- 75	got(<n>) expected(<n>) first got=<n> expected=<none>
- 26	got(<n>) expected(<n>) first got=<n> expected=NULL
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=9b9dc907b8bbf7a4545c9bdd30e27595 expected=e20b902b49a98b1a05ed62804c7...
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=37e36bb0203e720aa3eca2106c15b7d2 expected=39e3d4d27bae24c9e33e78b000c...
- 8	expected error, got success
- 5	schema: unknown table t1
- 5	hash mismatch: count got=<n> expected=<n>, md5 got=cf4abbed646a7db98f7cc570f6c36104 expected=934ccec0db7c5f1e61014e14d93...

### python
- 92554	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=e20b902b49a98b1a05ed62804c7...
- 32272	got(<n>)=[] expected(<n>)=['<s>', '<s>']
- 29324	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>']
- 28760	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 28644	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 26060	got(<n>)=[] expected(<n>)=['<s>']
- 15056	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>']
- 13492	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>']
- 13196	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 9424	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=9d3557642e57f7f03e636d9ae90...

### sqlite
- 13	OperationalError: no such table: t1
- 3	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 1	OperationalError: integer overflow
- 1	expected error, got success
- 1	OperationalError: no such trigger: t1r1
