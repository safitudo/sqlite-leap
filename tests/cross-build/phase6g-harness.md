# Phase 6g test harness — language-neutral spec

Same pipeline as phase 6f. Phase 6g adds no new opcodes or invariants; it extends the value domain (FLOAT_LITERAL token, Value::Real, serial type 7). `max_invariant = 23` on the harness binary.

## Invocation

```
<harness-binary> <path-to-phase6g.json>
```

Generated into `src-{lang}/bin/phase6g-test`.

## Value equality for test comparison

Values in row literals (the test fixture's JSON) are compared as follows:
- JSON integer → Value::Integer; compare by i64 equality.
- JSON number with `.` or exponent → Value::Real; compare by f64 equality via `==` (bit-level for non-NaN is fine; NaN != NaN is honoured; tests don't produce NaN).
- JSON string → Value::Text; compare by byte equality.
- JSON null → Value::Null.

When a test expects a Real result, the fixture MUST write it as a JSON number with a decimal point (e.g. `3.14`, `2.0`, `0.5`) to distinguish from Integer; this is enforced by the test author, not the harness.

## Output

```
SUMMARY phase=6g target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
