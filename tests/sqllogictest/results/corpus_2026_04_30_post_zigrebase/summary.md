# full corpus run 2026-04-28 (6 targets)

Files per target: 622 (FULL upstream corpus)
Per-file timeout: 90s
Wall clock: 5267s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP | excl-SKIP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rust | 5935956 | 1378 | 59 | 1480839 | 7418232 | 80.02% | 99.98% |
| c | 5935363 | 1764 | 64 | 1480839 | 7418030 | 80.01% | 99.97% |
| go | 5929882 | 4653 | 46 | 1480839 | 7415420 | 79.97% | 99.92% |
| zig | 5870897 | 65998 | 298 | 1480839 | 7418032 | 79.14% | 98.88% |
| python | 5860466 | 1134 | 57 | 1480626 | 7342283 | 79.82% | 99.98% |
| sqlite | 5939855 | 19 | 0 | 1480839 | 7420713 | 80.04% | 100.00% |

## Top 10 DEFER reasons per target

### rust
- 6	compile: unknown table: t1 (schema is for )
- 6	parse: <pos> deferred: blob literal
- 6	compile: deferred: qualified column ref `cor0.col2` in SELECT
- 6	compile: deferred: qualified column ref `cor1.col2` in SELECT
- 5	compile: deferred: qualified column ref `cor0.col1` in SELECT
- 4	parse: <pos> deferred: implicit BEFORE
- 4	parse: <pos> unexpected token after SELECT statement
- 4	compile: deferred: subquery with JOIN / derived FROM
- 4	compile: deferred: qualified column ref `cor0.col0` in SELECT
- 4	compile: deferred: qualified column ref `cor1.col1` in SELECT

### c
- 17	compile: deferred: LEFT JOIN with aggregation
- 11	statement: unsupported leading kw UPDATE
- 10	parse: <pos> unexpected token after SELECT statement
- 6	parse: <pos> deferred: blob literal
- 6	compile: unknown table: t1 (schema is for )
- 6	compile: deferred: LEFT JOIN in <n>-or-more-way JOIN
- 4	compile: deferred: subquery with JOIN / derived FROM
- 2	statement: unsupported leading kw CREATE
- 2	statement: unsupported leading kw REPLACE

### go
- 17	compile: deferred: LEFT JOIN with aggregation
- 13	statement: unsupported leading kw "<s>"
- 6	parse: parse error at token <n> (line <n> col <n>): deferred: blob literal
- 6	compile: unknown table: t1 (schema is for )
- 4	parse: parse error at token <n> (line <n> col <n>): unexpected token after SELECT statement

### zig
- 192	compile: deferred: LEFT JOIN (NULL-fill)
- 42	compile: deferred: GROUP BY: HAVING across JOIN
- 33	compile: deferred: GROUP BY across JOIN: bare nongroup column in projection
- 11	statement: unsupported leading kw UPDATE
- 6	parse: <pos> deferred: blob literal
- 6	compile: unknown table: t1
- 4	compile: deferred: subquery with JOIN
- 2	parse: <pos> deferred: TEMP VIEW
- 2	statement: unsupported leading kw REPLACE

### python
- 15	compile: unknown table qualifier: cor0
- 12	compile: unknown table qualifier: cor1
- 10	parse: unexpected token after SELECT statement
- 6	parse: deferred: blob literal
- 6	compile: unknown column: x
- 3	compile: unknown table qualifier: tab1
- 2	parse: expected INSERT at start of statement
- 2	compile: unknown table qualifier: tab0
- 1	compile: unknown table qualifier: tab2

### sqlite


## Top 10 FAIL reasons per target

### rust
- 844	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 240	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>", "<s>"]
- 25	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 25	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>...
- 15	got(<n>)=["<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>"]
- 15	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=[]
- 15	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>"]
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=95d4a78f7ccd01072a43f92c4924a03e expected=4d46c183dacbc681067c5316ef8...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=f37a6c5db39c26b345349fd3452922e4 expected=1a5c5ea02f9c7bb1e940e0d19bc...
- 10	expected error, got success

### c
- 363	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 219	got(<n>) expected(<n>): cell <n> got=-<n> expected=<n>
- 212	got(<n>) expected(<n>): cell <n> got=<n> expected=-<n>
- 124	got(<n>) expected(<n>): cell <n> got=-<n> expected=-<n>
- 70	got(<n>) expected(<n>): cell <n> got=NULL expected=<n>
- 61	hash mismatch: count got=<n> expected=<n>, md5 got=c917b25091231466bcbe9d6f6c15d6df expected=5bb238574bac123f8ef67bf47cf...
- 56	got(<n>) expected(<n>): cell <n> got=NULL expected=-<n>
- 34	got(<n>) expected(<n>): cell <n> got=<n> expected=NULL
- 20	hash mismatch: count got=<n> expected=<n>, md5 got=105e3a9db3376ca1122fb2c7d531d866 expected=e9b65d555326d2ed7db72f3ee99...
- 20	got(<n>) expected(<n>): cell <n> got=-<n> expected=NULL

### go
- 844	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 240	got(<n>)=["<s>" "<s>"] expected(<n>)=["<s>" "<s>"]
- 16	hash mismatch: count got=<n> expected=<n>, md5 got=ba3cd48960e5f683e288965bfb3375db expected=ea0f747588ddf5869ee18a5e22d...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=ee4aca8f7f838077c4b33ff5f202423a expected=375f372843089b03f23b0016000...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=459c515c05949a33567600b490e587ce expected=a8481bfbfcb330825976c5896e5...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=091c8f3a632a022f8a4f6f024cae1e43 expected=909b7ebab62aff8f69dc42ccbb5...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=637c0bbd99f666a203b63ea77b002b0d expected=db9b93cf4fdd5de4106f0487a66...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=22e34c8b81b6403658a4f186d0f36232 expected=980274175fafec015a830806724...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=f6d46761d72990776fd788ec6549b791 expected=d41be7437523f0dba2158c7f043...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=986162d2baf66149fa3f50846cd59ae3 expected=3b4587ab6c08d2179c6df094d2f...

### zig
- 33848	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 23615	got(<n>) expected(<n>) first got=<n> expected=<n>
- 4857	got(<n>) expected(<n>) first got=NULL expected=NULL
- 37	got(<n>) expected(<n>) first got=<n> expected=<none>
- 16	hash mismatch: count got=<n> expected=<n>, md5 got=ba3cd48960e5f683e288965bfb3375db expected=ea0f747588ddf5869ee18a5e22d...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=95d4a78f7ccd01072a43f92c4924a03e expected=4d46c183dacbc681067c5316ef8...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=f37a6c5db39c26b345349fd3452922e4 expected=1a5c5ea02f9c7bb1e940e0d19bc...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=459c515c05949a33567600b490e587ce expected=a8481bfbfcb330825976c5896e5...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=091c8f3a632a022f8a4f6f024cae1e43 expected=909b7ebab62aff8f69dc42ccbb5...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=637c0bbd99f666a203b63ea77b002b0d expected=db9b93cf4fdd5de4106f0487a66...

### python
- 844	got(<n>)=['<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>']
- 240	got(<n>)=['<s>', '<s>'] expected(<n>)=['<s>', '<s>']
- 20	runtime: RecursionError: maximum recursion depth exceeded while calling a Python object
- 17	expected error, got success
- 5	schema: "<s>"
- 4	got(<n>)=['<s>', '<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>', '<s>']
- 3	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 1	got(<n>)=['<s>'] expected(<n>)=[]

### sqlite
- 13	OperationalError: no such table: t1
- 3	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 1	OperationalError: integer overflow
- 1	expected error, got success
- 1	OperationalError: no such trigger: t1r1
