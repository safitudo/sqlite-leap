# Phase 6b test harness — language-neutral spec

Identical to `phase6a-harness.md`. Phase 6b adds 6 new VDBE opcodes (`SorterOpen`, `SorterInsert`, `SorterSort`, `SorterRewind`, `SorterNext`, `SorterRead`), a new Program field `num_sorters`, and new AST fields (`order_by` on Select) — but NO new step kinds, NO new backends, NO new error names.

## Invocation

```
<harness-binary> <path-to-phase6b.json>
```

Generated into `src-{lang}/bin/phase6b-test` (or the target's equivalent).

## Pipeline per step

Unchanged from Phase 6a: tokenize → parse → compile → vdbe.run against an in-memory storage handle. Each case starts with a fresh `create_database()`.

## Well-formedness invariants

Invariants 1–13 from Phase 2c-3 remain. Phase 6b adds invariants 14–20 as specified in `spec/vdbe-opcodes.spec.md` § Phase 6b. Harness MUST enforce them at step run-time (raises `VDBE_WELLFORMEDNESS_VIOLATION` — same error name used since Phase 2b).

## Equality rules

- `rows` / `error`: match Phase 6a conventions.
- For ORDER BY cases, row order matters — arrays are compared positionally, not as sets.
- `expected` arrays for `PARSE_UNEXPECTED_TOKEN` are compared as sets.
- `fields` on `PARSE_UNEXPECTED_TOKEN` are subset-matched; only fields declared in `expect.fields` are compared. `pos` field is OPTIONAL.

## Output

Per case: `PASS <case.name>` or `FAIL <case.name> at step <idx>: <reason>`. Final line:

```
SUMMARY phase=6b target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.

## Non-goals

Unchanged. Phase 6b adds ORDER BY on SELECT; aggregates, GROUP BY, JOINs remain deferred.
