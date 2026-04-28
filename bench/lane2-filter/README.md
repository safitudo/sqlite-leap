# Lane 2 corpus filter (2026-04-27)

Lane 2 (parse speed) had a methodology bug noted in memory
`2026-04-20 bench critique`: the upstream corpus contains ~52k
statements that leap doesn't implement. Both engines do unequal
work — leap fast-rejects, mainline tries to parse — so the lane 2
ratio measured rejection-path speed, not parse-path speed.

## What this directory contains

- `parse_filter_main.c` — mainline filter, builds with `-lsqlite3`.
  Reads workload, calls `sqlite3_prepare_v2` per statement, prints
  one `OK\n` or `ERR\n` per stmt to stdout, summary on stderr.
- `parse_filter.rs` — leap-rust filter. Drop into
  `src-rust/examples/`, build with `cargo build --release --example
  parse_filter`. Same I/O contract as the C filter; classifies stmts
  outside `{select,insert,create,noop}` as `ERR` (leap-rust does not
  implement them in lib_bench mode).
- `apply_filter.py` — intersects three masks. Reads original
  corpus.sql + 3 masks, splits stmts with the same rule as the C/Rust
  split_stmts, emits a filtered corpus where ALL THREE engines said
  `OK`.

For leap-c, `src-c/examples/lib_bench.c` was patched to accept a
`--filter` flag that emits `OK`/`ERR` per statement (instead of the
default qps line). The patch is documented in
`bench/results/2026-04-27-linux-native/lane2-filtered/run.log`; the
build script is unchanged.

## Result (2026-04-27, Linux x86_64)

Filtered: kept 65,652 / 157,373 (41.7%); per-engine drops
mainline=185, leap-c=91,536, leap-rust=78,538.

| corpus    | leap-c qps | leap-rust qps | mainline qps | leap-c / mainline |
|-----------|------------|---------------|--------------|-------------------|
| original  | 2,776      | 3,388         | 64,942       | 4.3%              |
| filtered  | 1,236      | 1,831         | 199,666      | 0.6%              |

The filter exposes the methodology bug from both sides:
- **leap qps drops** because the original numbers were inflated by
  the cheap fast-rejection path (33% of input was rejected in the
  tokenizer/classifier, faster than real parse).
- **mainline qps tripled** (65k -> 200k) because mainline was being
  slowed by `prepare_v2` failures on the same 33%; on a clean corpus
  it just parses and runs.

## How to rerun

On the Linux box (or any host with sqlite3-dev + cargo):

```bash
gcc -O2 -o /tmp/parse_filter_main bench/lane2-filter/parse_filter_main.c -lsqlite3
cp bench/lane2-filter/parse_filter.rs src-rust/examples/
( cd src-rust && cargo build --release --example parse_filter )
# patch src-c/examples/lib_bench.c with --filter mode (see run.log)
bash src-c/build_lib_bench.sh

CORPUS=bench/lanes/02-parse-speed/corpus.sql
/tmp/parse_filter_main "$CORPUS" > /tmp/mask_main.txt 2>/dev/null
src-c/build/lib_bench "$CORPUS" --filter > /tmp/mask_c.txt 2>/dev/null
src-rust/target/release/examples/parse_filter "$CORPUS" > /tmp/mask_rust.txt 2>/dev/null

python3 bench/lane2-filter/apply_filter.py \
    "$CORPUS" /tmp/mask_main.txt /tmp/mask_c.txt /tmp/mask_rust.txt \
    bench/lane2_corpus_filtered.sql
```
