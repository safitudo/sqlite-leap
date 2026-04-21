# Phase 6bd test harness — SELECT ALL

Tiny parser-only extension: accept the optional `ALL` keyword after `SELECT` as a no-op. No AST change, no compile change. `max_invariant=43` unchanged.

## Invocation

`<harness-binary> <path-to-phase6bd.json>`

Generated into `src-{lang}/bin/phase6bd-test`.

## Output

`SUMMARY phase=6bd target=<c|rust|wasm> passed=<int> failed=<int> total=<int>`

## Gate

6 cases green both targets. Byte-identical cross-build.

Corpus win: ~7K records in random/aggregates and random/select unlocked.

## Implementation notes

- Parser: at the DISTINCT-peek position (already present for Phase 6d/6h DISTINCT), ALSO peek for `KEYWORD_ALL`. If found, consume and do nothing. `ALL` and `DISTINCT` are mutually exclusive — if both appear, `PARSE_UNEXPECTED_TOKEN` on the second.
- AST: unchanged. No flag for ALL.
