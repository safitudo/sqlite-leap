# Phase 6ak test harness — language-neutral spec

Phase 6ak adds `IF EXISTS` on DROP and `IF NOT EXISTS` on CREATE. Idempotency modifiers only; no new opcodes. Algorithm per `spec/sql-grammar.spec.md` § "Phase 6ak".

## Invocation

```
<harness-binary> <path-to-phase6ak.json>
```

Generated into `src-{lang}/bin/phase6ak-test`.

## Output

```
SUMMARY phase=6ak target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`.

## Gate

13 cases green on both C and Rust. All prior phases regression-green. Byte-identical cross-build.

Corpus win: unblocks 30+ `.test` files in upstream corpus (evidence/, index/, random/) that use `DROP TABLE IF EXISTS` or `CREATE INDEX IF NOT EXISTS` in their test setup.

## Implementation notes

- Tokenizer: no changes. `IF`, `EXISTS`, `NOT` are reserved.
- Parser: extend DROP TABLE / DROP INDEX to optionally accept `KEYWORD_IF KEYWORD_EXISTS` before identifier; extend CREATE TABLE / CREATE INDEX to optionally accept `KEYWORD_IF KEYWORD_NOT KEYWORD_EXISTS`. Attach `if_exists` / `if_not_exists` boolean to the DDL AST node.
- Compile: check the flag before raising the existence error. Suppressed: emit `{"rows": []}` success. Otherwise: unchanged.
- **Cross-object-kind rule**: `CREATE TABLE IF NOT EXISTS foo` where `foo` is an INDEX still raises `STORAGE_TABLE_EXISTS`. The check is by object kind, not name.

## Cross-build risks

- Don't parse `IF` greedily alone — a partial phrase (`DROP TABLE IF t`) must be a clean PARSE_UNEXPECTED_TOKEN, not silent fallback.
- `DROP VIEW IF EXISTS` should parse-accept but not run until Phase 6ac (CREATE VIEW) lands — if the current DROP VIEW path already errors, keep that path.
