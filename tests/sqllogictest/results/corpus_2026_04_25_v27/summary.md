# v10 corpus run 2026-04-25 (5 leap targets + mainline sqlite baseline)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP | excl-SKIP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rust | 1557168 | 167 | 718 | 88464 | 1646517 | 94.57% | 99.94% |
| c | 1485116 | 139 | 606 | 83229 | 1569090 | 94.65% | 99.95% |
| go | 1510926 | 857 | 12646 | 83699 | 1608128 | 93.96% | 99.11% |
| zig | 1576594 | 1437 | 1114 | 93256 | 1672401 | 94.27% | 99.84% |
| python | 1649870 | 92 | 797 | 134851 | 1785610 | 92.40% | 99.95% |
| sqlite | 1655199 | 19 | 0 | 134851 | 1790069 | 92.47% | 100.00% |

## Top 10 DEFER reasons per target

### rust
- 256	compile: deferred: DISTINCT across JOIN sources
- 197	parse: <pos> deferred: parenthesized table-ref / subquery in FROM
- 74	compile: deferred: IN subquery
- 70	parse: <pos> expected '<s>' after IN
- 41	compile: deferred: star projection in aggregate query
- 25	statement: unsupported leading kw "<s>"
- 11	parse: <pos> deferred: TRIGGER
- 10	parse: <pos> unexpected token after SELECT statement
- 6	parse: <pos> deferred: blob literal
- 6	compile: unknown table: t1 (schema is for )

### c
- 197	parse: <pos> deferred: parenthesized table-ref
- 188	compile: deferred: <n>-or-more-way JOIN with aggregation
- 74	compile: deferred: subquery in non-SELECT context
- 70	parse: <pos> expected '<s>' after IN
- 31	compile: deferred: star in aggregate query
- 11	statement: unsupported leading kw UPDATE
- 10	parse: <pos> unexpected token after SELECT statement
- 6	parse: <pos> deferred: blob literal
- 6	compile: deferred: function call total_distinct
- 6	compile: unknown table: t1 (schema is for )

### go
- 197	parse: parse error at token <n> (line <n> col <n>): deferred: parenthesized table-ref / subquery in FROM
- 74	compile: deferred: unknown expression node
- 70	parse: parse error at token <n> (line <n> col <n>): expected '<s>' after IN
- 39	compile: deferred: star projection in aggregate query
- 24	compile: deferred: Col
- 13	statement: unsupported leading kw "<s>"
- 6	parse: parse error at token <n> (line <n> col <n>): deferred: blob literal
- 6	compile: deferred: function call total_distinct
- 6	compile: unknown table: t1 (schema is for )
- 4	compile: deferred: function call group_concat_distinct

### zig
- 353	compile: deferred: DISTINCT * across self-joined sources
- 216	compile: deferred: DISTINCT/ORDER BY across JOIN aggregate
- 197	parse: <pos> expected table name
- 140	compile: deferred: IN subquery
- 70	parse: <pos> expected '<s>' after IN
- 41	compile: deferred: star projection in aggregate query
- 26	compile: deferred: GROUP BY: HAVING across JOIN
- 22	compile: deferred: GROUP BY across JOIN: bare nongroup column in projection
- 11	statement: unsupported leading kw UPDATE
- 8	compile: deferred: LEFT JOIN (NULL-fill)

### python
- 426	compile: deferred: <n>-or-more-way JOIN with aggregation
- 197	parse: expected SELECT after '<s>' in FROM (parenthesized JOIN deferred)
- 70	parse: expected '<s>' after IN
- 41	compile: deferred: star projection in aggregate query
- 13	statement: unsupported leading kw '<s>'
- 8	compile: unknown table qualifier: cor1
- 7	parse: unexpected token after SELECT statement
- 7	compile: unknown table qualifier: cor0
- 6	parse: deferred: blob literal
- 6	parse: deferred: DISTINCT in total() unsupported

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
- 80	execute: halt rc=<n>
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
- 304	execute: CursorClosed
- 195	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 16	got(<n>)=["<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 14	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 11	got(<n>)=["<s>" "<s>"] expected(<n>)=["<s>" "<s>"]
- 10	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 8	expected error, got success
- 6	got(<n>)=["<s>"] expected(<n>)=["<s>" "<s>"]
- 5	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"]
- 5	schema: unknown table "<s>"

### zig
- 470	got(<n>) expected(<n>) first got=<n> expected=<n>
- 304	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 77	got(<n>) expected(<n>) first got=<n> expected=<none>
- 47	got(<n>) expected(<n>) first got=-<n> expected=<n>
- 44	got(<n>) expected(<n>) first got=<n> expected=-<n>
- 32	got(<n>) expected(<n>) first got=NULL expected=NULL
- 28	got(<n>) expected(<n>) first got=<n> expected=NULL
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=ee8448c7847a9e359e92bfd7e4bd0bb2 expected=463a8481a3c42a48764d017d9e1...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=4c560bb9510468fdc7ef8be2e18f2707 expected=463a8481a3c42a48764d017d9e1...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=b30850cca7d9b85d3f8dbcb184de14e2 expected=73719e959c2a2fe1cfe419b4519...

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
