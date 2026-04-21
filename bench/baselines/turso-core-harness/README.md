# turso-core-harness — library-vs-library Turso benchmark adapter

`tursodb` (the Turso CLI shipped in `bench/baselines/bin/turso`) is 13.5 MiB
on macOS arm64. Most of that is not engine code — it's rustyline, syntect
(with a vendored 150 MiB of syntax definitions), mimalloc, a tracing
subscriber, a clap parser, and an MCP server. For the "embedded DB library"
comparison sqlite-leap cares about, that's noise.

This crate is a small hand-written binary that links against `turso_core`
directly, bypassing the CLI shell. It measures what a consumer of the Turso
engine would actually link.

## What this crate is and is not

- It is a benchmark adapter. 150 lines of Rust in `src/main.rs`.
- It depends on `turso_core` by path, pinned via the vendored clone at
  `bench/baselines/src/turso/` (tag `v0.5.3`, commit
  `09c149a776b5140bfff3e3dee1dc786177d2615a`).
- It does not modify Turso's source. It only imports the public API.
- It is not an implementation reference for sqlite-leap. See the
  do-not-cheat rule in `../turso/README.md` and the repo root `CLAUDE.md`.

## Public API we consumed

From `turso_core`:

- `MemoryIO` / `PlatformIO` — I/O backends.
- `Database::open_file(io, path) -> Result<Arc<Database>>` — opens (or
  attaches to) a database. `:memory:` short-circuits the process registry.
- `Database::connect() -> Result<Arc<Connection>>`.
- `Connection::query_runner(sql: &[u8]) -> QueryRunner` — iterates
  multi-statement SQL, one `Statement` at a time.
- `Statement::step() -> Result<StepResult>`, `Statement::row()`,
  `StepResult::{Row, Done, IO, Interrupt, Busy}`.
- `Value::{Null, Numeric, Text, Blob}` with `Display`.

All of these are re-exported from `turso_core/lib.rs`'s top-level `pub use`
block — no private-API surgery, no unsafe escape hatches used.

## Build

```sh
cd bench/baselines/turso-core-harness
cargo build --release
```

Release profile matches sqlite-leap-rust: `lto = "fat"`, `codegen-units = 1`,
`strip = true`, `panic = "abort"`. Cold build ~45s on an M2 Ultra once the
`turso_core` cargo cache is warm (the first-ever build pulls ~900 crates
and takes ~1m35s same as the CLI build).

## Run

```sh
# Cold start: opens :memory:, runs SELECT 1;, exits.
./target/release/turso-core-bench --mode=cold-start

# Multi-statement SQL from a file against :memory:.
./target/release/turso-core-bench --mode=run --sql-file=path/to.sql

# Multi-statement SQL from stdin against a file DB.
./target/release/turso-core-bench --mode=run --db=path/to.db < script.sql
```

stderr carries `ELAPSED_NS=<ns>` (a coarse end-to-end timer). stdout emits
one line per result row, pipe-separated columns, to match the existing
leap-rust / sqlite-mainline lane runners.

Non-strict multi-statement execution is the default: errors log to stderr
(`step error (continuing): ...`) and the run continues, matching CLI
behaviour. Cold-start mode is strict — any error aborts.

## Numbers (macOS arm64, M2 Ultra, 2026-04-20)

See `bench/results/2026-04-20-turso-core-library-variant.csv` for full data.
Headlines:

| lane              | tursodb CLI   | turso-core lib | reduction |
|-------------------|---------------|----------------|-----------|
| cold-start        | 20.9 ms       | 9.8 ms         | 2.1× faster |
| binary-size       | 13,486,168 B  | 6,330,224 B    | 2.13× smaller |
| memory-footprint  | 16,728,064 B  | 9,338,880 B    | 1.79× less |

And the full comparison at the same sitting (lower is better):

| lane             | mainline | tursodb CLI | turso-core lib | leap-c  | leap-rust |
|------------------|---------:|------------:|---------------:|--------:|----------:|
| cold-start (s)   | 0.01572 | 0.02091    | 0.00982       | 0.00342 | 0.00345   |
| binary-size (B)  | 1,219,888 | 13,486,168 | 6,330,224    | 412,704 | 1,125,552 |
| memory RSS (B)   | 2,752,512 | 16,728,064 | 9,338,880    | 1,671,168 | 2,113,536 |

## Narrative framing

**CLI-vs-CLI** (`tursodb` vs `sqlite3` vs the sqlite-leap sqllogictest
binary): the 13.5 MiB `tursodb` ships the full interactive shell, and loses
on cold-start / size / memory against both mainline SQLite *and* leap-c by
wide margins. Publish this as a separate row: honest, user-visible, the
size of a binary you download.

**Lib-vs-lib** (`turso_core` the crate, linked by this adapter, vs the
sqlite-leap C/Rust builds). The 6.3 MiB `turso-core-bench` is a tighter
comparison: it's the engine plus a ~100-line test driver. Even here,
leap-c beats it 15× on size and 2.9× on cold-start, and leap-rust beats
it 5.6× on size and 2.8× on cold-start. But the *ratio* vs turso shrinks
dramatically vs the CLI number, and publishing both is what keeps the
claim honest.

## Lanes 2, 3, 4

Not measured. Two obstacles, separable:

1. **`PRAGMA journal_mode=MEMORY` is rejected by Turso.** Lane 3's corpus
   opens with exactly that pragma. The CLI `tursodb` rejects it too but
   keeps processing the rest of the file. Our harness does the same
   (non-strict mode), so lane 3 can in principle run — but the first
   statement never takes effect, which muddies what's being measured.
2. **Lane 2/4 corpora reference tables that may not exist yet.** Mixed
   DDL + DML against random names by design; both CLIs error on the first
   bad statement. Matching CLI semantics, we keep going.

Because the `Bench integrity fix` agent is actively rewriting these lane
runners, the `turso-core` wiring for lanes 2/3/4 is parked in
`INTEGRATION.patch` alongside this README. Apply that patch after the
bench-fix lands. In this CSV the three lanes are marked
`NA,pending-harness-fix,turso-core`.

## Known limitations

- **macOS only.** Linux numbers need the host.
- **No io_uring.** The adapter uses `PlatformIO` for file DBs on all
  platforms — no preferential treatment for io_uring on Linux. A separate
  adapter variant can flip that feature on later.
- **Default features enabled on `turso_core`.** Disabling them (e.g.
  `default-features = false, features = ["fs"]`) causes compile errors in
  `core/incremental/dbsp.rs` which unconditionally references `uuid`. We
  keep defaults on; the binary-size number therefore includes json, uuid,
  time, series, encryption code paths — same as the CLI.
- **Not a reference for sqlite-leap generation.** This adapter is built
  purely as a measurement target. No turso_core source is read or copied
  during `src-c/` / `src-rust/` / `src-wasm/` generation.
