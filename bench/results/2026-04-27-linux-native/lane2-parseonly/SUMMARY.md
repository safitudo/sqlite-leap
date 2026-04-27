# Lane 2 parse-only — 2026-04-27 Linux x86_64

## Why this directory exists

The previous Lane 2 number (--time-setup mode in lib_bench) was NOT
measuring parse. See ../parser-profile/SUMMARY.md for the gprof
flat-profile: parser fns <0.1% of cycles; dominant cost was
leap_opcode_rows_execute (15%) + leap_vdbe_dispatch (9.7%) — i.e.
VDBE table-scan execution on the SELECT-on-growing-table corpus
shape. Lane 2 was secretly a slow Lane 3 wearing a parse-speed label.

This rerun adds a real parse-only mode to all three harnesses
(mainline sqlite3_prepare_v2 + sqlite3_finalize, no step; leap-c
leap_parser_tokenize + parse_<stmt> then drop AST; leap-rust
tokenize + parse_* then drop AST) and measures only the parser.

## Numbers (3 runs, filtered corpus, 65,653 stmts)

| target    | median qps  | success | errors | vs mainline |
|-----------|-------------|---------|--------|-------------|
| mainline  | 1,060,065   | 26,205  | 39,448 | 1.00x       |
| leap-c    | 1,857,806   | 52,583  | 13,070 | 1.75x       |
| leap-rust |   710,430   | 52,583  | 13,070 | 0.67x       |

CSV: raw.csv (3 runs each).

## What "9.6x" actually was — and what it is not

The parser-profile/SUMMARY.md quoted ~9.6x faster for leap-c. That
number was leap-c parse-only vs mainline FULL PIPELINE
(prepare + step + finalize) at 199,666 qps. Apples-to-oranges.

Apples-to-apples (parse vs parse): leap-c is ~1.75x mainline.
Still a Lane 2 win, but the headline gap shrinks once we measure
mainline prepare_v2 instead of prepare_v2 + step. Treat 9.6x as a
legacy cached number from when the Lane 2 harness was wrong; this
directory s 1.75x is the honest measurement.

## Caveats on apples-to-applesness

- Mainline prepare_v2 does parse + name resolution + bytecode emit.
  We are not running CREATE TABLE side-effects in this mode (we
  just prepare the CREATE, then finalize without stepping), so 60%
  of mainline prepare attempts fail fast with "no such table" —
  those error paths return earlier than a successful prepare would,
  inflating mainline qps relative to a schema-resolved run.
- Leap parsers do PURE SYNTACTIC parse, no name resolution. The
  13,070 leap errors are real syntactic rejections; the 39,448
  mainline errors are mostly semantic (table missing).
- Net: this comparison probably UNDERSTATES leap-c parse win vs a
  schema-resolved mainline. A future iteration should run the
  CREATEs untimed first, then time only SELECT/INSERT prepare on
  both sides.

## Files changed

- src-c/examples/lib_bench.c — added --parse-only flag +
  run_parse_only() (tokenize + parse + release AST). Forces
  time_setup=true so the entire corpus is timed.
- src-rust/examples/lib_bench.rs — same shape: --parse-only flag
  + run_parse_only().
- bench/baselines/sqlite_lib_bench.c — added --parse-only flag +
  run_one_parse_only() (prepare_v2 + finalize, no step).
- bench/run-linux-libmode.sh — Lane 2 now passes --parse-only
  instead of --time-setup.

The first two files are gitignored generation output; their
patches were applied directly on the Linux box. Apply the same
edits at regen time, or promote --parse-only into the lib_bench
part emit spec so future regens carry the mode.

## Reproduce

    ssh stanislav@192.168.1.143
    cd ~/sqlite-leap
    WL=bench/results/2026-04-27-linux-native/lane2-filtered/lane2_corpus_filtered.sql
    bench/baselines/bin/sqlite_lib_bench           "$WL" --parse-only
    src-c/build/lib_bench                          "$WL" --parse-only
    src-rust/target/release/examples/lib_bench     "$WL" --parse-only
