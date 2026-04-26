# 5-target corpus run 2026-04-25 (post runner-format upgrade)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | PASS rate |
| --- | --- | --- | --- | --- | --- | --- |
| rust | 1485142 | 64718 | 8193 | 88464 | 1646517 | 90.20% |
| c | 1031124 | 461879 | 32122 | 90336 | 1615461 | 63.83% |
| go | 1016288 | 335591 | 22049 | 40355 | 1414283 | 71.86% |
| zig | 211239 | 91601 | 32933 | 17094 | 352867 | 59.86% |
| python | 961406 | 571418 | 122394 | 134851 | 1790069 | 53.71% |

## Top 10 DEFER reasons per target

### rust
- 3130	compile: deferred: compound SELECT with CTE or derived FROM
- 3036	compile: projection references column not in GROUP BY
- 309	compile: HAVING references column not in GROUP BY
- 256	compile: deferred: DISTINCT across JOIN sources
- 197	parse: <pos> deferred: parenthesized table-ref / subquery in FROM
- 89	compile: unknown table: t2 (schema is for t1)
- 85	compile: unknown table: t6 (schema is for t1)
- 80	compile: unknown table: t7 (schema is for t1)
- 79	compile: unknown table: t4 (schema is for t1)
- 74	compile: deferred: IN subquery

### c
- 7820	compile: deferred: unsupported expression kind in aggregate projection/HAVING
- 4361	compile: deferred: <n>-or-more-way JOIN
- 2854	compile: projection references column not in GROUP BY: col0
- 2803	compile: projection references column not in GROUP BY: col2
- 2743	compile: projection references column not in GROUP BY: col1
- 2606	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 2139	compile: deferred: scalar subquery
- 855	compile: deferred: function call MIN_distinct
- 809	compile: deferred: function call SUM_distinct
- 802	compile: deferred: function call MAX_distinct

### go
- 2860	compile: projection references column not in GROUP BY
- 2260	compile: deferred: <n>-or-more-way JOIN
- 1879	compile: deferred α23: correlated subquery with aggregate / GROUP BY / compound
- 583	parse: parse error at token <n> (line <n> col <n>): unexpected token after SELECT statement
- 327	compile: deferred: function call MIN_distinct
- 320	compile: ambiguous column: pk
- 282	compile: deferred: function call SUM_distinct
- 271	compile: deferred: function call MAX_distinct
- 262	compile: deferred: function call AVG_distinct
- 159	compile: deferred: unknown expression node

### zig
- 9381	compile: deferred: IN subquery
- 2671	compile: projection references column not in GROUP BY
- 1795	compile: deferred: scalar subquery
- 1782	compile: deferred: derived-table subquery in FROM
- 1630	compile: deferred: JOIN with aggregation
- 796	compile: deferred: mixed INTERSECT/EXCEPT/UNION in one compound SELECT
- 617	compile: deferred: EXISTS subquery
- 616	compile: unknown table in JOIN: tab1
- 612	compile: unknown table in JOIN: tab2
- 591	compile: unknown table in JOIN: tab0

### python
- 52785	compile: internal: unhandled Expr variant ExprInSubquery
- 10103	parse: expected prefix expression
- 8927	compile: projection references column not in GROUP BY
- 5795	compile: internal: unhandled Expr variant ExprCast
- 3638	compile: unknown table in JOIN: tab2
- 3581	compile: unknown table in JOIN: tab0
- 3566	compile: unknown table in JOIN: tab1
- 3287	compile: INSERT from SELECT requires source schema
- 2440	compile: internal: unhandled TableRef TableRefSubquery
- 2304	parse: deferred: DISTINCT in SUM() unsupported


## Top 10 FAIL reasons per target

### rust
- 28563	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=[]
- 5959	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 3503	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=[]
- 3461	got(<n>)=[] expected(<n>)=["<s>", "<s>", "<s>"]
- 2571	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 1596	got(<n>)=[] expected(<n>)=["<s>"]
- 1586	got(<n>)=["<s>"] expected(<n>)=[]
- 1130	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=b833e3a3ba082b2c0028b4cd08f...
- 670	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>"]
- 630	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=c6c0a4111b36d04dbc811a11e4d...

### c
- 335636	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 64462	got(<n>) expected(<n>): cell <n> got=-<n> expected=-<n>
- 39250	row count mismatch: <n> cells vs expected <n>
- 7873	got(<n>) expected(<n>): cell <n> got=<n> expected=NULL
- 1120	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=b833e3a3ba082b2c0028b4cd08f...
- 870	got(<n>) expected(<n>): cell <n> got=<n> expected=-<n>
- 629	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=c6c0a4111b36d04dbc811a11e4d...
- 619	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=75c998aa53ac83218cbf2feb962...
- 618	got(<n>) expected(<n>): cell <n> got=-<n> expected=<n>
- 538	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=c4b42765dff94eaaa46040e537f...

### go
- 47654	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 43432	got(<n>)=["<s>" "<s>"] expected(<n>)=["<s>" "<s>"]
- 38119	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 37787	got(<n>)=["<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>"]
- 37576	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>...
- 33455	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 25292	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 19411	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"]
- 17421	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 7325	execute: no such view "<s>"

### zig
- 68018	got(<n>) expected(<n>) first got=<n> expected=<n>
- 13171	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 3991	got(<n>) expected(<n>) first got=<n> expected=<none>
- 1535	got(<n>) expected(<n>) first got=<n> expected=NULL
- 1088	got(<n>) expected(<n>) first got=-<n> expected=<none>
- 555	got(<n>) expected(<n>) first got=<none> expected=<n>
- 330	got(<n>) expected(<n>) first got=<none> expected=-<n>
- 177	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=b833e3a3ba082b2c0028b4cd08f...
- 149	got(<n>) expected(<n>) first got=<n> expected=-<n>
- 86	got(<n>) expected(<n>) first got=-<n> expected=<n>

### python
- 92554	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=e20b902b49a98b1a05ed62804c7...
- 32619	got(<n>)=[] expected(<n>)=['<s>', '<s>']
- 29341	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>']
- 29046	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 28648	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 27805	got(<n>)=[] expected(<n>)=['<s>']
- 16905	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>']
- 15063	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>']
- 13202	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 9424	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=9d3557642e57f7f03e636d9ae90...
