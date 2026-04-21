# Phase 6e test harness — language-neutral spec

Identical to `phase6d-harness.md`. Phase 6e adds NO new opcodes. It adds tokens, AST shape (FromSource / QualifiedColumn / JoinKind), and compile-time errors.

## Invocation

```
<harness-binary> <path-to-phase6e.json>
```

Generated into `src-{lang}/bin/phase6e-test`.

## Pipeline per step

Unchanged: tokenize → parse → compile → vdbe.run.

## Well-formedness invariants

Invariants 1–23 unchanged (plus whatever new invariant the 6d regen added if it needed a group-key-equality opcode). 6e itself adds none.

## Equality rules

Row order matters when ORDER BY is present (explicit). Joined output without ORDER BY is in "natural nested-loop order" (outer-rowid-asc × inner-rowid-asc). Tests either pin order with ORDER BY or use single-match-per-outer-row fixtures where the order is unambiguous.

## Output

```
SUMMARY phase=6e target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.
