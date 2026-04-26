# v10 corpus run 2026-04-25 (5 leap targets + mainline sqlite baseline)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP | excl-SKIP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rust | 1619208 | 218 | 65 | 123255 | 1742746 | 92.91% | 99.98% |
| c | 1493430 | 213 | 49 | 83252 | 1576944 | 94.70% | 99.98% |
| go | 1516457 | 610 | 7362 | 83699 | 1608128 | 94.30% | 99.48% |
| zig | 1577378 | 1530 | 237 | 93256 | 1672401 | 94.32% | 99.89% |
| python | 1650611 | 95 | 53 | 134851 | 1785610 | 92.44% | 99.99% |
| sqlite | 1655199 | 19 | 0 | 134851 | 1790069 | 92.47% | 100.00% |

## Top 10 DEFER reasons per target

### rust
- 12	statement: unsupported leading kw "<s>"
- 11	parse: <pos> deferred: TRIGGER
- 6	parse: <pos> deferred: blob literal
- 6	compile: unknown table: t1 (schema is for )
- 4	compile: deferred: subquery with JOIN / derived FROM
- 4	parse: <pos> unexpected token after SELECT statement
- 4	compile: deferred: qualified column ref `cor0.col2` in SELECT
- 4	compile: deferred: qualified column ref `cor1.col2` in SELECT
- 3	compile: deferred: qualified column ref `cor0.col1` in SELECT
- 3	compile: deferred: qualified column ref `cor1.col1` in SELECT

### c
- 11	statement: unsupported leading kw UPDATE
- 10	parse: <pos> unexpected token after SELECT statement
- 6	parse: <pos> deferred: blob literal
- 6	compile: deferred: function call total_distinct
- 6	compile: unknown table: t1 (schema is for )
- 4	compile: deferred: subquery with JOIN / derived FROM
- 2	statement: unsupported leading kw CREATE
- 2	statement: unsupported leading kw REPLACE
- 1	compile: deferred: function call group_concat_distinct
- 1	compile: deferred: LEFT JOIN with aggregation

### go
- 13	statement: unsupported leading kw "<s>"
- 6	parse: parse error at token <n> (line <n> col <n>): deferred: blob literal
- 6	compile: deferred: function call total_distinct
- 6	compile: unknown table: t1 (schema is for )
- 4	compile: deferred: function call group_concat_distinct
- 4	parse: parse error at token <n> (line <n> col <n>): unexpected token after SELECT statement
- 1	compile: unknown table: view1 (schema is for )
- 1	compile: unknown table: view2 (schema is for )
- 1	compile: unknown table: view_1_tab0_302 (schema is for )
- 1	compile: unknown table: view_2_tab0_302 (schema is for )

### zig
- 140	compile: deferred: IN subquery
- 26	compile: deferred: GROUP BY: HAVING across JOIN
- 22	compile: deferred: GROUP BY across JOIN: bare nongroup column in projection
- 11	statement: unsupported leading kw UPDATE
- 8	compile: deferred: LEFT JOIN (NULL-fill)
- 6	parse: <pos> deferred: blob literal
- 6	compile: deferred: function call total_distinct
- 6	compile: unknown table: t1
- 4	compile: deferred: subquery with JOIN
- 4	compile: deferred: function call group_concat_distinct

### python
- 9	compile: unknown table qualifier: cor0
- 8	compile: unknown table qualifier: cor1
- 7	parse: unexpected token after SELECT statement
- 6	parse: deferred: blob literal
- 6	parse: deferred: DISTINCT in total() unsupported
- 6	compile: unknown column: x
- 4	parse: deferred: DISTINCT in group_concat() unsupported
- 3	compile: unknown table qualifier: tab1
- 2	parse: expected INSERT at start of statement
- 1	compile: unknown table qualifier: tab0

### sqlite


## Top 10 FAIL reasons per target

### rust
- 40	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 28	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 27	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=[]
- 21	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>...
- 16	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>", "<s>"]
- 15	got(<n>)=["<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>"]
- 15	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>"]
- 10	expected error, got success
- 7	schema: unknown table "<s>"
- 5	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>"]

### c
- 102	execute: halt rc=<n>
- 52	got(<n>) expected(<n>): cell <n> got=<n> expected=NULL
- 8	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 8	expected error, got success
- 6	row count mismatch: <n> cells vs expected <n>
- 5	schema: unknown table t1
- 4	hash mismatch: count got=<n> expected=<n>, md5 got=9e2d6381b04ea314cd79c5fc9325b30e expected=2c390d67360189455801dde3eab...
- 3	got(<n>) expected(<n>): cell <n> got=NULL expected=<n>
- 2	got(<n>) expected(<n>): cell <n> got=-<n>.<n> expected=-<n>.<n>
- 1	hash mismatch: count got=<n> expected=<n>, md5 got=894a42989161252fe16d473856061256 expected=2a20cfe00170362fbce52cfe093...

### go
- 195	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 66	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 16	got(<n>)=["<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
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
- 17	expected error, got success
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
