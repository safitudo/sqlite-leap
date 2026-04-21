# sqllogictest runner — language-neutral spec

## Why this exists

"Done" criterion #1 is: `sqllogictest` pass rate ≥ mainline SQLite's own pass rate on the same suite, on **both** C and Rust builds. That criterion is load-bearing for the stunt — without a functioning `sqllogictest` runner, we cannot measure it, and any claim about SQL correctness is hand-waving. This spec defines the runner as a language-neutral component so that both the C and Rust builds can produce identical pass/fail verdicts on identical test files.

## sqllogictest file format (normative subset)

The sqllogictest format is a published text format originally created for the SQLite project. This spec pins the subset we interpret. Unrecognised directives outside this subset MUST be skipped silently with a warning emitted once per file.

### File structure

A `.test` file is a sequence of **records** separated by blank lines. Whitespace-only lines count as blank. Comments start with `#` at the beginning of a line and extend to end-of-line; blank lines and comments separate records but otherwise have no semantic meaning.

### Record types

#### `statement ok`

```
statement ok
<SQL statement>
```

Executes the SQL. PASS iff no error is raised. FAIL if any error is raised. Multi-line SQL terminates at the next blank line.

#### `statement error`

```
statement error [optional-error-pattern]
<SQL statement>
```

Executes the SQL. PASS iff an error IS raised. If an `optional-error-pattern` is present, the raised error's message must match the pattern (substring match; case-sensitive). FAIL if no error, OR if the error message does not match the pattern.

#### `query <typestring> [<sortmode>] [<label>]`

```
query IIT nosort
<SQL SELECT statement>
----
<expected rows, one value per line>
```

Executes the SQL and compares the result set to the expected rows.

- **`typestring`**: a string of one character per output column. Characters:
  - `I` — integer
  - `R` — real (floating point)
  - `T` — text (also used for NULL, BLOB, and non-integer non-real values)
- **`sortmode`** (optional):
  - `nosort` (default) — rows compared in order produced by the engine.
  - `rowsort` — rows sorted by tuple-lex comparison (left-to-right over rendered cell values, treating each row as a tuple). Column order WITHIN each row is preserved; rows are reordered against each other. (2026-04-18 retroactive pin per cross-corroboration between C and Rust runner implementations. Earlier wording was ambiguous and could be read as "sort cells within each row, then sort rows" — mainline sqllogictest has never done the inner sort; pin here matches mainline.)
  - `valuesort` — all values (across rows and columns) flattened into a single list, sorted lexicographically, then compared.
- **`label`** (optional): an identifier used for cross-file result deduplication. Two queries with the same label across any number of files must produce identical result hashes. Ignored in v1; runner MAY record but need not enforce.

##### Expected result format

Following `----`, the expected rows appear. Formatting rules:

- One value per line. A query producing an R×C result set produces R×C lines.
- NULL is rendered as the literal string `NULL` regardless of typechar.
- **Rendering is driven by the typechar declared in `typestring`, NOT by the runtime type of the cell**. The engine's reported value is coerced to the declared column type before rendering. Mainline sqllogictest pins this rule (retroactive 2026-04-20 per cross-corroboration with `index/random/*` corpus expectations), because generated-random tests are written assuming the typechar controls rendering:
  - `I` (integer):
    - Integer value → decimal (no leading zeros, optional leading `-`).
    - Real value → truncated to `i64` (toward zero), then decimal.
    - Text value → prefix-parsed as signed decimal integer (atoi semantics: optional leading whitespace, optional leading `+`/`-`, then digits up to first non-digit; empty prefix yields `0`).
    - `NULL` → literal `NULL`.
  - `R` (real):
    - Integer value → `%.3f`.
    - Real value → `%.3f`.
    - Text value → prefix-parsed as floating point (atof semantics; empty prefix yields `0.000`), then `%.3f`.
    - `NULL` → literal `NULL`.
  - `T` (text):
    - Integer value → decimal.
    - Real value → `%.3f`.
    - Text value → as-is, one line per value. A text containing a newline is encoded by replacing the newline with the literal two-character sequence `\n` (backslash + 'n'). Empty text is rendered as `(empty)`.
    - BLOB → lowercase hex with no prefix.
    - `NULL` → literal `NULL`.
- Reals use `%.3f` format (3 digits after decimal point). EXCEPTION: sqllogictest originally used `%g` but all modern suites converge on a canonical form; our runner MUST match whatever the reference hash agrees with — see § "Result hashing" below.

##### Hash-based result comparison

If a query's expected output is abbreviated as:

```
<N> values hashing to <md5-hex>
```

(where `<N>` is the total number of VALUES — i.e., rows × cols — produced), then:

1. The runner computes the canonical string representation of each output value (per rules above), concatenates them separated by `\n` (ONE trailing `\n` at the end, no terminal blank), MD5-hashes the resulting byte string, and compares the lowercase hex digest to `<md5-hex>`.
2. The row count is an independent check; `<N>` must match actual rows × cols.

Hash comparison is used for large result sets to keep `.test` files compact. It is the authoritative canonicalization for numeric values — both full-form and hashed forms must agree on the same canonical string.

### Control records

#### `halt`

Stop executing this file. Any records after `halt` are ignored. Used to stub out currently-unimplemented features without deleting the records.

#### `hash-threshold <N>`

Any `query` record with more than `<N>` values in its expected output MAY be presented in hash form. Runner ignores this for parsing; it's an authoring hint.

#### `onlyif <engine>` / `skipif <engine>`

Preceding a record:

```
onlyif leap
statement ok
<SQL>
```

means "only run this record if the running engine is named `leap`". Our runner's engine name is `leap`. `skipif` is the negation. Multiple `skipif` / `onlyif` lines stack (all must pass).

#### `mode <mode>`

`mode` switches the default rendering mode for subsequent records. Recognised values: `standard` (default). Other values are skipped-with-warning.

## Runner invocation

```
<harness-binary> <path-to-test-file-or-directory> [--filter=<glob>]
```

- Single `.test` file: run every record.
- Directory: recursively find `*.test` files, run each in isolation (new DB per file).
- `--filter`: only run files matching the glob. Defaults to `*.test`.

Each test file runs against a fresh in-memory database. The runner does NOT share state across files.

## Output

### Per-record output (one line)

```
<PASS|FAIL|SKIP> <file-relative-path>:<line-number> <record-kind> <optional-detail>
```

Examples:

```
PASS suite/select/001.test:14 query
FAIL suite/select/002.test:27 query expected-hash=abc... got-hash=def...
SKIP suite/create/005.test:5 onlyif=sqlite
```

### Per-file output (one line, after all records in the file)

```
FILE <file-relative-path> passed=<int> failed=<int> skipped=<int> total=<int> duration_ms=<int>
```

### Summary (at end)

```
SUMMARY sqllogictest target=<c|rust|wasm> passed=<int> failed=<int> skipped=<int> total=<int> duration_ms=<int>
```

Exit 0 iff `failed == 0`, else 1. `skipped` does not fail the run.

## Suite shape

The initial suite lives under `tests/sqllogictest/`. It is a curated subset of the public sqllogictest corpus, trimmed to:

- **select1.test** through **select5.test** — the canonical selection suite (thousands of SELECT queries over synthetic tables).
- **random/aggregates/** — generated aggregate queries.
- **evidence/** — feature-tagged evidence tests (e.g., every clause of the SQL grammar has one record asserting it parses + runs).

We do NOT port the full mainline corpus in one pass. We land the above four categories first (they gate the L3 SELECT benchmark's credibility); later categories (joins, subqueries, CTEs) gate later phases of SQL coverage and land with their corresponding phases.

**Curation rule**: a test is in-suite iff its mainline SQLite behaviour is unambiguously defined by a published SQLite spec or documented feature. Tests that depend on mainline implementation quirks (e.g., internal rowid allocation order after DELETE, or specific `sqlite_stat1` heuristics) are excluded or rewritten to be spec-only. The goal is testing SQL correctness, not mainline-idiosyncrasy compatibility.

## Test authority

The sqllogictest runner IS a test runner; it does not itself need fixtures. Its correctness is verified by:

1. Running our own `tests/sqllogictest/smoke/` (5-10 hand-written `.test` files covering every record type and every rendering rule). Passing these on both C and Rust builds gates the runner itself.
2. Running a mainline `.test` file (e.g., upstream `select1.test`) against mainline SQLite via a reference harness AND against leap; the pass/fail verdicts must AGREE. Disagreement is either a runner bug, a spec gap, or a genuine leap defect — disambiguation is manual.

The mainline-reference harness (`tests/sqllogictest/reference_sqlite.py`) drives `sqlite3` CLI via subprocess, parses its output with a minimal adapter, and emits the same PASS/FAIL/SKIP lines. Its output is diffed against the leap runner's output; identical = success; non-identical = triage.

## Non-goals

- Full compatibility with every sqllogictest dialect extension (e.g., duckdb's extensions, mainline's internal-test-only directives). We implement the canonical published subset. Anything else is "skip-with-warning".
- Parallel execution across files. v1 is sequential for reproducibility; parallelism is a performance opt-in that can be added without spec change.
- Result caching. Every run is fresh; caching is an opt-in developer tool, not part of the gate.
