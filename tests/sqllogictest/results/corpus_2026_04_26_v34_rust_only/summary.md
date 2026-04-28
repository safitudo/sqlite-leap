# v34 corpus rerun rust-only 2026-04-26

Files sampled per target: 186
Per-file timeout: 60s

## Per-target aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP | excl-SKIP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rust | 1619257 | 169 | 65 | 123255 | 1742746 | 92.91% | 99.99% |

## FAIL files per target

### rust
- 30	index/in/10/slt_good_0.test
- 15	index/in/10/slt_good_1.test
- 15	index/in/10/slt_good_5.test
- 15	index/in/10/slt_good_4.test
- 12	random/expr/slt_good_31.test
- 11	random/expr/slt_good_59.test
- 10	index/commute/10/slt_good_21.test
- 9	random/expr/slt_good_18.test
- 9	random/expr/slt_good_45.test
- 7	evidence/slt_lang_replace.test
- 7	select4.test
- 5	random/expr/slt_good_0.test
- 4	evidence/slt_lang_aggfunc.test
- 4	random/expr/slt_good_111.test
- 3	evidence/slt_lang_createview.test
- 3	evidence/slt_lang_droptable.test
- 3	random/expr/slt_good_86.test
- 3	random/expr/slt_good_72.test
- 2	evidence/slt_lang_dropindex.test
- 2	evidence/slt_lang_dropview.test


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
