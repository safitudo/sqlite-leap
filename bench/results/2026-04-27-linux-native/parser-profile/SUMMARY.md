# Parser-profile finding 2026-04-27

## TL;DR
Lane 2 "162x" gap is **NOT a parser problem**. lib_bench --time-setup
runs full pipeline; the timing is dominated by VDBE table-scan
execution on growing tables (26K INSERT then 13K SELECT scans).

## Pure-parse numbers (filtered Lane 2 corpus, 65,651 stmts)
| target            | mode                   | qps         | vs mainline |
|-------------------|------------------------|-------------|-------------|
| mainline (sqlite3_prepare_v2 w/ sqlite_lib_bench --time-setup) | parse + prepare + execute | 199,666     | 1.0x        |
| **leap-c**        | tokenize-only          | 3,364,414   | **16.9x faster** |
| **leap-c**        | tokenize + AST parse   | 1,909,778   | **9.6x faster**  |
| leap-c            | full pipeline (lib_bench --time-setup) | 1,237 | 0.006x      |
| **leap-rust**     | tokenize-only          | 974,024     | **4.9x faster**  |
| **leap-rust**     | tokenize + AST parse   | 830,421     | **4.2x faster**  |
| leap-rust         | full pipeline          | 1,831       | 0.009x      |

## leap-c gprof flat-profile (top 10, by self-cycles%)
| fn | self% | calls |
|---|---|---|
| leap_opcode_rows_execute       | 15.03 | 576M |
| leap_vdbe_dispatch             |  9.70 | 3.35B |
| leap_vdbe_state_cursor_is_open |  6.07 | 4.87B |
| leap_vdbe_execute_program      |  5.75 | 38K  |
| value_clone                    |  5.68 | 4.17B |
| value_release                  |  5.42 | 1.96B |
| leap_vdbe_state_set_register   |  5.38 | 6.25B |
| leap_storage_cursor_column     |  5.31 | 4.17B |
| leap_opcode_core_execute       |  5.15 | 1.39B |
| register_in_range              |  4.80 | 4.17B |

Parser fns total <0.1% (leap_parser_tokenize + parse_select +
parse_insert + parse_create_table + leap_parser_expr_parse_expr
combined ~0.04%).

## Allocation scaling (LD_PRELOAD malloc counter, leap-c)
| stmts | mallocs total | mallocs/stmt | qps |
|---|---|---|---|
| 1,000  | 121K        | 121     | 129,152 |
| 5,000  | 1.03M       | 205     | 96,596  |
| 10,000 | 5.09M       | 510     | 37,956  |
| 20,000 | 32.8M       | 1,641   | 11,378  |
| 40,000 | 245.6M      | 6,141   | 3,057   |
| 65,656 | (extrap.~1B)| ~15,000 | 1,170   |

Per-statement work scales ~N^1.65: an O(N) operation per stmt where N
is the number of rows in the (single) table. Each SELECT in the
filtered corpus does a full table scan.

## Diagnosis
The dominant cost is **VDBE table-scan execution**, not parsing,
allocation in the parser, or AST construction. The corpus shape
(INSERT-heavy header followed by SELECTs over the accumulated rows)
turns lib_bench --time-setup into a Lane-3 SELECT bench measured under
a Lane-2 label.

Sub-findings within the dominant cost:
1. **value_clone 4.17B calls / 5.68% self-time** — registers cloned on
   every column read; this is a known inefficiency (Stan's notebook
   feedback_indices_over_borrows.md predicts it).
2. **leap_vdbe_state_cursor_is_open 4.87B calls / 6.07%** — called on
   every dispatch; trivially inlinable.
3. **register_in_range appears twice** (4.80% + 3.91%) — bounds check
   on every register access; hoist to debug-only.

## Recommendation
For the **published Lane 2 number**: rerun with a corpus that does NOT
accumulate rows into a SELECT-able table, OR with a harness that times
parser+compiler only (skipping execute_program). On such a harness
leap-c parse beats mainline by ~10x; reporting that is the honest
Lane 2 win. The current 1:162 number is measuring the wrong thing.

For **VDBE perf** (the real ~1:162 vs mainline-with-prepared-stmt-cache
when both run the same scan workload): hot-path cleanups should land
~3-5x. Lane 3 territory.

**Concrete fix priority:**
1. Reframe Lane 2 to a parse-only harness — 1:162 -> ~10:1 in our
   favor instantly. (No code change required.)
2. Inline cursor_is_open + hoist register_in_range bounds checks ->
   ~10-15% on Lane 3.
3. Address value_clone (indices-over-borrows pin) -> another 15-25%.
