---
name: compiler
kind: inner
inherits:
  - /spec/memory-discipline.spec.md
  - /schema/ast.schema.json
  - /schema/program.schema.json
  - /schema/opcode.schema.json
  - /parts/parser/master.md
  - /parts/vdbe/master.md
  - /parts/storage/master.md
emits:
  c:
    path: src-c/compiler/mod.h
  rust:
    path: src-rust/src/compiler/mod.rs
---

# Part: compiler

Consumes an AST. Produces a well-formed VDBE Program per
`/schema/program.schema.json`. The compiler is **inner** — it
decomposes along SQL-feature lines, not statement-kind lines, with
cross-feature sub-parts (expressions, aggregates, joins, etc.)
called by per-statement sub-parts.

## Public interface

- **Input:** `ast: Ast<'src>`, `storage_handle: ReadOnlyStorage`.
- **Output on success:** `Program<'src>` satisfying every
  well-formedness invariant declared in `parts/vdbe/master.md`.
- **Output on failure:** one of the structured error conditions
  declared per sub-part. Compiler-level errors visible in the
  public interface:
  - `STORAGE_TABLE_NOT_FOUND` / `STORAGE_COLUMN_NOT_FOUND` /
    `STORAGE_DUPLICATE_COLUMN` — propagated verbatim from storage.
  - `COMPILE_UNKNOWN_TABLE` — a FROM/INSERT/UPDATE table reference
    that storage returned not-found for.
  - `COMPILE_AMBIGUOUS_COLUMN` — multi-source reference resolvable
    to more than one column.
  - `EVAL_COLUMN_WITHOUT_TABLE` — a column reference that does not
    resolve to any known source at compile time.
  - `COMPILE_NESTED_AGGREGATE` — aggregate inside aggregate, never
    legal.
  - Plus per-sub-part conditions (see each child's master.md).

## Sub-part map

Per-statement (call-graph roots):

- `parts/statements/select/` — `SelectFrom` AST → Program.
- `parts/statements/insert/` — `Insert` AST → Program.
- `parts/statements/update/` — `Update` AST → Program.
- `parts/statements/delete/` — `Delete` AST → Program.
- `parts/statements/create-table/`, `create-index/`, `create-view/`,
  `drop/`, `alter-table/`, `pragma/` — DDL + PRAGMA.

Cross-feature (called by statement sub-parts):

- `parts/expressions/` — `Expression` AST → opcode sequence leaving
  value in a dest register. Called everywhere an expression appears.
- `parts/name-resolution/` — column identifier → `(source_index,
  column_index)` resolution. Owns alias scoping, shadow rules,
  ambiguity detection. See "Phase 9h pin" below.
- `parts/aggregates/` — GROUP BY / HAVING / aggregate function
  compilation.
- `parts/joins/` — INNER/LEFT/CROSS/NATURAL/USING join planning.
- `parts/subqueries/` — scalar/IN/EXISTS subqueries + correlated
  scope capture.
- `parts/cte/` — WITH and WITH RECURSIVE bindings.
- `parts/window/` — OVER clauses, ROW_NUMBER, frame ops.
- `parts/views/` — view expansion at compile time.
- `parts/upsert/` — ON CONFLICT DO NOTHING | DO UPDATE SET.
- `parts/returning/` — RETURNING clause on INSERT/UPDATE/DELETE.
- `parts/constraints/` — CHECK, NOT NULL, UNIQUE enforcement
  emission.

## Cross-sub-part invariants (owned here, not inside children)

### Register allocation

Registers are a flat, contiguous, compile-time-decided array. Every
sub-part that needs registers receives a `RegAllocator` handle from
its caller and allocates via `next_register()` / `next_range(n)`.
Registers are never reused across the compile of a single
statement. `num_registers` in the emitted Program is the high-water
mark.

### Cursor allocation

Cursors are allocated similarly, one per referenced table or index.
Allocation is per-statement. `num_cursors` in the emitted Program
is the count.

### Well-formedness

Every emitted Program MUST:

- End with exactly one `OpHalt`.
- Have no opcodes after `OpHalt` in the main body.
- Have all register indices in `[0, num_registers)`.
- Have all cursor indices in `[0, num_cursors)`.
- Have all jump targets referencing valid opcode indices in the
  same program body.
- Preserve identifier case exactly as seen in the AST.

Sub-parts MUST NOT emit Programs violating these; the parent
composer validates after each sub-part returns.

### Expression dest-register protocol

`parts/expressions/` compiles an expression into a reg. The caller
passes a desired dest register (via the allocator) and the
expression compiler emits opcodes that leave the value in that
register. Subexpressions use caller-owned scratch registers
allocated by the expressions sub-part internally.

### Aggregate boundary

Aggregate expressions are legal ONLY in the SELECT list and HAVING
clauses of a GROUP BY / implicit-GROUP-BY SELECT. Other positions
(WHERE, ORDER BY on non-aggregated outer context, JOIN ON) reject
with `COMPILE_NESTED_AGGREGATE` or the appropriate sub-part
condition. `parts/expressions/` delegates to `parts/aggregates/`
when it encounters an `AggregateCall` AST node.

### Name-resolution handoff

Whenever an expression compiler (any sub-part) encounters a
`ColumnRef` AST, it delegates resolution to
`parts/name-resolution/`. Resolution is deterministic:
`(source_index, column_index)` or a structured error. Sub-parts do
not implement their own name resolution — the Phase 9h fix lives in
that one sub-part.

## Phase pins (active)

- **Phase 6aj** — column alias visible in GROUP BY / ORDER BY /
  HAVING, with base-column-wins-on-alias-shadow rule (Phase 6cd).
  Owner: `parts/name-resolution/`.
- **Phase 6bo** — bare-column-in-GROUP-BY. Owner:
  `parts/aggregates/`.
- **Phase 9h** — name-resolution error propagation dual-target pin.
  Owner: `parts/name-resolution/`.
- **Phase 2c-3** — UPDATE duplicate-column rightmost-wins. Owner:
  `parts/statements/update/`.

Each phase pin's detailed semantics live in the owning sub-part's
`master.md`. This list exists for cross-reference.

## What this part does NOT do

- Execute programs (VDBE owns execution).
- Mutate storage (read-only access during compile).
- Plan index use beyond the minimum needed for well-formedness (no
  cost-based optimization; planner lives in a future sub-part if at
  all).
- Perform optimizations beyond what's required by tests.

## Composition

Each leaf sub-part emits its own module file at
`emits.<target>.path`. This part's generator produces a `mod.rs`
(Rust) that `pub mod`s each sub-part and re-exports the public
compile functions, plus an `entry()` function that dispatches on
AST kind to the matching statement sub-part. For C, it produces an
aggregating header and a `compile()` dispatch function.
