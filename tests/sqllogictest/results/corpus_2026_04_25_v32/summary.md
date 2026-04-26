# v10 corpus run 2026-04-25 (5 leap targets + mainline sqlite baseline)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP | excl-SKIP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rust | 1619257 | 169 | 65 | 123255 | 1742746 | 92.91% | 99.99% |
| c | 1519963 | 60 | 42 | 83252 | 1603317 | 94.80% | 99.99% |
| go | 1524072 | 327 | 30 | 83699 | 1608128 | 94.77% | 99.98% |
| zig | 1577990 | 1068 | 87 | 93256 | 1672401 | 94.35% | 99.93% |
| python | 1650617 | 96 | 46 | 134851 | 1785610 | 92.44% | 99.99% |
| sqlite | 1655199 | 19 | 0 | 134851 | 1790069 | 92.47% | 100.00% |

## Top 10 DEFER reasons per target

### rust
- 12	statement: unsupported leading kw "<s>"
- 11	parse: <pos> deferred: TRIGGER
- 6	parse: <pos> deferred: blob literal
- 6	compile: unknown table: t1 (schema is for )
- 4	parse: <pos> unexpected token after SELECT statement
- 4	compile: deferred: subquery with JOIN / derived FROM
- 4	compile: deferred: qualified column ref `cor0.col2` in SELECT
- 4	compile: deferred: qualified column ref `cor1.col2` in SELECT
- 3	compile: deferred: qualified column ref `cor0.col1` in SELECT
- 3	compile: deferred: qualified column ref `cor1.col1` in SELECT

### c
- 11	statement: unsupported leading kw UPDATE
- 10	parse: <pos> unexpected token after SELECT statement
- 6	parse: <pos> deferred: blob literal
- 6	compile: unknown table: t1 (schema is for )
- 4	compile: deferred: subquery with JOIN / derived FROM
- 2	statement: unsupported leading kw CREATE
- 2	statement: unsupported leading kw REPLACE
- 1	compile: deferred: LEFT JOIN with aggregation

### go
- 13	statement: unsupported leading kw "<s>"
- 6	parse: parse error at token <n> (line <n> col <n>): deferred: blob literal
- 6	compile: unknown table: t1 (schema is for )
- 4	parse: parse error at token <n> (line <n> col <n>): unexpected token after SELECT statement
- 1	compile: deferred: LEFT JOIN with aggregation

### zig
- 26	compile: deferred: GROUP BY: HAVING across JOIN
- 22	compile: deferred: GROUP BY across JOIN: bare nongroup column in projection
- 11	statement: unsupported leading kw UPDATE
- 8	compile: deferred: LEFT JOIN (NULL-fill)
- 6	parse: <pos> deferred: blob literal
- 6	compile: unknown table: t1
- 4	compile: deferred: subquery with JOIN
- 2	parse: <pos> deferred: TEMP VIEW
- 2	statement: unsupported leading kw REPLACE

### python
- 10	parse: unexpected token after SELECT statement
- 9	compile: unknown table qualifier: cor0
- 8	compile: unknown table qualifier: cor1
- 6	parse: deferred: blob literal
- 6	compile: unknown column: x
- 3	compile: unknown table qualifier: tab1
- 2	parse: expected INSERT at start of statement
- 1	compile: unknown table qualifier: tab0
- 1	compile: unknown table qualifier: tab2

### sqlite


## Top 10 FAIL reasons per target

### rust
- 40	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 25	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 16	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>", "<s>"]
- 15	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>...
- 15	got(<n>)=["<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>"]
- 15	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>"]
- 15	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=[]
- 10	expected error, got success
- 7	schema: unknown table "<s>"
- 3	got(<n>)=["<s>"] expected(<n>)=["<s>"]

### c
- 8	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 8	expected error, got success
- 6	row count mismatch: <n> cells vs expected <n>
- 5	schema: unknown table t1
- 4	hash mismatch: count got=<n> expected=<n>, md5 got=9e2d6381b04ea314cd79c5fc9325b30e expected=2c390d67360189455801dde3eab...
- 3	got(<n>) expected(<n>): cell <n> got=NULL expected=<n>
- 3	got(<n>) expected(<n>): cell <n> got=-<n>.<n> expected=-<n>.<n>
- 1	hash mismatch: count got=<n> expected=<n>, md5 got=894a42989161252fe16d473856061256 expected=2a20cfe00170362fbce52cfe093...
- 1	hash mismatch: count got=<n> expected=<n>, md5 got=45094f034fb71e47fd233021f266f7f1 expected=76e5018cbc30cd20144c127779c...
- 1	hash mismatch: count got=<n> expected=<n>, md5 got=6adb7939f513a490aa0ae08b0b7bdb53 expected=55e9888ae6ebbdb592c80dceb12...

### go
- 12	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 12	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 8	expected error, got success
- 5	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"]
- 5	schema: unknown table "<s>"
- 4	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 4	hash mismatch: count got=<n> expected=<n>, md5 got=62634e04a17da0e006feac1d867155ac expected=199eb36995ce9cc025eb667a27b...
- 3	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 3	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 3	hash mismatch: count got=<n> expected=<n>, md5 got=7ea04cf8ee35c59591700ea9b7fc1935 expected=d489341cd587fd6eb0b972c5464...

### zig
- 266	got(<n>) expected(<n>) first got=<n> expected=<n>
- 197	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 77	got(<n>) expected(<n>) first got=<n> expected=<none>
- 32	got(<n>) expected(<n>) first got=NULL expected=NULL
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=ee8448c7847a9e359e92bfd7e4bd0bb2 expected=463a8481a3c42a48764d017d9e1...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=4c560bb9510468fdc7ef8be2e18f2707 expected=463a8481a3c42a48764d017d9e1...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=b30850cca7d9b85d3f8dbcb184de14e2 expected=73719e959c2a2fe1cfe419b4519...
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=9af68e7302129f578cf6dd846d7eebdb expected=7aa228701de8d21263c44e16030...
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=5b2fb31db2a07475cba11951c2abbd42 expected=7aa228701de8d21263c44e16030...
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=c3c066ca0b729815845cd2b7e298cf55 expected=7aa228701de8d21263c44e16030...

### python
- 47	got(<n>)=['<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>']
- 22	got(<n>)=['<s>', '<s>'] expected(<n>)=['<s>', '<s>']
- 17	expected error, got success
- 5	schema: "<s>"
- 3	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 1	got(<n>)=['<s>'] expected(<n>)=[]
- 1	got(<n>)=['<s>', '<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>', '<s>']

### sqlite
- 13	OperationalError: no such table: t1
- 3	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 1	OperationalError: integer overflow
- 1	expected error, got success
- 1	OperationalError: no such trigger: t1r1
