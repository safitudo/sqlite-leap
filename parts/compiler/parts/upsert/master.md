---
name: compiler/upsert
kind: leaf
inherits:
  - /parts/compiler/parts/statements/insert/master.md
  - /parts/compiler/parts/statements/update/master.md
  - /parts/compiler/parts/expressions/master.md
emits:
  c: { path: src-c/compiler/upsert.c, headers: [src-c/compiler/upsert.h] }
  rust: { path: src-rust/src/compiler/upsert.rs }
---

# Part: compiler/upsert

Compiles the `ON CONFLICT` clause of INSERT statements, a.k.a. the
UPSERT: `INSERT ... ON CONFLICT (col) DO { NOTHING | UPDATE SET ... }`.

## Public interface

```
compile_upsert_tail(
    insert:      &Insert<'src>,
    upsert:      &Upsert<'src>,
    ctx:         &CompileContext,
    program_out: &mut ProgramBuilder,
) -> Result<(), CompileError>
```

Called by `parts/statements/insert/` after the base INSERT opcode
sequence is emitted, when the statement has an ON CONFLICT tail.

## Actions

- **DO NOTHING** — on conflict, skip the current row. Emit a
  jump past the InsertRow opcode keyed on the conflict detection.
- **DO UPDATE SET col = expr, ... [WHERE pred]** — on conflict,
  replace with an UPDATE of the conflicting row. The assignment
  list may reference the EXCLUDED pseudo-table (the row attempted
  to be inserted) via `EXCLUDED.col`.

## EXCLUDED pseudo-source

During DO UPDATE compilation, the NameScope is extended with a
pseudo-source named `EXCLUDED` holding the attempted-insert row's
values in register slots. Expression compilation in the SET and
WHERE clauses resolves `EXCLUDED.col` references to those slots.

## Conflict detection

A conflict is detected when the INSERT would violate a UNIQUE
constraint (PRIMARY KEY, UNIQUE index). The upsert tail runs only
on the violation of a constraint named in the ON CONFLICT `(col)`
target list (or any constraint if the target is empty).

## Phase pins

- **Phase 6bh** — UPSERT (ON CONFLICT DO NOTHING | DO UPDATE SET).
- **Phase 6ab** — INSERT OR REPLACE / OR IGNORE conflict resolution
  (simpler conflict strategy at INSERT level; this sub-part is
  disjoint from that but related).

## Regeneration envelope

- Target leaf size: 300–500 lines per target.
- Spec < 100 lines.
