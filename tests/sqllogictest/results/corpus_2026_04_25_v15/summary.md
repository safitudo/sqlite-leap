# v10 corpus run 2026-04-25 (5 leap targets + mainline sqlite baseline)

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP | excl-SKIP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rust | 1553045 | 160 | 4848 | 88464 | 1646517 | 94.32% | 99.68% |
| c | 1459464 | 1257 | 4938 | 83229 | 1548888 | 94.23% | 99.58% |
| go | 1500478 | 4896 | 19146 | 83741 | 1608261 | 93.30% | 98.42% |
| zig | 409733 | 2306 | 23345 | 36910 | 472294 | 86.75% | 94.11% |
| python | 1634239 | 9804 | 7775 | 134851 | 1786669 | 91.47% | 98.94% |
| sqlite | 1655199 | 19 | 0 | 134851 | 1790069 | 92.47% | 100.00% |

## Top 10 DEFER reasons per target

### rust
- 3130	compile: deferred: compound SELECT with CTE or derived FROM
- 256	compile: deferred: DISTINCT across JOIN sources
- 197	parse: <pos> deferred: parenthesized table-ref / subquery in FROM
- 89	compile: unknown table: t2 (schema is for t1)
- 85	compile: unknown table: t6 (schema is for t1)
- 80	compile: unknown table: t7 (schema is for t1)
- 79	compile: unknown table: t4 (schema is for t1)
- 74	compile: deferred: IN subquery
- 74	compile: unknown table: t8 (schema is for t1)
- 72	compile: unknown table: t3 (schema is for t1)

### c
- 1627	compile: ambiguous column: col0
- 552	compile: deferred: complex expression in JOIN context
- 455	compile: ambiguous column: pk
- 197	parse: <pos> deferred: parenthesized table-ref
- 188	compile: deferred: <n>-or-more-way JOIN with aggregation
- 86	compile: unknown table: t2 (schema is for t1)
- 80	compile: unknown table: t6 (schema is for t1)
- 77	compile: unknown table: t4 (schema is for t1)
- 74	compile: deferred: subquery in non-SELECT context
- 72	compile: unknown table: t8 (schema is for t1)

### go
- 2595	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 1879	compile: deferred α23: correlated subquery with aggregate / GROUP BY / compound
- 1146	compile: ambiguous column: col0
- 523	compile: deferred: unknown expression node
- 455	compile: ambiguous column: pk
- 197	parse: parse error at token <n> (line <n> col <n>): deferred: parenthesized table-ref / subquery in FROM
- 70	parse: parse error at token <n> (line <n> col <n>): expected '<s>' after IN
- 39	compile: deferred: star projection in aggregate query
- 13	statement: unsupported leading kw "<s>"
- 6	parse: parse error at token <n> (line <n> col <n>): deferred: blob literal

### zig
- 2052	compile: deferred: derived-table subquery in FROM
- 2000	compile: deferred: JOIN with aggregation
- 1383	compile: deferred: aggregate in scalar context
- 1047	compile: unknown table in JOIN: tab2
- 1035	compile: unknown table in JOIN: tab1
- 941	compile: unknown table in JOIN: tab0
- 796	compile: deferred: mixed INTERSECT/EXCEPT/UNION in one compound SELECT
- 550	compile: deferred: IN subquery
- 229	compile: unknown table in JOIN: t2
- 228	compile: deferred: DISTINCT/ORDER BY across JOIN

### python
- 2595	compile: deferred: DISTINCT or ORDER BY across JOIN sources
- 2351	compile: deferred: correlated subquery (Python pre-execute model)
- 1146	compile: ambiguous column: col0
- 455	compile: ambiguous column: pk
- 426	compile: deferred: <n>-or-more-way JOIN with aggregation
- 410	compile: deferred: expression ExprCast across JOIN sources
- 197	parse: expected SELECT after '<s>' in FROM (parenthesized JOIN deferred)
- 70	parse: expected '<s>' after IN
- 41	compile: deferred: star projection in aggregate query
- 25	statement: unsupported leading kw '<s>'

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
- 47	got(<n>) expected(<n>): cell <n> got=<n> expected=<n>
- 37	row count mismatch: <n> cells vs expected <n>
- 32	install: too many tables
- 10	schema: unknown table t33
- 10	schema: unknown table t34
- 10	schema: unknown table t35
- 10	schema: unknown table t36
- 10	schema: unknown table t37
- 10	schema: unknown table t38
- 10	schema: unknown table t39

### go
- 510	hash mismatch: count got=<n> expected=<n>, md5 got=e20b902b49a98b1a05ed62804c757f94 expected=9d3557642e57f7f03e636d9ae90...
- 236	got(<n>)=["<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>"]
- 225	got(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>" "<s>" "<s>"]
- 175	hash mismatch: count got=<n> expected=<n>, md5 got=69ea35c77af3760266d28e7abca05b5f expected=41188ae9f1de9f62c029b0ba1e6...
- 130	got(<n>)=["<s>" "<s>" "<s>" "<s>"] expected(<n>)=["<s>" "<s>" "<s>" "<s>"]
- 125	hash mismatch: count got=<n> expected=<n>, md5 got=02372058a6257f2baf27a233f4ae9275 expected=df58bd920fa5bb8073dbe2713be...
- 125	hash mismatch: count got=<n> expected=<n>, md5 got=77ae578f9f7513b505a7a2af2444cebc expected=8c51d1dd174dc466cfb50dd81ca...
- 105	hash mismatch: count got=<n> expected=<n>, md5 got=1545dbae6984d5a7242371e4fc8003a6 expected=95ffe0f363ac316e7624bba07a1...
- 100	hash mismatch: count got=<n> expected=<n>, md5 got=9003cd84b3ceed4984f6b3ec56c14ab9 expected=9d88223741eaf4864dd05243683...
- 100	hash mismatch: count got=<n> expected=<n>, md5 got=6f07f79710643bfb1f1d41826957c270 expected=d0d143ef7831cba4153cd8c7141...

### zig
- 290	hash mismatch: count got=<n> expected=<n>, md5 got=b833e3a3ba082b2c0028b4cd08f0834d expected=db761b746c7d0f18810c20311a9...
- 241	got(<n>) expected(<n>) first got=-<n> expected=-<n>
- 203	got(<n>) expected(<n>) first got=<n> expected=<n>
- 60	got(<n>) expected(<n>) first got=<n> expected=NULL
- 26	hash mismatch: count got=<n> expected=<n>, md5 got=8b75136b2b51c77345c03804ec1cda5c expected=cd7a7901e47c15155404aff0d21...
- 21	got(<n>) expected(<n>) first got=-<n> expected=<n>
- 16	got(<n>) expected(<n>) first got=<n> expected=-<n>
- 10	hash mismatch: count got=<n> expected=<n>, md5 got=bcacc2835f645a422e7c49b22a4249ee expected=c28bfbaaee0fa364e85ac2df047...
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=5ba796b544ceea43d0af7fb3eaf92919 expected=9a6afb6b859fc856aafb6a7af11...
- 8	hash mismatch: count got=<n> expected=<n>, md5 got=141999cb1d7a52c7485621f955e65308 expected=74b4b1d1e049d57b3610b70a67a...

### python
- 540	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=b4932ce2176929487a0600a939f...
- 460	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=463a8481a3c42a48764d017d9e1...
- 460	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=c7733d57b26c9c868ee6669da35...
- 380	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=73719e959c2a2fe1cfe419b4519...
- 340	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=7aa228701de8d21263c44e16030...
- 300	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=d4ae738bdf2c57c7b49cfb7b94e...
- 260	hash mismatch: count got=<n> expected=<n>, md5 got=d41d8cd98f00b204e9800998ecf8427e expected=e0ff9f51855fbcbf409d9f48f2a...
- 140	hash mismatch: count got=<n> expected=<n>, md5 got=1cf5e33842cb88de423f90bc8276641d expected=7aa228701de8d21263c44e16030...
- 120	hash mismatch: count got=<n> expected=<n>, md5 got=129ba3736da584e9c86827198721b1ff expected=c7733d57b26c9c868ee6669da35...
- 100	hash mismatch: count got=<n> expected=<n>, md5 got=948a388ebdb7c808733eb78b29713187 expected=c7733d57b26c9c868ee6669da35...

### sqlite
- 13	OperationalError: no such table: t1
- 3	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 1	OperationalError: integer overflow
- 1	expected error, got success
- 1	OperationalError: no such trigger: t1r1
