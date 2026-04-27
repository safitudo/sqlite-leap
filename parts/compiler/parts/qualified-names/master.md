---
name: compiler/qualified-names
kind: leaf
shapes: ./shapes.json
inherits:
  - /parts/compiler/parts/name-resolution/master.md
  - /parts/storage/parts/multi-db/master.md
---

# Part: compiler/qualified-names

Schema-prefix resolution for every name reference in a compiled
statement. Bridges parser-level identifiers
(`schema.table.column`, `table.column`, bare `column`) to
storage-level slot indices and per-slot table descriptors.

This part owns the **resolution algorithm only** — the catalog
itself lives in `/parts/storage/parts/multi-db`, and the
column-binding inside a single table is the existing
`/parts/compiler/parts/name-resolution`. This part stitches the
two together.

## Why a dedicated part

Once the catalog admits more than one schema, every existing
compiler that handled bare or `table.column` references must
also accept `schema.table.column`. The scope of that change
spans select-compile, insert-compile, update-compile,
delete-compile, expr-compile, joins, subqueries, returning, cte,
and views. Centralizing the prefix-walk here keeps that change
small in each consumer: each consumer calls
`resolve_qualified_name` and gets back a uniform descriptor.

It also concentrates the **detach-stability** invariant: slot
indices are NOT stable across detach
(`/parts/storage/parts/multi-db` pin 11), so the compiler MUST
re-resolve at every statement boundary. Concentrating the call
site makes the invariant easy to audit (pin 13).

## Resolution inputs

- `catalog: borrow DbCatalog` — read-only view of the
  connection's schema catalog.
- `name: QualifiedName` — the parser's three-part identifier
  (each part present|absent).
- `context: ResolutionContext` — the FROM-clause's currently
  in-scope tables (driven by name-resolution), the current
  statement's TEMP-binding rules, and a hint of whether the
  caller is resolving a TABLE position or an EXPR position.

## QualifiedName shape

```
QualifiedName ::= { schema (present|absent),
                    qualifier (present|absent),
                    leaf }
```

Surface mappings from the parser:
- `column` → `{ schema=absent, qualifier=absent, leaf="column" }`
- `t.column` → `{ schema=absent, qualifier="t", leaf="column" }`
- `s.t.column` → `{ schema="s", qualifier="t", leaf="column" }`
- `t` (in TABLE position) →
  `{ schema=absent, qualifier=absent, leaf="t" }` — the resolver
  reads `context.position` to know `leaf` is a TABLE name.
- `s.t` (in TABLE position) →
  `{ schema="s", qualifier=absent, leaf="t" }`.

## Resolution outputs

```
ResolvedRef ::=
  | Table { schema_idx, table_idx_in_schema }
  | Column { schema_idx, table_idx_in_schema, column_idx }
  | Error { kind, hint }
```

Compilers consume `Table` for FROM clauses, INSERT/UPDATE/DELETE
target tables, and RETURNING subjects; they consume `Column`
everywhere else.

## Walk algorithm

The resolver walks slots in the order returned by
`catalog_walk_unqualified`: `[main, temp, attached-by-attach_seq-asc]`.

```
resolve_qualified_name(catalog, name, context):
    case name:
        # explicit schema prefix
        { schema=present(s), qualifier=present(q), leaf=l }:
            slot = catalog.resolve(s)?         # SchemaNotFound on miss
            t    = lookup_table(slot, q)?      # TableNotFound on miss
            c    = lookup_column(t, l)?        # ColumnNotFound on miss
            return Column(slot, t, c)

        { schema=present(s), qualifier=absent, leaf=l }:
            slot = catalog.resolve(s)?
            if context.position == TABLE:
                t = lookup_table(slot, l)?
                return Table(slot, t)
            else:
                # `s.col` is NOT a valid expression form.
                return Error("ambiguous: schema.column without table")

        # implicit: try in-scope FROM aliases first, then walk
        { schema=absent, qualifier=present(q), leaf=l }:
            # FROM-scope alias takes priority (mainline parity).
            if context.from_alias_to_table.contains(q):
                (slot, t) = context.from_alias_to_table[q]
                c = lookup_column(t, l)?
                return Column(slot, t, c)
            # otherwise q is a table name to walk slots for.
            for slot in catalog.walk_unqualified():
                if slot has table named q:
                    if context.position == TABLE: return Table(slot, t)
                    c = lookup_column(t, l)?
                    return Column(slot, t, c)
            return Error("no such table", hint=q)

        { schema=absent, qualifier=absent, leaf=l }:
            if context.position == TABLE:
                # bare table reference
                for slot in catalog.walk_unqualified():
                    if slot has table named l:
                        return Table(slot, t)
                return Error("no such table", hint=l)
            # bare column: scan FROM-scope tables in order
            matches = []
            for (slot, t) in context.from_tables:
                if t has column named l:
                    matches.push((slot, t, c))
            if matches.len() == 0: return Error("no such column", hint=l)
            if matches.len() >= 2: return Error("ambiguous column", hint=l)
            return Column(matches[0])

        # impossible per parser: leaf is always present
```

`lookup_table(slot, name)` and `lookup_column(table, name)` are
**case-folded ASCII** lookups (mainline parity for unquoted
identifiers; quoted identifiers compare bytewise as the
tokenizer already canonicalized).

## Correctness pins

1. **Walk order is the catalog's order** — exactly the sequence
   returned by `catalog_walk_unqualified`:
   `main → temp → attached-by-attach_seq-asc`. The resolver
   does NOT reorder; it does NOT skip; it does NOT cache the
   order across calls.
2. **First-hit-wins for unqualified table refs** — the FIRST
   slot in walk order that contains a table with the given
   name resolves the reference. Subsequent slots are not
   examined. This mirrors mainline behavior:
   `SELECT * FROM t` finds `main.t` before `temp.t` before
   `attached.t`.
3. **Explicit schema prefix is exact** — `schema.table.column`
   resolves ONLY in `schema`'s slot. If `schema` is bound but
   has no `table`, raise `TableNotFound { schema }`. The
   resolver does NOT fall back to other slots.
4. **TEMP shadowing for TEMPORARY tables** — a `CREATE TEMP
   TABLE t` writes into slot 1 (temp). A subsequent
   `CREATE TABLE t` (no schema prefix) writes into slot 0
   (main). An unqualified `SELECT * FROM t` resolves to
   `main.t` first (walk order). To address the temp table the
   user MUST use `temp.t`. This is mainline behavior; the
   resolver does NOT "prefer temp."
5. **FROM-alias priority over schema walk** —
   `SELECT s.x FROM other AS s` resolves `s.x` against the
   `other` table aliased as `s`, NOT against a schema named
   `s`. The from_alias_to_table map in
   `ResolutionContext` is consulted FIRST when
   `qualifier=present`. Only when no alias matches does the
   resolver treat `qualifier` as a table name to walk for.
6. **Bare column ambiguity is an error** — when more than one
   in-scope FROM table has a column with the given leaf name,
   raise `AmbiguousColumn { hint=leaf }`. Mainline parity.
7. **Case-folded ASCII compare** — schema names, table names,
   column names, and FROM aliases are compared with ASCII
   case-folding (`A-Z` → `a-z`); bytes ≥ 0x80 compare bytewise.
   Matches the tokenizer's identifier canonicalization.
8. **Reserved schema names recognized** — `main` and `temp`
   resolve to slots 0 and 1 respectively, regardless of input
   case. There is no separate fast path; both go through
   `catalog.resolve`, which knows the reserved indices.
9. **Schema name in EXPR position requires qualifier** — a
   bare `s.col` (schema + leaf, no table) is an error.
   Mainline rejects this; the resolver raises
   `MissingTableQualifier { schema=s, leaf=col }`. Compilers
   producing diagnostic messages may rename this for the user
   ("did you mean s.t.col?").
10. **No silent fallback across slots on explicit prefix** —
    `bad_schema.t.c` does NOT walk other slots when
    `bad_schema` is unbound; it raises `SchemaNotFound`. This
    is testable: a test fixture binds only `main` + `temp` and
    expects `bad.t.c` to raise SchemaNotFound, not
    NoSuchColumn.
11. **Compiler must NOT cache SchemaIdx across statements** —
    the resolver MUST re-call `catalog_resolve` at every
    statement boundary. Caching across statements violates
    `/parts/storage/parts/multi-db` pin 11 because a `DETACH`
    between two prepared-statement executes can compact slot
    indices.
12. **Within a single statement compile, SchemaIdx IS stable**
    — the catalog forbids `catalog_attach` / `catalog_detach`
    inside a transaction (multi-db pin 10), and the compiler
    runs entirely inside a transaction-scoped pass. Caching
    SchemaIdx for the duration of one statement compile is
    therefore safe and required (avoid O(refs) catalog
    lookups).
13. **Re-resolution gate** — every consumer
    (select-compile, insert-compile, update-compile,
    delete-compile, expr-compile, joins, subqueries,
    returning, cte, views) calls `resolve_qualified_name` —
    none caches a `(schema_name → SchemaIdx)` map across
    consumers. Audit checklist for the regen-debt sweep.
14. **Cross-schema FK reference detected here** — when
    name-resolution sees a foreign-key REFERENCES clause whose
    target table resolves to a different `schema_idx` than the
    enclosing CREATE TABLE's schema, the compiler emits a
    `CrossSchemaForeignKey` diagnostic that the DDL executor
    (multi-db pin 13) refuses to install. The compiler never
    produces an opcode that would attempt the cross-schema FK.
15. **Language-neutral signature** — `QualifiedName`,
    `ResolvedRef`, and `ResolutionContext` are abstract
    records / variants. No mention of Rust `Cow`, no `char *`,
    no target allocator. The resolver's pseudo-code uses
    only constructs admitted by `/spec/type-system.spec.md`.
16. **No inline tests, no invented helpers** — the public
    surface is `resolve_qualified_name` plus the records /
    variant. Catalog mutation, parser AST construction, and
    column-binding helpers are imported from their owning
    parts (multi-db, parser, name-resolution).

## Regeneration envelope

- Line budget: ~250-400 lines per target. The walk is short;
  most of the volume is the case-fold helpers and the error
  enrichment.
- Imports: `DbCatalog`, `SchemaIdx` from multi-db; the existing
  `name-resolution` table-descriptor lookup helpers.
- Public items: `QualifiedName`, `ResolvedRef`,
  `ResolutionContext`, `resolve_qualified_name`.

## Smoke probes (cross-target)

```text
1. SELECT * FROM main.t            → resolves to (main, t)
2. SELECT * FROM t   (only main.t) → resolves to (main, t) via walk
3. SELECT * FROM t   (main.t + temp.t) → resolves to (main, t) (walk order)
4. SELECT temp.t.c FROM temp.t     → resolves to (temp, t, c)
5. SELECT bad.t.c FROM main.t      → SchemaNotFound { schema='bad' }
6. SELECT main.bad.c FROM main.t   → TableNotFound { schema='main' }
7. SELECT a.x FROM main.t1 AS a    → resolves alias a, NOT schema a
8. SELECT s.col FROM main.t        → MissingTableQualifier
9. CREATE TABLE main.t (a REFERENCES other.tt(b))
                                   → CrossSchemaForeignKey
```
