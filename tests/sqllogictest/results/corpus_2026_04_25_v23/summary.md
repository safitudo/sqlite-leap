# v10 corpus run 2026-04-25 (5 leap targets + mainline sqlite baseline)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP | excl-SKIP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rust | 1556175 | 160 | 1718 | 88464 | 1646517 | 94.51% | 99.88% |
| c | 1466235 | 64 | 2124 | 83229 | 1551652 | 94.50% | 99.85% |
| go | 1508795 | 632 | 15093 | 83741 | 1608261 | 93.82% | 98.97% |
| zig | 1569042 | 1928 | 20158 | 99916 | 1691044 | 92.79% | 98.61% |
| python | 1646966 | 92 | 3701 | 134851 | 1785610 | 92.24% | 99.77% |
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
- 552	compile: deferred: complex expression in JOIN context
- 197	parse: <pos> deferred: parenthesized table-ref
- 188	compile: deferred: <n>-or-more-way JOIN with aggregation
- 86	compile: unknown table: t2 (schema is for t1)
- 80	compile: unknown table: t6 (schema is for t1)
- 77	compile: unknown table: t4 (schema is for t1)
- 74	compile: deferred: subquery in non-SELECT context
- 72	compile: unknown table: t8 (schema is for t1)
- 72	compile: unknown table: t7 (schema is for t1)
- 70	parse: <pos> expected '<s>' after IN

### go
- 1879	compile: deferred α23: correlated subquery with aggregate / GROUP BY / compound
- 666	compile: deferred: unknown expression node
- 197	parse: parse error at token <n> (line <n> col <n>): deferred: parenthesized table-ref / subquery in FROM
- 70	parse: parse error at token <n> (line <n> col <n>): expected '<s>' after IN
- 39	compile: deferred: star projection in aggregate query
- 13	statement: unsupported leading kw "<s>"
- 6	parse: parse error at token <n> (line <n> col <n>): deferred: blob literal
- 6	compile: deferred: function call total_distinct
- 6	compile: unknown table: t1 (schema is for )
- 4	compile: deferred: function call group_concat_distinct

### zig
- 9854	compile: deferred: aggregate in scalar context
- 4880	compile: deferred: compound SELECT with CTE or derived FROM
- 3921	compile: deferred: DISTINCT/ORDER BY across JOIN
- 197	parse: <pos> expected table name
- 140	compile: deferred: IN subquery
- 86	compile: unknown table: t2 (schema is for t1)
- 80	compile: unknown table: t6 (schema is for t1)
- 77	compile: unknown table: t4 (schema is for t1)
- 72	compile: unknown table: t8 (schema is for t1)
- 72	compile: unknown table: t7 (schema is for t1)

### python
- 2351	compile: deferred: correlated subquery (Python pre-execute model)
- 553	compile: deferred: expression ExprCast across JOIN sources
- 426	compile: deferred: <n>-or-more-way JOIN with aggregation
- 197	parse: expected SELECT after '<s>' in FROM (parenthesized JOIN deferred)
- 70	parse: expected '<s>' after IN
- 41	compile: deferred: star projection in aggregate query
- 13	statement: unsupported leading kw '<s>'
- 8	compile: unknown table qualifier: cor1
- 7	parse: unexpected token after SELECT statement
- 7	compile: unknown table qualifier: cor0

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
- 10	execute: halt rc=<n>
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
- 710	got(<n>) expected(<n>) first got=<n> expected=<n>
- 630	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 81	got(<n>) expected(<n>) first got=NULL expected=NULL
- 75	got(<n>) expected(<n>) first got=<n> expected=<none>
- 47	got(<n>) expected(<n>) first got=-<n> expected=<n>
- 44	got(<n>) expected(<n>) first got=<n> expected=-<n>
- 26	got(<n>) expected(<n>) first got=<n> expected=NULL
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=9b9dc907b8bbf7a4545c9bdd30e27595 expected=e20b902b49a98b1a05ed62804c7...
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=37e36bb0203e720aa3eca2106c15b7d2 expected=39e3d4d27bae24c9e33e78b000c...
- 8	got(<n>) expected(<n>) first got=NULL expected=<n>

### python
- 47	got(<n>)=['<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>']
- 22	got(<n>)=['<s>', '<s>'] expected(<n>)=['<s>', '<s>']
- 14	expected error, got success
- 5	schema: "<s>"
- 2	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 1	got(<n>)=['<s>'] expected(<n>)=[]
- 1	got(<n>)=['<s>', '<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>', '<s>']

### sqlite
- 13	OperationalError: no such table: t1
- 3	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 1	OperationalError: integer overflow
- 1	expected error, got success
- 1	OperationalError: no such trigger: t1r1
