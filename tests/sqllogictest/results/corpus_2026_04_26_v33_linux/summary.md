# v10 corpus run 2026-04-25 (5 leap targets + mainline sqlite baseline)

Files sampled per target: 335
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP | excl-SKIP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rust | 1451240 | 139 | 54 | 74968 | 1526401 | 95.08% | 99.99% |
| c | 1384319 | 55 | 2129 | 46584 | 1433087 | 96.60% | 99.84% |
| go | 1406287 | 132 | 29 | 56495 | 1462943 | 96.13% | 99.99% |
| zig | 1423475 | 364 | 62 | 59240 | 1483141 | 95.98% | 99.97% |
| python | 856314 | 120 | 35 | 64732 | 921201 | 92.96% | 99.98% |
| sqlite | 1397798 | 19 | 0 | 80389 | 1478206 | 94.56% | 100.00% |

## Top 10 DEFER reasons per target

### rust
- 12	statement: unsupported leading kw "<s>"
- 11	parse: <pos> deferred: TRIGGER
- 6	parse: <pos> deferred: blob literal
- 6	compile: unknown table: t1 (schema is for )
- 4	parse: <pos> unexpected token after SELECT statement
- 4	compile: deferred: subquery with JOIN / derived FROM
- 3	compile: deferred: qualified column ref `cor1.col2` in SELECT
- 2	compile: deferred: qualified column ref `cor1.col1` in SELECT
- 1	compile: deferred: qualified column ref `tab1.col1` in SELECT
- 1	compile: deferred: qualified column ref `cor0.col0` in SELECT

### c
- 2088	compile: unknown table qualifier in column: .col4
- 11	statement: unsupported leading kw UPDATE
- 10	parse: <pos> unexpected token after SELECT statement
- 6	parse: <pos> deferred: blob literal
- 6	compile: unknown table: t1 (schema is for )
- 4	compile: deferred: subquery with JOIN / derived FROM
- 2	statement: unsupported leading kw CREATE
- 2	statement: unsupported leading kw REPLACE

### go
- 13	statement: unsupported leading kw "<s>"
- 6	parse: parse error at token <n> (line <n> col <n>): deferred: blob literal
- 6	compile: unknown table: t1 (schema is for )
- 4	parse: parse error at token <n> (line <n> col <n>): unexpected token after SELECT statement

### zig
- 17	compile: deferred: GROUP BY: HAVING across JOIN
- 11	statement: unsupported leading kw UPDATE
- 11	compile: deferred: GROUP BY across JOIN: bare nongroup column in projection
- 6	parse: <pos> deferred: blob literal
- 6	compile: unknown table: t1
- 4	compile: deferred: subquery with JOIN
- 3	compile: deferred: LEFT JOIN (NULL-fill)
- 2	parse: <pos> deferred: TEMP VIEW
- 2	statement: unsupported leading kw REPLACE

### python
- 10	parse: unexpected token after SELECT statement
- 6	parse: deferred: blob literal
- 6	compile: unknown column: x
- 5	compile: unknown table qualifier: cor1
- 3	compile: unknown table qualifier: cor0
- 2	parse: expected INSERT at start of statement
- 2	compile: unknown table qualifier: tab1
- 1	compile: inner SELECT halted: IO_ERROR

### sqlite


## Top 10 FAIL reasons per target

### rust
- 25	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 20	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 15	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>...
- 15	got(<n>)=["<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>"]
- 15	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>"]
- 15	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=[]
- 10	expected error, got success
- 7	schema: unknown table "<s>"
- 6	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>", "<s>"]
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
- 9	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 8	expected error, got success
- 5	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"]
- 5	schema: unknown table "<s>"
- 4	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 4	hash mismatch: count got=<n> expected=<n>, md5 got=62634e04a17da0e006feac1d867155ac expected=199eb36995ce9cc025eb667a27b...
- 3	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 2	hash mismatch: count got=<n> expected=<n>, md5 got=065d6be443fa55b97068841e27711050 expected=1ec49f6791dd184fda345e1c050...
- 2	hash mismatch: count got=<n> expected=<n>, md5 got=e8106031aa55a1e8b8551e82e1c8bfc2 expected=052bee12f2a7a847ddd0a7089ac...

### zig
- 118	got(<n>) expected(<n>) first got=<n> expected=<n>
- 70	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 33	got(<n>) expected(<n>) first got=<n> expected=<none>
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=9b9dc907b8bbf7a4545c9bdd30e27595 expected=e20b902b49a98b1a05ed62804c7...
- 10	got(<n>) expected(<n>) first got=NULL expected=NULL
- 8	expected error, got success
- 7	hash mismatch: count got=<n> expected=<n>, md5 got=03f4e4951d62660f736d7216e13f5abd expected=463a8481a3c42a48764d017d9e1...
- 5	schema: unknown table t1
- 4	hash mismatch: count got=<n> expected=<n>, md5 got=62634e04a17da0e006feac1d867155ac expected=199eb36995ce9cc025eb667a27b...
- 3	hash mismatch: count got=<n> expected=<n>, md5 got=3a79424e88fb7d017ad104ec105fb325 expected=463a8481a3c42a48764d017d9e1...

### python
- 24	got(<n>)=['<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>']
- 21	runtime: TypeError: string indices must be integers
- 17	expected error, got success
- 11	got(<n>)=['<s>', '<s>'] expected(<n>)=['<s>', '<s>']
- 8	runtime: UnboundLocalError: local variable '<s>' referenced before assignment
- 7	runtime: TypeError: '<s>' object is not callable
- 5	schema: "<s>"
- 5	runtime: AttributeError: '<s>' object has no attribute '<s>'
- 5	runtime: TypeError: '<s>' object is not subscriptable
- 3	got(<n>)=['<s>'] expected(<n>)=['<s>']

### sqlite
- 13	OperationalError: no such table: t1
- 3	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 1	OperationalError: integer overflow
- 1	expected error, got success
- 1	OperationalError: no such trigger: t1r1
