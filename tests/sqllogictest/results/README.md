# 2026-04-20 full-corpus sweep — real pass rates

Context: the 2026-04-20 external reviewer flagged that our published
"99.48% C / 99.82% Rust" number was sampled across ~54 common files, not
measured end-to-end. Action item #2 was to run the full upstream
sqllogictest corpus against both targets and publish the log. This is
that measurement.

## Invocation

```sh
# Rust (first)
tests/sqllogictest/run-full-corpus-parallel.sh \
  --target rust \
  --out tests/sqllogictest/results/2026-04-20-rust-full.log \
  --timeout 90 --jobs 4

# C (second — not concurrent with Rust on the same host)
tests/sqllogictest/run-full-corpus-parallel.sh \
  --target c \
  --out tests/sqllogictest/results/2026-04-20-c-full.log \
  --timeout 90 --jobs 8
```

Per-file timeout: 90s via perl `SIGALRM` wrapper (macOS has no GNU `timeout`).
Status classification (first token of each per-file log line):

- `PASS`    — runner exited 0
- `FAIL`    — runner exited 1..128 (any record mismatch per sqllogictest convention)
- `TIMEOUT` — SIGKILLed after 90s wall clock
- `PANIC`   — exit by signal (segfault, abort, bus error…) or rc > 128

(During the C run a concurrently-edited `_worker-one-file.pl` started emitting
an extra advisory `FAIL-TIMEOUT: <rel> file-level <ms>` line for every timeout.
Those advisory lines have been stripped from the committed log and the summary
block has been regenerated from the real per-file records. The Rust log is
unaffected — it was written before the edit.)

## Environment

- Date: 2026-04-20 → 2026-04-21 UTC (Rust finished at 23:36Z, C finished ~00:25Z).
- Commit: none — this tree has no git commits (`fatal: ambiguous argument 'HEAD'`). Working tree only.
- Host: Darwin Stanislavs-Mac-Studio.local 25.2.0 arm64 (Mac Studio, Mac14,14, 24-core M-series, macOS 26.2 / 25C56).
- Corpus: `tests/sqllogictest/upstream/test/` — 622 `.test` files:
  - 5 top-level `selectN.test`
  - 12 `evidence/`
  - 214 `index/`
  - 391 `random/`
- Binaries:
  - Rust: `src-rust/target/release/sqllogictest` (built 2026-04-20 15:52)
  - C:    `src-c/bin/sqllogictest`             (built 2026-04-20 16:11)

## Headline numbers

| Target | Total | Pass | Fail | Timeout | Panic | Pass rate |
|--------|-------|------|------|---------|-------|-----------|
| Rust   | 622   | 402  | 218  | 2       | 0     | **64.63%** |
| C      | 622   | 161  | 262  | 190     | 9     | **25.88%** |

**Neither target meets the previously-claimed 99%.** The sampled-~54-file
number was not representative of the full corpus; the dense
`random/expr/` and `random/aggregates/` subtrees (which dominate the
corpus by file count) expose a scalar-function and evaluation gap we had
not been measuring.

## Top failure categories (first FAIL message per file, re-run with 30s per-file cap)

### Rust — 218 FAIL files

| Category                             | Files | Example locus |
|--------------------------------------|-------|---------------|
| `RUNTIME_COMPILE_UNKNOWN_FUNCTION`   | 129   | `random/expr/slt_good_*.test`            |
| `RUNTIME_EVAL_DIVISION_BY_ZERO`      | 42    | `random/aggregates/slt_good_*.test`      |
| `QUERY_HASH_MISMATCH`                | 21    | `index/random/10/slt_good_*.test`        |
| `RUNTIME_STORAGE_TABLE_NOT_FOUND`    | 16    | `index/view/10/slt_good_*.test`          |
| `QUERY_ROWCOUNT_MISMATCH`            | 4     | `random/groupby/slt_good_0.test`         |
| `RUNTIME_COMPILE_AMBIGUOUS_ALIAS`    | 3     | (random/ tail)                           |
| `STMT_EXPECTED_ERROR_GOT_OK`         | 1     | `evidence/slt_lang_dropview.test`        |
| `RUNTIME_STORAGE_DUPLICATE_COLUMN`   | 1     | `evidence/slt_lang_update.test`          |
| `QUERY_VALUE_MISMATCH`               | 1     | `index/random/10/slt_good_10.test`       |

Rust timeouts (2): `select4.test`, `select5.test` — the two longest
hand-written top-level suites.

### C — 262 FAIL files

| Category                             | Files | Example locus |
|--------------------------------------|-------|---------------|
| `QUERY_VALUE_MISMATCH`               | 123   | `random/aggregates/slt_good_*.test`      |
| `RUNTIME_COMPILE_UNKNOWN_FUNCTION`   | 122   | `random/expr/slt_good_*.test`            |
| `RUNTIME_EVAL_DIVISION_BY_ZERO`      | 7     | `random/aggregates/` tail                |
| `RUNTIME_PARSE_UNEXPECTED_TOKEN`     | 5     | `index/view/10/slt_good_*.test`          |
| `RUNTIME_COMPILE_AMBIGUOUS_ALIAS`    | 3     | (random/ tail)                           |
| `QUERY_ROWCOUNT_MISMATCH`            | 1     | `random/groupby/slt_good_14.test`        |
| (uncategorized by current regex)     | 1     | `evidence/slt_lang_update.test` (`expected=ok got-error=STORAGE_DUPLICATE_COLUMN` + row mismatches) |

C timeouts (190): dominated by `index/between/`, `index/commute/`,
`index/in/`, `index/orderby*/` — index subtrees where the C build runs
algorithmically slower than Rust. Rust passes the same files in
300 ms – 1.5 s each; the C build cannot complete any of them within 90 s.
This is a runtime gap, not a correctness gap — the tests that complete
either pass or fail deterministically.

C panics (9): all in `random/groupby/slt_good_{0,1,2,3,4,5,7,8,13}.test`.
Reproduced: exit code 138 (SIGBUS, signal 10). A crash bug in the C
aggregation/group-by path on these randomly-generated queries.

## Divergence shapes

- **Rust fails but C passes** or vice versa: happens — the two targets
  are not bug-identical. Combined with the 190 C timeouts on files Rust
  passes, this means the previously-published 99%+ "byte-identical
  smoke" (203/203) only reflects the hand-authored smoke subset, *not*
  the `random/` + `index/` subtrees that dominate upstream.
- **Common gap:** `RUNTIME_COMPILE_UNKNOWN_FUNCTION` is the single
  largest failure bucket on both targets (129 Rust / 122 C), signalling
  scalar builtins missing from the spec — a single surface to fix that
  would lift both targets simultaneously. That is the highest-leverage
  next action per LEAP cross-corroboration rule: both generators independently
  stumble on the same spec gap.
- **C-only issue:** `QUERY_VALUE_MISMATCH` on 123 `random/aggregates/`
  files suggests an aggregate-evaluation divergence between targets;
  Rust produces the expected rows while C does not. Fix the C generator
  or — more likely — the spec for aggregate semantics so both targets
  converge.

## Verdict vs the 99% claim

**Does not meet it.** Full-corpus measured rates are 64.63% Rust / 25.88%
C, well below the sampled 99.82 / 99.48 on the narrower common file set.
Any public comparison against mainline SQLite, Turso, or sql.js must cite
these real numbers until the scalar-function, aggregate, and
index-query-plan gaps close. The reviewer was right.

## Files

- `2026-04-20-rust-full.log` — 622 per-file records + summary block.
- `2026-04-20-c-full.log`    — 622 per-file records + summary block (advisory `FAIL-TIMEOUT:` dup-lines stripped, summary rewritten).
