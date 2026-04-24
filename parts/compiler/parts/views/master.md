---
name: compiler/views
kind: leaf
inherits:
  - /parts/compiler/parts/statements/select/master.md
  - /parts/compiler/parts/name-resolution/master.md
  - /parts/storage/master.md
emits:
  c: { path: src-c/compiler/views.c, headers: [src-c/compiler/views.h] }
  rust: { path: src-rust/src/compiler/views.rs }
---

# Part: compiler/views

Expands view references at compile time. A view is a stored
SELECT; referencing the view is equivalent to inlining its SELECT
into the referencing query as a derived table.

## Public interface

```
expand_view_reference(
    view_name:   &str,
    scope:       &NameScope<'src>,
    ctx:         &CompileContext,
) -> Result<DerivedSource, CompileError>
```

Called by `parts/statements/select/` (and any other statement that
accepts a table reference) when name-resolution identifies a source
as a view.

## Expansion algorithm

1. Read the view's stored SELECT text from storage (`sqlite_master`
   / `sqlite_schema`).
2. Tokenize + parse the stored text into a local AST.
3. Compile the AST through the SELECT statement path, producing a
   derived-table sub-program.
4. Wire it in at the call site as a derived source, taking its
   column names from the view's declared column list (or the
   inner SELECT's projection names if undeclared).

View expansion is recursive — a view that references another view
expands transitively. Infinite-recursion guard: compile-time cycle
detection, raise `COMPILE_VIEW_CYCLE` if a view expands (directly
or transitively) to itself.

## View creation / drop

`CREATE VIEW` and `DROP VIEW` are handled by
`parts/statements/create-view/` and `parts/statements/drop/`
respectively. This sub-part is READ-ONLY — it only expands
existing views for downstream statements.

## Phase pins

- **Phase 6ac** — CREATE VIEW / DROP VIEW (owned by statement
  sub-parts; this sub-part is the expansion counterpart).
- **#122/#130** — VIEW read path consolidated from v1's
  `view_subst.rs` (Rust) and `src-c` VIEW code into this
  compile-time expander.

## Regeneration envelope

- Target leaf size: 300–500 lines per target.
- Spec < 150 lines.
