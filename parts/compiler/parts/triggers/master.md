---
name: compiler/triggers
kind: leaf
inherits:
  - /parts/compiler/parts/statements/insert/master.md
  - /parts/compiler/parts/statements/update/master.md
  - /parts/compiler/parts/statements/delete/master.md
  - /parts/compiler/parts/statements/select/master.md
  - /parts/compiler/parts/name-resolution/master.md
  - /parts/storage/parts/triggers/master.md
emits:
  c:    { path: src-c/compiler/triggers.c, headers: [src-c/compiler/triggers.h] }
  rust: { path: src-rust/src/compiler/triggers.rs }
---

# Part: compiler/triggers

Compiles trigger-affected DML by splicing each matching trigger's
body into the host program at the correct point relative to the row
write. Owns three things:

1. **Trigger lookup** — given a `(table, event, timing)` tuple,
   ask the storage trigger registry for the matching `CreateTriggerStmt`
   list (in trigger-creation order — see pin 5).
2. **Body lowering** — for each matched trigger, lower its body
   statements through the host DML compilers, with an active
   `TriggerContext` that resolves `OLD.col` / `NEW.col` to register
   slots holding the pre/post-image of the row.
3. **Splice points** — emit body fragments at four canonical
   splice points relative to the host DML's row-loop: BEFORE-row,
   AFTER-row, INSTEAD-OF-row (replaces the host write entirely),
   and the WHEN-predicate gate that prefixes any of the above.

This part owns NO storage interaction — registration / removal /
enumeration of triggers lives in `/parts/storage/parts/triggers/`.
This part owns NO parser concerns — the AST is consumed as-is from
`/parts/parser/parts/create-trigger-stmt/`.

## Public interface

```
compile_trigger_splice(
    host_event:  TriggerEvent,        # Insert | Delete | UpdateOf{cols}
    host_table:  borrow string,
    splice:      SpliceWhen,          # Before | After | InsteadOf
    ctx:         mut CompileContext,
    triggers:    borrow list<CreateTriggerStmt>,
) -> result<unit, CompileError>
```

`SpliceWhen` is a compiler-local enum (not the parser's TriggerTiming)
because INSTEAD OF is a third splice mode, distinct from
BEFORE/AFTER, that fully replaces the host write.

The host DML compiler calls this once per splice point in the order:

1. Open BEFORE row-loop, before per-row writes:
   `compile_trigger_splice(event, table, Before, ctx, before_triggers)`.
2. If any matching INSTEAD-OF trigger exists (only on views): emit
   the INSTEAD-OF body INSTEAD OF the host's row write, then SKIP
   the host write opcodes.
3. After per-row write: `compile_trigger_splice(..., After, ...)`.

## Trigger context (`OLD` / `NEW` resolution)

```
TriggerContext {
    event:      TriggerEvent,
    timing:     TriggerTiming,
    old_image:  option<list<RegisterSlot>>,   # row before the write
    new_image:  option<list<RegisterSlot>>,   # row after the write
    column_names: list<string>,                # of host_table
    depth:      u32,                           # recursion-guard counter
}
```

Resolution rule for a body-statement column reference `q.c`:

- If `q == "OLD"`: require `old_image.is_some()`, look up column `c`
  by name in `column_names`, emit a Register-copy from
  `old_image[idx]` into the body's expression register.
- If `q == "NEW"`: require `new_image.is_some()`, same as OLD but
  on `new_image`.
- Otherwise: fall through to ordinary name-resolution against the
  host scope (a trigger body MAY reference other tables in the
  schema by their normal names).

## Splice algorithm (pseudo-code)

```
compile_trigger_splice(host_event, host_table, splice, ctx, triggers):
    matched = []
    for tr in triggers:
        if tr.table != host_table: continue
        if !events_compatible(tr.event, host_event): continue
        if !timing_matches(tr.timing, splice):       continue
        matched.push(tr)

    # Mainline-compatible firing order: creation-order. The
    # storage registry is the source of truth for ordering (pin 5).

    for tr in matched:
        if !ctx.recursion_allowed(tr):
            # See pin 7. Default behavior: skip silently.
            continue

        # FOR EACH ROW: emit once per row (we are inside the host
        # row-loop, so a single emission per matched trigger is
        # already once-per-row).
        # Statement-level (not for_each_row): emit OUTSIDE the
        # row-loop. v1 collapses statement-level to row-level
        # semantics — see pin 8.

        bind_old_new(ctx, tr, host_event)

        if tr.when_.is_some():
            emit_when_gate(ctx, tr.when_, skip_label)

        for body_stmt in tr.body:
            compile_body_stmt(ctx.with_trigger_depth(+1),
                              body_stmt, tr)

        emit_label(skip_label)
        unbind_old_new(ctx, tr)

events_compatible(tr_event, host_event):
    # Insert vs Insert, Delete vs Delete: trivial match.
    # UpdateOf vs UpdateOf: match if tr.columns is empty
    # (unrestricted), else if any column in tr.columns appears in
    # the host UPDATE's SET-list. The host compiler passes the
    # actual column set via host_event's UpdateOf payload.
    case (tr_event, host_event):
        (Insert,  Insert):  true
        (Delete,  Delete):  true
        (UpdateOf{tcols}, UpdateOf{hcols}):
            tcols.is_empty() OR any(c in hcols for c in tcols)
        else: false

timing_matches(tr_timing, splice):
    case (tr_timing, splice):
        (Before,    Before):    true
        (After,     After):     true
        (InsteadOf, InsteadOf): true
        else: false
```

## OLD / NEW availability table

| Event   | OLD | NEW |
|---------|-----|-----|
| INSERT  | no  | yes |
| DELETE  | yes | no  |
| UPDATE  | yes | yes |

A body's reference to an unavailable side raises
`COMPILE_TRIGGER_OLD_UNAVAILABLE` or `COMPILE_TRIGGER_NEW_UNAVAILABLE`.

## Recursive-trigger semantics

SQLite has a `recursive_triggers` PRAGMA, default OFF. With it OFF,
a trigger body whose statements would activate the SAME trigger
(directly or transitively) skips that activation silently. With it
ON, recursion proceeds up to a depth limit (`MAX_TRIGGER_DEPTH`,
defined in `/parts/storage/parts/triggers/`).

Implementation:

- `CompileContext` carries `trigger_stack: list<TriggerName>`,
  capturing the chain of triggers currently being compiled.
- Before splicing a trigger `tr`: if `tr.name` is already in
  `trigger_stack` AND `pragma.recursive_triggers == false`, skip;
  ELSE if depth `>= MAX_TRIGGER_DEPTH`, raise
  `COMPILE_TRIGGER_DEPTH_EXCEEDED`; ELSE push and proceed.
- On exit, pop.

## Cascade and cross-table writes

A trigger body MAY modify tables OTHER than `host_table`. Those
modifications are themselves DML statements that activate further
triggers per the rules above. Compilation is therefore inherently
recursive and the recursion guard (above) is mandatory. Each cascade
runs in the SAME connection and SAME transaction as the host
statement; rollback semantics are inherited unchanged.

## Phase pins

- **Phase 7t-1** — trigger lookup + INSERT-only AFTER splice.
- **Phase 7t-2** — full timing matrix + UPDATE/DELETE.
- **Phase 7t-3** — recursive-trigger guard + depth limit.

## Correctness pins

1. **Splice point matches timing** — BEFORE triggers compile into
   the program ABOVE the host DML's row-write opcodes; AFTER
   triggers compile BELOW; INSTEAD OF triggers REPLACE the host
   write entirely (host compiler skips its own write opcodes).
2. **Firing order is creation-order** — multiple triggers matching
   the same `(table, event, timing)` fire in the order in which
   they were registered (the order
   `/parts/storage/parts/triggers/list_triggers_for_table`
   returns). Behavioral compatibility with mainline SQLite.
3. **WHEN evaluated AT splice time, NOT registration time** — the
   WHEN predicate compiles into a body-prefix conditional jump
   that, when false, skips the rest of THAT trigger's body but does
   NOT skip subsequent triggers' bodies at the same splice point.
4. **WHEN sees the same OLD/NEW as body** — for AFTER triggers,
   WHEN sees post-image NEW; for BEFORE triggers, WHEN sees
   pre-image NEW (because BEFORE may itself mutate the row before
   the host write commits). The OLD/NEW availability table applies
   identically to WHEN.
5. **OLD column read-only at compile time** — a body statement that
   tries to ASSIGN OLD.col (e.g. `UPDATE t SET a = 1` where `t` is
   the host table and OLD is bound) compiles, but at the resolution
   step, an OLD.col on the LHS of an assignment is
   `COMPILE_TRIGGER_OLD_NOT_ASSIGNABLE`. NEW.col on the LHS is
   permitted ONLY for BEFORE triggers (where the row is not yet
   committed); for AFTER triggers it is
   `COMPILE_TRIGGER_NEW_NOT_ASSIGNABLE_AFTER`.
6. **INSTEAD OF only on views** — at compile-time the host
   compiler MUST pass the host object kind. If `splice == InsteadOf`
   and the host object is a TABLE (not a view), raise
   `COMPILE_TRIGGER_INSTEAD_OF_ON_TABLE`. The published grammar
   rejects this; we enforce in the compiler so that the parser
   stays language-neutral and free of schema lookups.
7. **Recursion guard default OFF** — without
   `pragma.recursive_triggers = on`, a trigger that would activate
   itself (directly or transitively) is silently skipped at the
   self-activation point. With it ON, depth is bounded by
   `MAX_TRIGGER_DEPTH`; exceeding that raises
   `COMPILE_TRIGGER_DEPTH_EXCEEDED`.
8. **Statement-level vs row-level** — v1 implements only
   `for_each_row == true` semantics. A trigger declared without
   `FOR EACH ROW` is admitted by the parser but compiled as if
   `for_each_row == true`. A future revision may emit a single
   pre/post-loop splice for true statement-level; we record the
   parsed flag now to make that change additive.
9. **UPDATE OF column-set match** — when the trigger event is
   `UpdateOf { columns: [c1, c2] }`, the trigger fires only if the
   host UPDATE's SET-list mentions at least one of `c1, c2`. Empty
   trigger column-list (`UpdateOf { columns: [] }`) means "any
   column" and always fires on UPDATE.
10. **Cross-table cascade** — a trigger body MAY contain DML on
    tables other than `host_table`; each such statement is compiled
    through its normal DML path with the trigger context still
    active. The trigger context's `column_names` refers to
    `host_table` ONLY — name-resolution inside the body for tables
    other than the host falls through to ordinary scope.
11. **Owned-string rule** — every name carried in TriggerContext
    (table, column names) is owned. The body AST is borrowed from
    the storage registry for the duration of compilation; bodies
    are NOT cloned per emission.
12. **No inline tests, no invented helpers** — this leaf exports
    only `compile_trigger_splice`, `TriggerContext`, `SpliceWhen`,
    and `bind_old_new` / `unbind_old_new`. It does not re-implement
    any DML compiler logic; it dispatches.
13. **Trigger body diagnostics carry trigger name** — every
    `CompileError` raised while lowering a trigger body is
    annotated with the surrounding trigger's name (a
    `trigger_context: option<string>` field on `CompileError`),
    so failures point at the right source.
14. **No spec leak of allocator/lifetime idiom** — `TriggerContext`
    is described as a record-of-references; targets choose the
    concrete representation (Rust borrow, C pointer, etc.). No
    target-specific lifetime annotation appears in this spec.
15. **DROP TABLE semantics** — when the storage layer drops a
    table, every trigger whose `table` field equals the dropped
    name is unregistered (see
    `/parts/storage/parts/triggers/master.md` pin 9). This part
    therefore does NOT need to handle the case of a trigger whose
    target table no longer exists — the registry never returns one.
16. **DROP TRIGGER semantics** — same as DROP TABLE: the
    trigger ceases to be returned by lookups; in-flight
    compilations are unaffected (the borrowed AST list stays valid
    for the duration of one compilation).
17. **Connection scope** — triggers live on the database, not the
    connection; a trigger created on connection A is visible to
    connection B once the creating transaction commits. This part
    does not enforce this — it assumes the storage registry is
    consistent at compile time.
18. **Transaction scope** — a trigger body's writes participate
    in the same transaction as the host DML. Rollback of the host
    statement rolls back every trigger body cascade. This part
    requires no opcode emission for transaction control — the
    host already manages it.
19. **RETURNING interaction** — a host DML's RETURNING clause
    sees the post-image AFTER all matching AFTER-triggers run.
    The compile order therefore is: BEFORE → host write →
    AFTER → RETURNING. v1 may defer this composition with
    `COMPILE_TRIGGER_RETURNING_DEFERRED` if the host compiler
    is not yet wired for it.
20. **Empty matched-list is a no-op** — if no triggers match a
    given splice point, this part emits zero opcodes. The host
    compiler's row-write path is unchanged.

## Regeneration envelope

- Target leaf size: 400–700 lines per target.
- Spec under 250 lines.
- Public items: `compile_trigger_splice`, `TriggerContext`,
  `SpliceWhen`, plus the named CompileError variants.
