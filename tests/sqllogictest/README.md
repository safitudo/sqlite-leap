# sqllogictest corpus

This directory holds the sqllogictest suites that sqlite-leap uses to verify
behavioral equivalence with mainline SQLite. Three scopes live side-by-side:

```
tests/sqllogictest/
├── smoke/                # hand-authored minimal suite, byte-identical gate (C == Rust)
├── smoke-harness.md      # language-neutral spec for the smoke harness
├── upstream/             # gitignored — full vendored upstream corpus (see below)
├── run-full-corpus.sh    # sweep every upstream/.test file against a target
├── results/              # gitignored — per-sweep .log files
└── README.md             # this file
```

## What is sqllogictest

`sqllogictest` is SQLite's randomized-query regression suite. Each `.test` file
is a sequence of `statement` / `query` records describing SQL input and the
expected result (either literal rows or an md5 hash). The record format is
language-neutral; any engine that claims SQLite-compatible behavior can be
driven against it.

Upstream home: <https://sqlite.org/sqllogictest/> (Fossil). Vendored snapshot
pulled via `tests/sqllogictest/upstream/Dockerfile`.

## Corpus layout (`tests/sqllogictest/upstream/test/`)

622 `.test` files in four groups:

| Subtree      | Files | What it exercises                                              |
|--------------|-------|----------------------------------------------------------------|
| `select1-5.test` (top level) | 5 | Hand-written SELECT suites exercising a wide SQL surface. `select1` is the classic smoke — 1031 records. |
| `evidence/`  | 12    | Evidence-of-correctness tests that cite specific sentences in the SQL documentation (`EVIDENCE-OF: R-…`). Covers `IN` semantics, `slt_lang_*` (language features: aggregates, triggers, views, indexes, REPLACE, REINDEX, UPDATE, DROP…). |
| `index/`     | 214   | Index-correctness tests: `between/`, `commute/`, `delete/`, `in/`, `orderby/`, `orderby_nosort/`, `random/`, `view/` — each a matrix of generated index scenarios. |
| `random/`    | 391   | Machine-generated stress suites split into `aggregates/`, `expr/`, `groupby/`, `select/`. |

The upstream corpus is SQLite Public Domain — see
<https://sqlite.org/copyright.html>. Vendored verbatim; do not edit `.test`
files under `upstream/`.

## Running

### Full corpus sweep

```sh
# rust target (default), 120s per-file timeout
tests/sqllogictest/run-full-corpus.sh

# C target
tests/sqllogictest/run-full-corpus.sh --target c

# tighter per-file timeout
tests/sqllogictest/run-full-corpus.sh --target rust --timeout 60
```

Prerequisite: the target's sqllogictest binary is built.

- Rust: `(cd src-rust && cargo build --release --bin sqllogictest)`
  → `src-rust/target/release/sqllogictest`
- C: `(cd src-c && make sqllogictest)`
  → `src-c/bin/sqllogictest`

Output:

- `tests/sqllogictest/results/<YYYY-MM-DD>-<target>.log` — per-file RESULT lines + aggregate footer.
- stdout — aggregate summary (total / passed / failed / skipped / timed-out files + file pass-rate %).

Exit code:

- `0` iff ≥ 95% of executed files pass (skipped and timed-out files count as NOT passed).
- `1` otherwise. Wire this into CI once the rate is consistently above the gate.

### Single subtree

Invoke the sqllogictest binary directly — it accepts either a file or a
directory and walks recursively:

```sh
# one file
src-rust/target/release/sqllogictest tests/sqllogictest/upstream/test/select1.test

# one subtree
src-rust/target/release/sqllogictest tests/sqllogictest/upstream/test/evidence

# whole corpus in one process (no per-file timeout — use run-full-corpus.sh for that)
src-rust/target/release/sqllogictest tests/sqllogictest/upstream/test
```

### Smoke suite (C == Rust byte-identical)

```sh
src-rust/target/release/sqllogictest tests/sqllogictest/smoke > /tmp/rust.out
src-c/bin/sqllogictest              tests/sqllogictest/smoke > /tmp/c.out
diff /tmp/rust.out /tmp/c.out    # must be empty
```

See `smoke-harness.md` for the spec contract that makes byte-identical output
possible (timing elided, canonical field names, lexicographic file order).

## Re-fetching upstream

If the corpus is missing (`tests/sqllogictest/upstream/test/` empty — it is
gitignored), re-vendor via the upstream Dockerfile:

```sh
cd tests/sqllogictest/upstream
docker build -t slt-gen .
rm -rf test && mkdir test
docker run --rm -v "$PWD/test:/work/test" slt-gen
```

That image clones `https://sqlite.org/sqllogictest.git` (Fossil) and copies the
`test/` subtree. Do not fetch from a SQLite-*implementation* source; the test
corpus is a spec artifact and allowed, the implementation is not (see
`CLAUDE.md` § "DO NOT CHEAT").

## Licensing

- `upstream/` — SQLite Public Domain (<https://sqlite.org/copyright.html>).
- `smoke/` and this scaffolding — same license as the rest of sqlite-leap.
