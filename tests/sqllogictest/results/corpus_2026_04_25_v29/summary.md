# v10 corpus run 2026-04-25 (5 leap targets + mainline sqlite baseline)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP | excl-SKIP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rust | 1619133 | 274 | 84 | 123255 | 1742746 | 92.91% | 99.98% |
| c | 1486416 | 116 | 222 | 83247 | 1570001 | 94.68% | 99.98% |
| go | 1511485 | 558 | 12386 | 83699 | 1608128 | 93.99% | 99.15% |
| zig | 1577098 | 1530 | 517 | 93256 | 1672401 | 94.30% | 99.87% |
| python | 1650601 | 92 | 66 | 134851 | 1785610 | 92.44% | 99.99% |
| sqlite | 1655199 | 19 | 0 | 134851 | 1790069 | 92.47% | 100.00% |

## Top 10 DEFER reasons per target

### rust
- 25	statement: unsupported leading kw "<s>"
- 11	parse: <pos> deferred: TRIGGER
- 10	parse: <pos> unexpected token after SELECT statement
- 6	parse: <pos> deferred: blob literal
- 6	compile: unknown table: t1 (schema is for )
- 4	compile: deferred: subquery with JOIN / derived FROM
- 4	compile: deferred: qualified column ref `cor0.col2` in SELECT
- 4	compile: deferred: qualified column ref `cor1.col2` in SELECT
- 3	compile: deferred: qualified column ref `cor0.col1` in SELECT
- 3	compile: deferred: qualified column ref `cor1.col1` in SELECT

### c
- 144	compile: deferred: subquery in non-SELECT context
- 33	compile: deferred: star in aggregate query
- 11	statement: unsupported leading kw UPDATE
- 10	parse: <pos> unexpected token after SELECT statement
- 6	parse: <pos> deferred: blob literal
- 6	compile: deferred: function call total_distinct
- 6	compile: unknown table: t1 (schema is for )
- 2	statement: unsupported leading kw CREATE
- 2	statement: unsupported leading kw REPLACE
- 1	compile: deferred: function call group_concat_distinct

### go
- 144	compile: deferred: IN subquery
- 13	statement: unsupported leading kw "<s>"
- 6	parse: parse error at token <n> (line <n> col <n>): deferred: blob literal
- 6	compile: deferred: function call total_distinct
- 6	compile: unknown table: t1 (schema is for )
- 4	compile: deferred: function call group_concat_distinct
- 4	parse: parse error at token <n> (line <n> col <n>): unexpected token after SELECT statement
- 2	compile: view `view_1_tab0_153`: parse: expected SELECT at start of statement
- 2	compile: view `view_1_tab1_153`: parse: expected SELECT at start of statement
- 2	compile: view `view_1_tab2_153`: parse: expected SELECT at start of statement

### zig
- 239	compile: deferred: DISTINCT/ORDER BY across JOIN aggregate
- 140	compile: deferred: IN subquery
- 41	compile: deferred: star projection in aggregate query
- 26	compile: deferred: GROUP BY: HAVING across JOIN
- 22	compile: deferred: GROUP BY across JOIN: bare nongroup column in projection
- 11	statement: unsupported leading kw UPDATE
- 8	compile: deferred: LEFT JOIN (NULL-fill)
- 6	parse: <pos> deferred: blob literal
- 6	compile: deferred: function call total_distinct
- 6	compile: unknown table: t1

### python
- 13	statement: unsupported leading kw '<s>'
- 9	compile: unknown table qualifier: cor0
- 8	compile: unknown table qualifier: cor1
- 7	parse: unexpected token after SELECT statement
- 6	parse: deferred: blob literal
- 6	parse: deferred: DISTINCT in total() unsupported
- 6	compile: unknown column: x
- 4	parse: deferred: DISTINCT in group_concat() unsupported
- 3	compile: unknown table qualifier: tab1
- 2	parse: expected INSERT at start of statement

### sqlite


## Top 10 FAIL reasons per target

### rust
- 61	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 40	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 28	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 27	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=[]
- 21	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>...
- 16	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>", "<s>"]
- 15	got(<n>)=["<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>"]
- 15	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>"]
- 10	expected error, got success
- 5	schema: unknown table "<s>"

### c
- 57	execute: halt rc=<n>
- 8	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 8	expected error, got success
- 6	row count mismatch: <n> cells vs expected <n>
- 5	schema: unknown table t1
- 4	hash mismatch: count got=<n> expected=<n>, md5 got=9e2d6381b04ea314cd79c5fc9325b30e expected=2c390d67360189455801dde3eab...
- 3	got(<n>) expected(<n>): cell <n> got=NULL expected=<n>
- 2	got(<n>) expected(<n>): cell <n> got=-<n>.<n> expected=-<n>.<n>
- 1	hash mismatch: count got=<n> expected=<n>, md5 got=894a42989161252fe16d473856061256 expected=2a20cfe00170362fbce52cfe093...
- 1	hash mismatch: count got=<n> expected=<n>, md5 got=45094f034fb71e47fd233021f266f7f1 expected=76e5018cbc30cd20144c127779c...

### go
- 195	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 16	got(<n>)=["<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 14	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 12	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 11	got(<n>)=["<s>" "<s>"] expected(<n>)=["<s>" "<s>"]
- 8	expected error, got success
- 6	got(<n>)=["<s>"] expected(<n>)=["<s>" "<s>"]
- 5	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"]
- 5	schema: unknown table "<s>"
- 4	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]

### zig
- 470	got(<n>) expected(<n>) first got=<n> expected=<n>
- 304	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 77	got(<n>) expected(<n>) first got=<n> expected=<none>
- 54	got(<n>) expected(<n>) first got=<n> expected=NULL
- 47	got(<n>) expected(<n>) first got=-<n> expected=<n>
- 44	got(<n>) expected(<n>) first got=<n> expected=-<n>
- 32	got(<n>) expected(<n>) first got=NULL expected=NULL
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
