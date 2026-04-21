# Phase 6bb test harness — language-neutral spec

Phase 6bb adds `ASC`/`DESC` per-column modifier in `CREATE INDEX` column list. Parse-only; no execution change in v1. Algorithm per `spec/sql-grammar.spec.md` § "Phase 6bb".

## Invocation

```
<harness-binary> <path-to-phase6bb.json>
```

Generated into `src-{lang}/bin/phase6bb-test`.

## Output

```
SUMMARY phase=6bb target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`.

## Gate

6 cases green on both C and Rust. All prior phases regression-green. Byte-identical cross-build.

Corpus win: unblocks 10+ `index/` subcorpus files, each currently failing ~4-5K queries on `CREATE INDEX ... (col DESC)` syntax rejection. Projected aggregate unlock ~40K records.

## Implementation notes

- Tokenizer: no changes. `ASC`, `DESC` already reserved.
- Parser: in the `CREATE INDEX ... (...)` column-list production, after each identifier, optionally accept `KEYWORD_ASC` or `KEYWORD_DESC`. Store the direction as a field on the index schema node (default `ASC` when absent).
- Compile / execution: NO changes. The index is built and populated exactly as before — the direction flag is stored but not consulted.

## Cross-build risks

- Both generators must use the same default ("asc") for omitted direction — byte-identical schema dumps depend on this.
- Do NOT attempt to build the index in descending key order; v1 indexes are always ascending by row-id insertion order. This is an intentional v1 simplification — the direction flag is a compatibility placeholder.
