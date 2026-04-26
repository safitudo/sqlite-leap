# 5-target corpus run 2026-04-25 (post runner-format upgrade)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | PASS rate |
| --- | --- | --- | --- | --- | --- | --- |
| rust | 1375331 | 169498 | 13224 | 88464 | 1646517 | 83.53% |
| c | 935265 | 554923 | 86598 | 90421 | 1667207 | 56.10% |
| go | 919217 | 425212 | 32845 | 42255 | 1419529 | 64.76% |
| zig | 22546 | 15346 | 8028 | 10 | 45930 | 49.09% |
| python | 1364187 | 194068 | 231471 | 8 | 1789734 | 76.22% |

## Top 10 DEFER reasons per target

### rust
- 3130	compile: deferred: compound SELECT with CTE or derived FROM
- 3043	compile: projection references column not in GROUP BY
- 1086	compile: aggregate without FROM is unsupported
- 996	compile: deferred: function call MIN_distinct
- 961	compile: deferred: function call SUM_distinct
- 960	compile: deferred: function call MAX_distinct
- 490	compile: non-aggregate column in projection of aggregate query
- 452	compile: deferred: function call AVG_distinct
- 346	compile: HAVING references column not in GROUP BY
- 272	compile: deferred: DISTINCT across JOIN sources

### c
- 52711	compile: deferred: IN subquery
- 7550	compile: deferred: unsupported expression kind in aggregate projection/HAVING
- 4361	compile: deferred: <n>-or-more-way JOIN
- 4112	compile: deferred: function call
- 2854	compile: projection references column not in GROUP BY: col0
- 2803	compile: projection references column not in GROUP BY: col2
- 2743	compile: projection references column not in GROUP BY: col1
- 2606	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 1760	compile: deferred: scalar subquery
- 706	compile: deferred: EXISTS subquery

### go
- 10760	compile: deferred: compound SELECT
- 2860	compile: projection references column not in GROUP BY
- 2440	compile: deferred: derived-table subquery in FROM
- 2260	compile: deferred: <n>-or-more-way JOIN
- 1701	compile: deferred α23: correlated subquery with aggregate / GROUP BY / compound
- 1553	compile: aggregate without FROM is unsupported
- 766	compile: deferred: function call avg
- 583	parse: parse error at token <n> (line <n> col <n>): unexpected token after SELECT statement
- 410	compile: deferred: unknown expression node
- 347	compile: deferred: function call MIN_distinct

### zig
- 2019	compile: deferred: IN subquery
- 1745	compile: deferred: scalar subquery
- 1000	compile: deferred: compound SELECT
- 589	compile: deferred: EXISTS subquery
- 229	compile: unknown table in JOIN: t2
- 227	compile: unknown table in JOIN: t4
- 214	compile: unknown table in JOIN: t9
- 204	compile: unknown table in JOIN: t8
- 200	compile: unknown table in JOIN: t5
- 193	compile: unknown table in JOIN: t6

### python
- 52711	compile: internal: unhandled Expr variant ExprInSubquery
- 47752	compile: aggregate without FROM is unsupported
- 26185	parse: unexpected token after SELECT statement
- 19318	parse: expected prefix expression
- 14655	statement: unsupported leading kw '<s>'
- 11266	compile: internal: unhandled Expr variant ExprCast
- 9126	compile: projection references column not in GROUP BY
- 4492	parse: deferred: DISTINCT in SUM() unsupported
- 4457	parse: deferred: DISTINCT in MIN() unsupported
- 4429	parse: deferred: DISTINCT in MAX() unsupported


## Top 10 FAIL reasons per target

### rust
- 28563	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=[]
- 12290	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 5479	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 3926	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>"]
- 3457	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=[]
- 3444	got(<n>)=[] expected(<n>)=["<s>", "<s>", "<s>"]
- 3166	got(<n>)=["<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>"]
- 2926	got(<n>)=["<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>"]
- 2617	got(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>", "<s>"] expected(<n>)=["<s>", "<s>", "<s>", "<s>", "<s>", "<s>...
- 2250	hash mismatch: count got=<n> expected=<n>, md5 got=2f8e5bef97f41cd641eafba46c99a49d expected=ee724f9f159f8cdef185b42c43b...

### c
- 339691	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 64350	got(<n>) expected(<n>): cell <n> got=-<n> expected=-<n>
- 39205	row count mismatch: <n> cells vs expected <n>
- 11780	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 7871	got(<n>) expected(<n>): cell <n> got=<n> expected=NULL
- 2200	hash mismatch: count got=<n> expected=<n>, md5 got=2f8e5bef97f41cd641eafba46c99a49d expected=ee724f9f159f8cdef185b42c43b...
- 2100	hash mismatch: count got=<n> expected=<n>, md5 got=f40a1ef6542491a0f490c50802955a8e expected=fd5ef87ee372019414f0b3de2d9...
- 1925	hash mismatch: count got=<n> expected=<n>, md5 got=287c225018dcf5275d60795ef673033b expected=665eeefca657f1f6c2d4f2ba683...
- 1925	hash mismatch: count got=<n> expected=<n>, md5 got=376a57a72b63bbd0b53390c7ee72216a expected=ac073ee6ea28ef0ed712cb7c239...
- 1925	hash mismatch: count got=<n> expected=<n>, md5 got=337cd209751d7466f9299dacb931e8a3 expected=ba461e878c0df14081008c4853f...

### go
- 48697	got(<n>)=["<s>"] expected(<n>)=["<s>"]
- 43463	got(<n>)=["<s>" "<s>"] expected(<n>)=["<s>" "<s>"]
- 37981	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 37638	got(<n>)=["<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>"]
- 37399	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>...
- 33314	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 25292	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=[]
- 19266	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>"]
- 17266	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 12290	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...

### zig
- 14113	got(<n>) expected(<n>) first got=<n> expected=<n>
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=5ba796b544ceea43d0af7fb3eaf92919 expected=9a6afb6b859fc856aafb6a7af11...
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=141999cb1d7a52c7485621f955e65308 expected=74b4b1d1e049d57b3610b70a67a...
- 8	expected error, got success
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=b826057329a4e68017a62a931747cb26 expected=5026537fcfcc7d06e2928e16f9b...
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=f9dd945f07c787fd3686e2672098de10 expected=e48615ff8ca5cfc049146260f31...
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=223d1e2bb9f666c7d541a3820d49118b expected=7ece664b68f1d5dd5df20c38b45...
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=a6ab8660ce234346838d3361d4915eec expected=33946dd780d80a44b8a5a40324a...
- 7	hash mismatch: count got=<n> expected=<n>, md5 got=810df65a31f5833a9b731ebc49a8bf88 expected=5597b8fa34613aadc270053ea54...
- 6	hash mismatch: count got=<n> expected=<n>, md5 got=caea5cb4da570651a8580bd6e9975bef expected=9e2d6381b04ea314cd79c5fc932...

### python
- 30993	got(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>'] expected(<n>)=[]
- 11780	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 10195	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 8934	index '<s>' already exists
- 3734	got(<n>)=[] expected(<n>)=['<s>', '<s>', '<s>']
- 3732	got(<n>)=['<s>', '<s>', '<s>'] expected(<n>)=[]
- 3705	got(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>']
- 3125	got(<n>)=['<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>']
- 2796	got(<n>)=['<s>', '<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>', '<s>']
- 2582	got(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>', '<s>'] expected(<n>)=['<s>', '<s>', '<s>', '<s>', '<s>', '<s>...
