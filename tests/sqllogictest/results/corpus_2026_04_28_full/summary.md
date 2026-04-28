# full corpus run 2026-04-28 (6 targets)

Files per target: 622 (FULL upstream corpus)
Per-file timeout: 60s
Wall clock: 4210s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP | excl-SKIP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rust | 5424607 | 878 | 76 | 1207295 | 6632856 | 81.78% | 99.98% |
| c | 4105212 | 672 | 17549 | 600079 | 4723512 | 86.91% | 99.56% |
| go | 4672160 | 3562 | 45 | 808851 | 5484618 | 85.19% | 99.92% |
| zig | 4803848 | 8121 | 298 | 857565 | 5669832 | 84.73% | 99.83% |
| python | 5683224 | 1128 | 58 | 1473859 | 7158269 | 79.39% | 99.98% |
| sqlite | 5932125 | 19 | 0 | 1480839 | 7412983 | 80.02% | 100.00% |

## Top 10 DEFER reasons per target

### rust
- 12	statement: unsupported leading kw "<s>"
- 11	parse: <pos> deferred: TRIGGER
- 6	compile: unknown table: t1 (schema is for )
- 6	parse: <pos> deferred: blob literal
- 6	compile: deferred: qualified column ref `cor0.col2` in SELECT
- 6	compile: deferred: qualified column ref `cor1.col2` in SELECT
- 5	compile: deferred: qualified column ref `cor0.col1` in SELECT
- 4	parse: <pos> unexpected token after SELECT statement
- 4	compile: deferred: subquery with JOIN / derived FROM
- 4	compile: deferred: qualified column ref `cor0.col0` in SELECT

### c
- 8752	compile: unknown table qualifier in column: .col1
- 5114	compile: unknown table qualifier in column: .col2
- 1445	compile: unknown table qualifier in column: NUMERIC.col2
- 1029	compile: unknown table qualifier in column:
- 852	compile: unknown table qualifier in column:  a.col2
- 252	compile: unknown table qualifier in column:  .col2
- 12	compile: deferred: LEFT JOIN with aggregation
- 11	statement: unsupported leading kw UPDATE
- 10	parse: <pos> unexpected token after SELECT statement
- 10	compile: unknown table qualifier in column: .col2

### go
- 16	compile: deferred: LEFT JOIN with aggregation
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
- 1	parse: expected prefix expression
- 1	compile: unknown table qualifier: tab2

### sqlite


## Top 10 FAIL reasons per target

### rust
- 482	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 141	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>", "<s>"]
- 25	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 25	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>...
- 15	got(<n>)=["<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>"]
- 15	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=[]
- 15	got(<n>)=["<s>", "<s>"] expected(<n>)=["<s>"]
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=95d4a78f7ccd01072a43f92c4924a03e expected=4d46c183dacbc681067c5316ef8...
- 10	expected error, got success
- 10	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>"]

### c
- 61	hash mismatch: count got=<n> expected=<n>, md5 got=c917b25091231466bcbe9d6f6c15d6df expected=5bb238574bac123f8ef67bf47cf...
- 20	hash mismatch: count got=<n> expected=<n>, md5 got=105e3a9db3376ca1122fb2c7d531d866 expected=e9b65d555326d2ed7db72f3ee99...
- 16	row count mismatch: <n> cells vs expected <n>
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=1faf94eae6f28022efcfbcc20608d272 expected=f61a50f4418ed61fdc3ceed7404...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=92fa4b75947e0d94e3753a8450652afc expected=a123c81dc3204a05a931624cc0a...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=81749a0c2aed62ec5213873d546a706e expected=4c3a25bc538e204723e305bba7d...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=18e4ac0e036961f26312567546cf8afd expected=7089e47856a3e07d35773e88dad...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=e7b0e606f02105c7c5eb52117cb67086 expected=cc3b240eaaab5f7bb22e8467e0c...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=a58204d2e36b692114e90955800bffc0 expected=06715b2e774760af2c864d2796e...
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=2218fdeacee3a45ee4119db062cf9857 expected=24f365327ae48117a1ac4b8c482...

### go
- 16	hash mismatch: count got=<n> expected=<n>, md5 got=ba3cd48960e5f683e288965bfb3375db expected=ea0f747588ddf5869ee18a5e22d...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=ee4aca8f7f838077c4b33ff5f202423a expected=375f372843089b03f23b0016000...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=459c515c05949a33567600b490e587ce expected=a8481bfbfcb330825976c5896e5...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=091c8f3a632a022f8a4f6f024cae1e43 expected=909b7ebab62aff8f69dc42ccbb5...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=637c0bbd99f666a203b63ea77b002b0d expected=db9b93cf4fdd5de4106f0487a66...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=22e34c8b81b6403658a4f186d0f36232 expected=980274175fafec015a830806724...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=f6d46761d72990776fd788ec6549b791 expected=d41be7437523f0dba2158c7f043...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=986162d2baf66149fa3f50846cd59ae3 expected=3b4587ab6c08d2179c6df094d2f...
- 14	hash mismatch: count got=<n> expected=<n>, md5 got=2d9248b178b9248b76c7252d435aa723 expected=ee5129bae5293935ae558ebe952...
- 14	hash mismatch: count got=<n> expected=<n>, md5 got=16a5c6e54c30128c7df2eae4c60345ce expected=0fcd8d0934383dd58863be894b0...

### zig
- 2464	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 1545	got(<n>) expected(<n>) first got=<n> expected=<n>
- 411	got(<n>) expected(<n>) first got=NULL expected=NULL
- 43	got(<n>) expected(<n>) first got=<n> expected=<none>
- 16	hash mismatch: count got=<n> expected=<n>, md5 got=ba3cd48960e5f683e288965bfb3375db expected=ea0f747588ddf5869ee18a5e22d...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=95d4a78f7ccd01072a43f92c4924a03e expected=4d46c183dacbc681067c5316ef8...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=459c515c05949a33567600b490e587ce expected=a8481bfbfcb330825976c5896e5...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=091c8f3a632a022f8a4f6f024cae1e43 expected=909b7ebab62aff8f69dc42ccbb5...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=637c0bbd99f666a203b63ea77b002b0d expected=db9b93cf4fdd5de4106f0487a66...
- 15	hash mismatch: count got=<n> expected=<n>, md5 got=22e34c8b81b6403658a4f186d0f36232 expected=980274175fafec015a830806724...

### python
- 844	got(<n>)=['<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>']
- 240	got(<n>)=['<s>', '<s>'] expected(<n>)=['<s>', '<s>']
- 17	expected error, got success
- 5	schema: "<s>"
- 4	runtime: TypeError: string indices must be integers
- 4	got(<n>)=['<s>', '<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>', '<s>']
- 3	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 3	runtime: AttributeError: '<s>' object has no attribute '<s>'
- 2	runtime: TypeError: '<s>' object is not callable
- 1	got(<n>)=['<s>'] expected(<n>)=[]

### sqlite
- 13	OperationalError: no such table: t1
- 3	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 1	OperationalError: integer overflow
- 1	expected error, got success
- 1	OperationalError: no such trigger: t1r1
