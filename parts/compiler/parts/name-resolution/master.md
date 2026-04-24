---
name: compiler/name-resolution
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /schema/ast.schema.json
  - /parts/storage/master.md
emits:
  c:
    path: src-c/compiler/name_resolution.c
    headers: [src-c/compiler/name_resolution.h]
  rust:
    path: src-rust/src/compiler/name_resolution.rs
---

# Part: compiler/name-resolution

Resolves column identifiers to `(source_index, column_index)`
tuples. Also owns alias scoping rules across the clauses of a
SelectCore. This sub-part is where **Phase 9h** (name-resolution
error propagation, dual-target pin) lives.

## Public interface

```
resolve_column(
    column_ref:             &ColumnRef<'src>,
    scope:                  &NameScope<'src>,
    clause:                 ClauseKind,      // SelectList | Where | GroupBy | Having | OrderBy | Insert | OnConflict | ...
) -> Result<Resolution, CompileError>

struct Resolution {
    source_index: usize,   // index into scope.sources
    column_index: usize,   // column offset within that source
    lifetime:     'src,    // identifier slices preserved
}
```

Every expression compiler that encounters a `ColumnRef` calls this
function. Name-resolution is NOT inlined into expression
compilation; it is a single authority.

## NameScope

```
struct NameScope<'src> {
    sources:    Vec<Source<'src>>,    // one per FROM source (table, subquery, CTE, VALUES)
    aliases:    Vec<Alias<'src>>,     // SELECT-list aliases
    outer:      Option<&NameScope>,   // correlated parent scope
}

struct Source<'src> {
    name:       &'src str,            // table/CTE name or derived alias
    alias:      Option<&'src str>,    // AS x
    columns:    Vec<ColumnInfo<'src>>,// resolved column schema
    kind:       SourceKind,           // Table | Subquery | Cte | Values | DerivedTable
}

struct Alias<'src> {
    name:       &'src str,            // SELECT expr AS <name>
    expr:       &'src Expression<'src>,
    defines_aggregate: bool,          // for Phase 6cd alias-shadow rule
}
```

## Clause-specific resolution rules

Alias visibility and shadow-tie-breaking vary by clause. The rules:

| ClauseKind | Aliases visible? | On alias-vs-base collision |
|---|:---:|---|
| SelectList | No (being constructed) | n/a |
| Where | No | n/a |
| Join ON | No | n/a |
| GroupBy | **Yes** | **Base column wins** (Phase 6cd) |
| Having | **Yes** | **Base column wins** (Phase 6cd) |
| OrderBy | **Yes** | **Alias wins** (standard SQL) |
| Insert (column list) | No | n/a |
| Upsert excluded | No (refers to EXCLUDED pseudo-source) | n/a |
| Returning | No | n/a |

Caller passes `ClauseKind`. Name-resolution reads the table,
applies the right rule, returns.

## Resolution algorithm

1. **Qualified reference** (`table.col` or `schema.table.col`):
   - Find matching source by alias first, then by table name.
   - If multiple matches → `COMPILE_AMBIGUOUS_TABLE` (e.g.
     self-join without alias).
   - If none → `COMPILE_UNKNOWN_TABLE`.
   - Find column in that source; if missing →
     `STORAGE_COLUMN_NOT_FOUND`.
2. **Unqualified reference** (`col`):
   - If clause allows aliases AND an alias named `col` exists:
     - If ALSO a source has a column named `col`:
       - Apply clause-specific tie-break (table above).
     - Else: use the alias. Substitute alias's expression.
   - Else (aliases not visible OR no matching alias):
     - Look for `col` across all sources.
     - Zero matches → `EVAL_COLUMN_WITHOUT_TABLE` (Phase 9h-named
       condition).
     - Multiple matches → `COMPILE_AMBIGUOUS_COLUMN`.
     - One match → return its `(source_idx, col_idx)`.
3. **Correlated reference** (not found in current scope):
   - Walk `scope.outer` chain. First match returns.
   - Never-matched → the same errors as above, bubbling.

## Alias substitution (not inlining)

When a resolution returns "use alias," the caller does NOT textually
substitute the alias body. Instead, the expression compiler:

- If the alias's expression is a simple `ColumnRef`: emit a direct
  `Column` opcode (or in aggregate context, read the same
  accumulator slot). Cheap.
- If the alias's expression is complex: recompile it in the
  CURRENT clause's context, using a fresh scratch register. This
  means an alias referencing an aggregate gets its aggregate call
  compiled into the SELECT list's accumulator allocation, not a
  duplicate.

For GROUP BY / HAVING with **base column wins** (Phase 6cd): if the
base column exists, the alias is ignored at this position — resolve
to the base column's source.

## Phase 9h — error propagation (dual-target pin)

v1 had three `.expect()` panic sites in `src-rust/src/compiler.rs`
that were hand-edited to structured-error returns on 2026-04-21.
The spec pin lives in this sub-part:

### Condition names

- **`EVAL_COLUMN_WITHOUT_TABLE`** — unqualified column reference
  with zero source matches. Fields: `{name, clause}`.
- **`STORAGE_COLUMN_NOT_FOUND`** — qualified reference where the
  source exists but the column doesn't. Propagated verbatim from
  storage; fields `{table, column}`.
- **`COMPILE_UNKNOWN_TABLE`** — qualified reference where the
  table qualifier doesn't match any source. Fields: `{table}`.
- **`COMPILE_AMBIGUOUS_COLUMN`** — unqualified reference with >1
  source match. Fields: `{name, candidates}`.
- **`COMPILE_AMBIGUOUS_TABLE`** — qualified reference with >1
  source match on the qualifier. Fields: `{table, candidates}`.
- **`RUNTIME_RECURSIVE_CTE_LIMIT`** — recursive CTE depth exceeded.
  Fields: `{cte_name}`. Raised from engine via self-reference
  detection — see `parts/cte/`.

### Dual-target pin

Both C and Rust compilers MUST:

1. Return the same structured condition in the same situation.
2. Never panic / abort / SIGABRT on resolvable resolution failures
   — every failure path returns a structured condition.
3. Emit the name in `kind`, not in prose-formatted message.

The v1 pin fixture `tests/cross-build/phase9h-name-resolution-errors.json`
(14 cases, 5 "Bug A" + 4 "Bug B" + 1 "Bug C" + 4 regression guards)
is the authoritative cross-target check. Under v2 this fixture
moves to this sub-part's `tests/phase9h.json`.

### Why it is a sub-part-level pin

In v1 the fix was a 3-line surgical edit across a 19k-line file.
Under v2 the fix lives explicitly in the name-resolution sub-part's
source, which is a ~500-line file with its own tests. A clean
regeneration of THIS sub-part from this master.md + its tests must
reproduce the fix without hand-editing.

## Phase pins owned here

- **Phase 6aj** — column alias visible in GROUP BY / ORDER BY /
  HAVING.
- **Phase 6cd** — base-column-wins-on-alias-shadow rule for GROUP
  BY / HAVING (alias wins in ORDER BY unchanged).
- **Phase 9h** — name-resolution error propagation dual-target pin
  (detailed above).
- **Phase 6aj AMBIGUOUS_ALIAS cluster** (5 groupby files) — the
  multi-source case where unqualified references to a name that
  exists in both multiple sources AND as an alias raises
  `COMPILE_AMBIGUOUS_COLUMN`, not `COMPILE_AMBIGUOUS_ALIAS`
  (aliases shadow sources only when exactly one source defines
  the column).

## What this part does NOT do

- Compile expressions (expressions calls into this part, not the
  reverse).
- Do any storage I/O beyond the storage-owned schema read
  (`storage.table_schema(name)`). Reads are free, writes are
  forbidden.
- Perform join planning. Source ordering comes from the FROM
  clause as-declared.

## Regeneration envelope

- Target leaf size: 400–700 lines per target.
- Spec size budget: this file < 300 lines.
- Test ownership: `tests/phase9h.json` (v1's 14-case fixture moves
  here), plus per-clause alias fixtures.
