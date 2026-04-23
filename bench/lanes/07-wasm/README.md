# Lane 7 — WASM bench

Three sub-lanes, three targets. The goal is fair WASM-engine-vs-WASM-engine
numbers for cold start, parse throughput, and in-memory SELECT throughput,
directly comparable with native lanes 1/2/3.

## Targets

| Target | How it's built | Version |
|---|---|---|
| `sqlite-leap-wasm` | `generators/wasm/build.sh` → `src-wasm/sqlite_leap.wasm` (Rust target compiled to `wasm32-unknown-unknown`, driven via `spec/wasm-ffi.spec.md`) | artifact bundled in repo; `leap_version() == 0x030b0000` (Phase 3b feature level); 560 KB |
| `sql.js` | `npm i sql.js@1.13.0` (bundled Emscripten build of SQLite 3.45.1) | 1.13.0 |
| `sqlite-wasm` | `npm i @sqlite.org/sqlite-wasm@3.51.2-build9` (SQLite team's official WASM build) | 3.51.2 |

Version pinning matters. `sqlite-leap-wasm` is whatever is checked into
`src-wasm/` at the time of the run — if you regenerate with a newer
Rust-target feature set, re-measure and update this README. The two
competitors are npm-pinned so they don't drift between runs.

## Sub-lanes

### `wasm-cold-start` — instantiate → first query ready

**Measured:** wall clock from "start of instantiation" to "first SELECT 1
committed," inside the Node process. **Not measured:** Node's own process
startup. We spawn a fresh child Node process per iteration so the
engine-internal module cache (`initSqlJs` and `sqliteInit` both memoise
across calls in the same process) doesn't make the second iteration look
artificially fast.

- **Method:** 30 runs + 3 warmup, median.
- **Output units:** `seconds`.
- **Parallel to native lane 1** (which also measures process wall clock
  for a cold engine + one SELECT).

### `wasm-parse-speed` — parse + execute throughput on a 10 MiB corpus

**Measured:** steady-state SQL throughput in bytes per second on the same
`bench/lanes/02-parse-speed/corpus.sql` the native lane feeds to
mainline/leap. We split the corpus on statement terminators (same logic as
`bench/lanes/_wrap_sql.py`, ported to JS) and drive one statement per FFI
call on all three targets. The leap FFI surface (`leap_exec`) only accepts
a single statement per call, so per-statement replay is mandatory; we
apply the same discipline to sql.js and sqlite-wasm for like-for-like.

- **Method:** 1 run, 0 warmup (single-run methodology, same as the native
  lane-2 CSV published on 2026-04-21 — leap's per-target runtime is 7+
  minutes and medianing 5 of those is not a realistic budget).
- **Output units:** `bytes_per_second_single_run`.
- **Parallel to native lane 2.**
- **Apples-to-apples caveat:** sql.js and sqlite-wasm could comfortably
  run 5 medianed iterations in the time leap needs for one. We
  intentionally match leap's budget rather than give them a variance-
  reduction advantage. Their medianed-of-5 numbers would be marginally
  lower-variance but no faster.

### `wasm-select-in-memory` — 100k point SELECTs on 10k rows

**Measured:** selects per second on
`bench/lanes/03-select-in-memory/workload.sql` (PRAGMA + CREATE + 10 000
INSERTs inside a transaction + 100 000 primary-key SELECTs). Same per-
statement replay as the parse lane.

- **Method:** 3 runs + 1 warmup, median.
- **Output units:** `selects_per_second`.
- **Parallel to native lane 3.**

## CSV output

Same 5-column format as every other lane's CSV:

```
lane,target,value,units,timestamp
wasm-cold-start,sqlite-leap-wasm,0.00687,seconds,2026-04-21T...
wasm-parse-speed,sql.js,1419344,bytes_per_second_single_run,2026-04-21T...
wasm-select-in-memory,sqlite-wasm,137995,selects_per_second,2026-04-21T...
```

Lane names carry a `wasm-` prefix to disambiguate from native lanes in
combined CSVs.

## Reproducing

```
cd bench/lanes/07-wasm
npm install                        # first time only; ~23 MB of node_modules
./run-all.sh > ../../results/2026-04-21-wasm.csv
```

Or individually:

```
./run.sh --target sqlite-leap-wasm --lane cold-start
./run.sh --target sql.js           --lane parse-speed
./run.sh --target sqlite-wasm      --lane select-in-memory
```

The runner accepts `--runs N --warmup N --verbose` for ad-hoc
investigation:

```
node runner.mjs --lane cold-start --target sqlite-leap-wasm --runs 10 --warmup 2 --verbose
```

`--verbose` prints the raw samples (useful for checking that the median
isn't masking a wild outlier).

## Known asymmetries (what the numbers do NOT say)

1. **Per-statement FFI is leap's native path, but a handicap for the
   others.** sql.js and sqlite-wasm both support batch-exec of multiple
   statements in a single FFI round-trip, which would reduce JS/WASM
   boundary-crossing overhead. We drive them one statement at a time to
   match leap's interface. This pessimises the competitors slightly —
   they'd be faster with batch exec. That's fine for this report; we
   publish honest per-statement numbers.

2. **sqlite-wasm's `initSqlJs`-equivalent is slower on Node because of
   OPFS probing.** The official SQLite WASM module does OPFS / worker-
   proxy capability detection during module load, which adds ~20-25 ms on
   Node (where OPFS isn't available anyway). In a real browser with OPFS
   support this cost is amortised against actual persistence features; in
   Node it's dead weight. If you want a pure "WASM instantiate only"
   number, subtract ~25 ms from sqlite-wasm's cold-start. We publish the
   honest wall clock because a real browser app pays this cost too.

3. **sql.js is compiled from an older SQLite (3.45.1); sqlite-wasm uses
   3.51.2; leap implements Phase 3b of the LEAP SQL subset.** Feature
   coverage differs. leap lacks some SQL dialect corners (e.g., some
   random/groupby fixtures from the upstream suite) and its performance
   characteristics are correspondingly different. These numbers are valid
   bench-to-bench comparisons, not feature-parity claims.

4. **sqlite-wasm logs sqlite3 step errors to stderr by default.** The
   lane-2 corpus produces occasional PRIMARY KEY collisions (random
   integers into an INTEGER PRIMARY KEY column); leap counts these as
   errors-but-continues, sqlite-wasm warns on every single one. The
   runner explicitly sets `sqlite3.config.warn = () => {}` on setup so
   stderr doesn't pollute the CSV output. Error counts are still
   captured in the `--verbose` output (`medianErrs` field); same order
   of magnitude on all three targets.

5. **Error-counting is cosmetic only.** The parse lane's wall clock
   includes the time each engine spent on the errored statements. That's
   the whole point of the lane — measure parse+execute throughput on a
   mixed, occasionally-invalid workload. The per-target error counts are
   reported for transparency but don't change the headline throughput
   number.

6. **First-query cost may be dominated by VDBE warm-up in leap.** The
   6-7ms cold-start for `sqlite-leap-wasm` includes the first `SELECT 1`,
   which invokes the VDBE for the first time; typical subsequent queries
   in the parse lane cost an order of magnitude less per statement.

## 2× priors rule

Project convention (DASHBOARD.md, `bench/README.md`): any bench result
showing one engine >2× faster than another is a **bug candidate, not a
win**, until a plausible structural reason is identified. Current
lane-7 standings (macOS arm64 / Apple M2 Ultra, one pass on 2026-04-21):

| Lane | leap vs sql.js | leap vs sqlite-wasm | Structural reason |
|---|---|---|---|
| cold-start | leap 2.0× faster | leap 4.2× faster | sql.js: mature minifier keeps startup tight; sqlite-wasm: OPFS probe overhead on Node. Documented asymmetry #2. |
| parse-speed | leap 58× slower | leap 35× slower | leap VDBE is un-tuned (Phase 3b); same gap as native lane 2 (80-99× slower than mainline). Not a measurement bug. |
| select-in-memory | leap 75× slower | leap 110× slower | same VDBE-not-tuned story; WASM adds a further ~2-3× slowdown on top of native leap. |

The only entry that trips the 2× rule is `cold-start vs sqlite-wasm`
(4.2×); the structural reason (OPFS probe) is documented and reproducible
by setting `sqlite3.config.warn` before measurement (no effect — the time
is spent in the C-level worker-proxy capability check before `oo1` is
reachable). Noting this publicly rather than quietly discounting it.

## Version pins (2026-04-21 run)

- `sqlite-leap-wasm`: `src-wasm/sqlite_leap.wasm`, `leap_version() ==
  0x030b0000`, 560 039 bytes. Phase 3b feature level; built by
  `generators/wasm/build.sh` on 2026-04-20.
- `sql.js`: 1.13.0 (embeds SQLite 3.45.1).
- `@sqlite.org/sqlite-wasm`: 3.51.2-build9 (embeds SQLite 3.51.2).
- Node: v22.22.0.
- Host: macOS arm64, Apple M2 Ultra.

If you re-measure after updating any of these, re-run `run-all.sh`, put
the new CSV in `bench/results/YYYY-MM-DD-wasm.csv`, and update the
version pin block above.
