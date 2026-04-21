# Fuzz corpus — language-neutral spec

## Why this exists

"Done" criterion #2: reads/writes databases produced by mainline SQLite with zero corruption across fuzz corpus, both builds. The fuzz corpus is the specific artifact that measurement depends on. This spec defines the corpus shape, the mutation strategies, the harness contract, and the equivalence oracle — all language-neutral so both C and Rust builds share the same corpus and the same verdicts.

## Corpus shape

The corpus lives under `tests/fuzz/corpus/` and is organised as follows:

```
tests/fuzz/
├── corpus/
│   ├── db/              # valid mainline-generated .sqlite files (seeds)
│   ├── db-mutated/      # AFL / libFuzzer output: mutated DB files
│   ├── sql/             # valid SQL statement strings (seeds)
│   ├── sql-mutated/     # AFL / libFuzzer output: mutated SQL strings
│   └── index.json       # corpus index (seeds + mutations + provenance)
├── harness/
│   ├── parse-only/      # binaries: run parser, expect any outcome without crash
│   ├── exec-only/       # binaries: run VDBE, expect any outcome without crash
│   ├── roundtrip-db/    # binaries: open DB → dump schema+rows → compare to mainline
│   └── roundtrip-sql/   # binaries: run SQL on leap + mainline → diff results
└── reports/             # ephemeral: per-run crash, hang, diff reports
```

### Seed corpus (`corpus/db/` and `corpus/sql/`)

**db/** seeds are produced by running a small library of SQL scripts through mainline SQLite and capturing the resulting `.sqlite` files. Each seed has a manifest (`.meta.json`) recording: the script that produced it, the mainline version used, the feature subset exercised (e.g., "btree-only", "wal-mode", "index-heavy"), and a canonical hash of its byte content.

Seed naming: `<category>-<short-description>-<hash6>.sqlite` (e.g., `btree-single-table-42rows-a1b2c3.sqlite`).

**sql/** seeds are hand-authored or corpus-mined SQL strings covering every grammar production currently implemented. Each seed is one SQL statement (or a semicolon-separated batch); each is recorded in `index.json` with a `grammar-coverage` tag enumerating the non-terminals it exercises.

### Mutation corpora (`corpus/db-mutated/` and `corpus/sql-mutated/`)

Populated by the fuzzers. For **C build**, the fuzzer is libFuzzer (linked into an ASan+UBSan binary). For **Rust build**, the fuzzer is `cargo-fuzz` (wraps libFuzzer) OR `afl.rs`; both produce compatible corpus layouts. Shared corpus: a mutation found by EITHER fuzzer MUST be added to the shared corpus and exercised by both.

Retention policy: every mutation that triggers a NEW code-path (per libFuzzer's coverage tracker) is retained. Mutations that provide no new coverage are discarded at the end of the fuzzing run. This keeps the corpus shrinking-to-minimal-viable-set while still catching regressions.

## Mutation strategies

### DB-file mutations (byte-level)

Applied to seeds in `corpus/db/`:

- **Bit-flip**: random single-bit flip in the file body (skipping the 100-byte header).
- **Byte-flip**: random single-byte set to a random value.
- **Page-header corruption**: target the first N bytes of a random page and randomise them; tests our header-validation paths.
- **Cell-pointer corruption**: target the cell-pointer array of a random leaf or interior page.
- **Free-list corruption**: target the free-block linked list inside a page.
- **Truncation**: truncate the file at a random page boundary.
- **Over-extension**: append random bytes past the file-reported page count.

### SQL-string mutations (token-level)

Applied to seeds in `corpus/sql/`:

- **Token insertion**: insert a random token from the grammar's terminal set at a random position.
- **Token deletion**: remove a random token.
- **Token swap**: swap two adjacent tokens.
- **Literal mutation**: change a numeric / string literal to an adversarial value (MAX_INT, MIN_INT, INT_MIN-1, empty string, 1MB string, NaN, Infinity).
- **Identifier collision**: replace an identifier with a reserved word.
- **Nesting explosion**: wrap a subexpression in N layers of parentheses (probe stack depth).

## Harness contracts

Each harness binary consumes one input (bytes from the fuzzer), exercises a specific code path, and signals outcome to the fuzzer via process exit status:

- **Exit 0**: input consumed cleanly (parsed successfully OR parsed-with-expected-error). This is the fuzzer's "accepted" signal.
- **Non-zero exit**: input triggered an expected engine-level error (malformed SQL, corrupt DB). Also counted as accepted.
- **Crash / abort / sanitizer hit**: unexpected failure. The fuzzer records the input in `reports/crashes/` and the harness is expected to have been compiled with ASan/UBSan/MSan so the exact defect is captured.
- **Hang (> 10s)**: unexpected infinite loop or livelock. Fuzzer records the input in `reports/hangs/`.

### `parse-only` harness

```
<harness-binary> <path-to-sql-input>
```

Reads the file, passes contents as a single SQL string to the parser. Expected outcomes: successful parse, `SQL_PARSE_ERROR { ... }`, `SQL_UNSUPPORTED { ... }`. Any OTHER outcome (panic, crash, assertion) is a fuzz finding.

### `exec-only` harness

```
<harness-binary> <path-to-sql-input>
```

Reads the file, parses, compiles to VDBE, runs against a fresh in-memory DB. Expected outcomes: successful execution (any result), any named engine error from the condition enumeration in `spec/errors.spec.md` (to be authored), or any of the `VDBE_*` errors. Unnamed errors = fuzz finding.

### `roundtrip-db` harness

```
<harness-binary> <path-to-sqlite-file>
```

Opens the file via leap, dumps schema and all rows of every table to a canonical text format. Opens the same file via mainline `sqlite3` CLI, dumps identically. Diffs. Exit 0 iff dumps match; non-zero iff they differ.

Specifically: any dump-diff is a bidirectional-compatibility violation and gates "Done" criterion #2.

### `roundtrip-sql` harness

```
<harness-binary> <path-to-sql-input>
```

Runs the SQL on leap (fresh DB) and on mainline (fresh DB); diffs result sets. Exit 0 iff diffs empty; non-zero iff they differ.

Some SQL constructs are deliberately non-deterministic (ORDER BY without an ORDER BY; rowid order after DELETE). The harness normalises by sorting every result set on all columns before diff. A small denylist of constructs known to produce platform-dependent output (e.g., `date('now')`) is filtered out at input time.

## Equivalence oracle

The three harnesses define three equivalence classes:

1. **`parse-only`**: did we parse something mainline also parses? (Yes/no; no result comparison.)
2. **`exec-only`**: did we execute something mainline also executes? (Binary verdict; no result comparison.)
3. **`roundtrip-*`**: did we produce the SAME result mainline produces? (Full semantic equivalence.)

Level 3 is the strongest and is what gates publication. Level 1 and 2 are intermediate gates that fail first during fuzz campaigns — they catch parse / execute crashes before they mutate into roundtrip divergence.

## Cross-build equivalence (C vs Rust)

A mutation found by the C fuzzer MUST also be run through the Rust harness, and vice versa. The two builds must produce:

- Identical pass/fail verdict on every harness.
- Byte-identical output on `roundtrip-db` dumps.
- Byte-identical output on `roundtrip-sql` result sets.

Any divergence is a language-specific spec leak and blocks publication. This is the same invariant that `tests/cross-build/` enforces at the fixture level; fuzz extends it to adversarial inputs.

## Operational limits

- Per-input timeout: 10 seconds. Longer → recorded as hang.
- Per-input memory cap: 1 GiB. Longer → recorded as OOM (counted as crash).
- Campaign duration: 24-hour rolling for each of `parse-only`, `exec-only`, `roundtrip-db`, `roundtrip-sql` (total 4×24 = 96 CPU-hours of fuzzing between releases).
- Shared coverage: libFuzzer corpus merge after each campaign keeps only inputs that increase coverage.

## Non-goals

- Crashing mainline SQLite. If a mutation crashes mainline, it is recorded (surprising!) but not reported as a leap defect — we report upstream and skip the input from our diff oracle.
- Property-based SQL generation (e.g., SQLsmith). A valuable addition but out of scope for the initial infrastructure landing; can be added later as another seed source into `corpus/sql/`.
- Multi-process fuzz. v1 is single-process per harness instance; a driver script parallelises across CPUs but each instance is independent.
