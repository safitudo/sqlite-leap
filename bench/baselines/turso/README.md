# Turso baseline

Turso (formerly Limbo, repo still tracks that alias) is the Rust-native SQLite
reimplementation we compare against. The sqlite-leap narrative claim — "one
language-neutral spec, two implementations, same tests pass on both" — is
only meaningful if we put numbers next to the hand-written-in-one-language
alternative. That alternative is Turso.

## Pinned version

| field         | value                                                    |
|---------------|----------------------------------------------------------|
| tag           | `v0.5.3`                                                 |
| commit        | `09c149a776b5140bfff3e3dee1dc786177d2615a`               |
| released      | 2026-04-02                                               |
| upstream      | https://github.com/tursodatabase/turso                   |
| CLI binary    | `tursodb` (workspace member `cli`, `default-run=tursodb`) |
| installed as  | `bench/baselines/bin/turso`                              |

`v0.5.3` is the most recent non-prerelease as of 2026-04-20. `v0.6.0-pre.*`
tags exist but are explicitly flagged as prereleases on the upstream
releases page.

The pin lives in three places so every build target is reproducible:

1. `bench/baselines/fetch-baselines.sh` — `TURSO_TAG` / `TURSO_COMMIT`.
2. `bench/baselines/bin/turso.version` — text file written next to the
   binary by `fetch-baselines.sh` (gitignored, regenerated per host).
3. `bench/baselines/bin/turso.commit` — same, for the SHA.

If the upstream tag ever moves (it shouldn't), the `TURSO_COMMIT` sanity
check in `fetch-baselines.sh` emits a warning.

## Build

```sh
./bench/baselines/fetch-baselines.sh --turso
```

Internally that does, at the pinned tag:

```sh
git clone --depth 1 --branch v0.5.3 \
    https://github.com/tursodatabase/turso.git bench/baselines/src/turso
cd bench/baselines/src/turso
cargo build --release --bin tursodb
cp target/release/tursodb ../../bin/turso
strip ../../bin/turso       # macOS strip is a no-op on signed Mach-O; fine
```

Build time on this host (M2 Ultra, macOS 26.2, rustc 1.94.1): ~1m35s for
`--release --bin tursodb` on a cold cargo cache (~900 crates).

We build **only** the `tursodb` binary rather than the whole workspace. The
workspace has 40+ members (JavaScript bindings, Python bindings, simulator,
fuzzer, etc.); building all of them is ~6× longer and produces nothing the
benchmark harness uses.

## CLI compatibility

`tursodb` speaks the `sqlite3`-CLI dialect closely enough that every lane's
existing "pipe SQL to the DB file" invocation works unchanged:

```sh
turso :memory: 'SELECT 1;'           # inline SQL
echo 'SELECT 1;' | turso :memory:    # stdin
turso path/to/file.db < script.sql   # DB + stdin
```

Verified on 2026-04-20: reads a small DB produced by mainline SQLite
(`bench/lanes/06-memory-footprint/small-db.sqlite`, 20 KiB) and returns
`SELECT count(*) FROM t;` → `500` identical to mainline.

## Lanes and results (macOS arm64, M2 Ultra, 2026-04-20)

All numbers in `bench/results/2026-04-20-Stanislavs-Mac-Studio-baseline.csv`;
Turso-only snapshot in `bench/results/2026-04-20-turso-only.csv`.

| lane              | turso        | mainline sqlite | sqlite-leap-c | sqlite-leap-rust |
|-------------------|--------------|-----------------|---------------|------------------|
| cold-start (s)    | 0.01093      | 0.00785         | 0.00325       | 0.00352          |
| binary-size (B)   | 13,486,168   | 1,219,888       | 412,704       | 1,108,880        |
| memory-footprint (B) | 16,744,448 | 2,719,744       | 1,654,784     | 2,113,536        |
| parse-speed       | NA — pending harness fix (see note) |
| select-in-memory  | NA — pending harness fix             |
| insert-throughput | NA — pending harness fix             |

### Notes on clean-lane numbers

- **Cold start**: Turso is ~1.4× *slower* than mainline SQLite at cold start
  on this host. That's explained by the `tursodb` CLI's heavier startup
  (rustyline / syntect / mimalloc / tracing-subscriber init — it's a full
  interactive shell). `turso` the *library* is faster at open-time than
  mainline; `tursodb` the CLI is not. Framing matters: our cold-start
  number is for a CLI invocation, same methodology as everyone else.
- **Binary size**: Turso ships 13.5 MiB stripped — significantly heavier
  than mainline (1.2 MiB) because it statically links a syntax highlighter,
  mimalloc, rustyline, etc. The `sqlite-leap` C build wins this lane
  decisively for the same reason SQLite itself does: tiny surface, no
  Rust stdlib drag, no shell ornaments.
- **Memory footprint**: 16 MiB peak RSS for an open-small-db-and-exit
  workload, vs mainline's 2.7 MiB. Same explanation as binary size; the
  CLI is rope-heavy at startup. This is a *CLI* footprint number, not a
  library-embedded one.

### Why lanes 2/3/4 are `pending-harness-fix`

The 2026-04-20 reviewer found that parse-speed, select-in-memory, and
insert-throughput all feed sqllogictest-formatted input to `sqlite3` /
`turso`, which those CLIs silently reject; what's being measured there is
rejection speed, not throughput. The issue is upstream to this baseline —
fixing it is lane-2/3/4 harness surgery, not baseline-related. Turso rows
for those lanes stay `NA,pending-harness-fix` until the harness is fixed;
once it is, re-run `./bench/lanes/0{2,3,4}/run.sh --target turso`.

## Known limitations

- **macOS only**: these numbers are from `arm64` (M2 Ultra). Linux numbers
  are a separate job — Turso's io_uring feature is on by default and will
  likely move the INSERT lane meaningfully when we have it.
- **Stripped size is approximate**: macOS `strip` on Rust release binaries
  is a near no-op (Mach-O debug info isn't inline). Linux `strip` removes
  more. The 13.5 MiB number is therefore pessimistic; the Linux number
  will be smaller.
- **Build pulls submodules**: the syntect git dependency pulls
  `sublimehq/Packages` (~150 MiB of syntax definitions) during the update
  step. If bandwidth is constrained, cache `~/.cargo` aggressively.
- **Not cross-built for WASM**: Turso does ship WASM bindings via
  `bindings/javascript`, but those aren't a CLI and don't fit the current
  harness. Lane-6-vs-WASM comparisons against Turso will need a separate
  setup.

## Library variant (engine-vs-engine)

For the CLI-vs-CLI vs library-vs-library distinction (important for the
embedded-DB narrative), see `bench/baselines/turso-core-harness/README.md`.
That crate links directly against `turso_core` — bypassing rustyline,
syntect, mimalloc, tracing-subscriber, and the MCP/sync server shells —
and measures ~6.3 MiB binary, ~9.3 MiB RSS, ~9.8 ms cold-start on this
host. Numbers live in
`bench/results/2026-04-20-turso-core-library-variant.csv`.

The `tursodb` CLI row above is still the right number to publish for
"what a user downloads". The `turso-core` row is the right number for
"what an application linking libturso_core pays".

## Do-not-cheat reminder

This baseline is **not** a reference implementation for sqlite-leap's own
generation. The CLAUDE.md rule at the repo root is absolute: no Turso
source reading during `src-c/` / `src-rust/` / `src-wasm/` generation.
Turso is here strictly as a finish-line marker.
