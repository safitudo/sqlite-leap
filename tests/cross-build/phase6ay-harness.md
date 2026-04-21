# Phase 6ay test harness — language-neutral spec

Phase 6ay extends the JOIN compiler/planner from 2-table (Phase 6e) to N-table (N ≥ 3). No new VDBE opcodes. `max_invariant=43` unchanged. Algorithm per `spec/sql-grammar.spec.md` § "Phase 6ay".

## Invocation

```
<harness-binary> <path-to-phase6ay.json>
```

Generated into `src-{lang}/bin/phase6ay-test`.

## Output

```
SUMMARY phase=6ay target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`.

## Gate

7 cases green on both C and Rust. All prior phases regression-green. Byte-identical cross-build on result rows.

Additionally: `sqllogictest ../tests/sqllogictest/upstream/test/select5.test` must stop panicking on both targets (may still fail on other features — just no panic).

## Implementation notes

- Parser already accepts `table ( join-op table on-condition )+` chains. Only the compiler plan needs extension.
- **Canonical lowering**: left-associative nested-loop. For chain `a JOIN b ON c1 JOIN c ON c2 JOIN d ON c3`:

```
open a
outer loop over a:
    open b; apply c1 filter
    loop over b:
        open c; apply c2 filter
        loop over c:
            open d; apply c3 filter
            loop over d:
                emit row
```

- Table aliases: already supported since Phase 6aa pin.
- Column resolution: walks the JOIN chain's table-alias map; qualified refs (`t.col`) look up by alias; unqualified refs must be unambiguous across the chain.
- Scope for INNER JOIN vs LEFT OUTER JOIN is unchanged from Phase 6e — just iterate per additional table.

## Cross-build risks

- Join-order differences won't affect row output if the final result is ORDER BY'd (test fixtures do this). Without ORDER BY, row order is undefined and byte-identical expectations should not be assumed.
- Register allocation for N cursors may differ per target. Output rows must match; opcode streams may diverge.
