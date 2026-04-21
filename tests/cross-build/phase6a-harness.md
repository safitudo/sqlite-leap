# Phase 6a test harness — language-neutral spec

Identical to `phase2c3-harness.md`. Phase 6a adds NO new step kinds, NO new opcodes, NO new backends. It's a grammar + compiler + expected-set-table extension only.

## Invocation

```
<harness-binary> <path-to-phase6a.json>
```

Generated into `src-{lang}/bin/phase6a-test` (or the target's equivalent).

## Pipeline per step

Unchanged from Phase 2c-3: tokenize → parse → compile → vdbe.run against an in-memory storage handle. Each case starts with a fresh `create_database()`.

## Well-formedness invariants

Same 13 invariants from Phase 2c-3. Phase 6a adds no new opcodes.

## Equality rules

- `rows` / `error`: match Phase 2c-3 conventions.
- `expected` arrays for `PARSE_UNEXPECTED_TOKEN` are compared as sets.
- `fields` on `PARSE_UNEXPECTED_TOKEN` are subset-matched: only fields declared in `expect.fields` are compared. `pos` field is OPTIONAL in Phase 6a fixtures (most cases don't assert exact position).

## Output

Per case: `PASS <case.name>` or `FAIL <case.name> at step <idx>: <reason>`. Final line:

```
SUMMARY phase=6a target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.

## Non-goals

Unchanged from Phase 2c-3. Phase 6a adds only LIMIT/OFFSET on SELECT; ORDER BY, aggregates, JOINs remain deferred.
