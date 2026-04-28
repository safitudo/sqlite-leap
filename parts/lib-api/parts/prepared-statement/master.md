---
name: lib-api/prepared-statement
kind: leaf
emits:
  rust:   { path: src-rust/lib_api/prepared_statement.rs }
  c:      { path: src-c/lib_api/prepared_statement.c, headers: [src-c/lib_api/prepared_statement.h] }
  zig:    { path: src-zig/lib_api/prepared_statement.zig }
  go:     { path: src-go/lib_api/prepared_statement.go }
  python: { path: src-python/lib_api/prepared_statement.py }
---

# Prepared statement: prepare / bind / step / reset

A prepared statement is the canonical "compile once, execute many"
surface. The user calls `prepare(db, sql)` to parse + compile +
arity-determine; `bind(stmt, slot, value)` to install one or more
bind-parameter values; `step(stmt, db)` to advance the program (a
single-shot statement runs to Halt; a row-producing statement may
emit a row and pause); `reset(stmt)` to rewind without re-preparing.

Bench-validated: on the Rust target, this surface lifts Lane 4
(INSERT throughput, single writer) from 98k ips (re-prepare-per-
INSERT) to 2.58M ips (prepare once + 1M binds-and-steps). Mainline
SQLite at the same workload is 1.33M ips; the prepared-statement
surface is 1.94× faster than mainline.

## Scope (v1)

Admitted:

- `prepare(db, sql)` — parses SQL via `/parts/parser`, dispatches to
  the matching statement compiler, computes the statement's arity
  (count of distinct anonymous `?` placeholders observed during
  parse), and returns a `PreparedStatement` carrying the compiled
  Program plus that arity.
- `bind(stmt, slot, value)` — installs `value` at the 1-based slot
  index. Slot 0 or > arity is `BindError::SlotOutOfRange`.
- `step(stmt, db)` — runs the statement's Program against a fresh
  VdbeState (or a state cached on the statement; see Pin 7) seeded
  with the current bindings. Returns `StepResult::Row` for each
  emitted row, `StepResult::Done` on Halt(Ok), and
  `StepResult::Error(condition)` on any RuntimeCondition that
  bubbles up from execute_program.
- `reset(stmt)` — discards the per-step VdbeState (PC, cursors, any
  per-step buffer slots, aggregate / window slots). Bindings are
  PRESERVED; the next step starts from PC 0 with the same params
  vector.

Deferred:

- Named (`:name`, `@name`, `$name`) and explicitly-numbered (`?N`)
  parameters — parser admits anonymous `?` only in v1.
- A `finalize` step distinct from drop/destruct — v1 lets the target
  language's drop / GC / dispose path own teardown. Targets that
  need an explicit `finalize` may map it to a no-op wrapper.
- `column_name(stmt, i)` / `column_count(stmt)` introspection
  helpers — out of scope for the bench-driving surface; follow-up.
- Multi-step transaction / savepoint composition — covered by the
  underlying VDBE's existing transactional opcodes; lib-api does
  not yet expose the savepoint surface.

## Declared shapes (`shapes.json`)

- `PreparedStatement { program: Program, arity: u32 }` — the
  compiled bytecode plus the bind-parameter slot count. The bound
  values themselves live on the per-step VdbeState; see Pin 7 for
  why this is a deliberate split.
- `BoundParams { values: list<Value> }` — a wrapper around the
  caller-side params vector. Sized to `arity` at prepare time;
  unbound slots default to `Value::Null` (Pin 3).
- `StepResult` — variant: `Row | Done | Error(RuntimeCondition)`.
- `PrepareError` / `BindError` / `StepError` — variant types
  surfacing the failure modes (parse, compile, slot-out-of-range,
  runtime).
- Functions `prepare`, `bind`, `step`, `reset`.

## Algorithm

### `prepare(db, sql)`

```
tokens = tokenize(sql)
parsed = parse_statement(tokens)         # may produce ParseError
arity  = count_distinct_param_placeholders(parsed)
                                          # walk the AST; for SELECT,
                                          # walks projection +
                                          # FROM derived + WHERE +
                                          # ORDER BY etc.; for
                                          # INSERT walks VALUES +
                                          # column-list-bearing
                                          # subSELECT; etc.
program = compile_statement(parsed, db.schema_registry)
                                          # may produce CompileError
return Ok(PreparedStatement { program, arity })
```

The parser already assigns each anonymous `?` a 1-based `idx` in
left-to-right source order (see `/parts/parser/parts/expr` Pin on
`Expr::Param`); `arity` is `max(observed idx values)` over the
walked AST, or 0 if no placeholders appear.

### `bind(stmt, params, slot, value)`

```
if slot < 1 or slot > stmt.arity:
    return Err(BindError::SlotOutOfRange { slot, arity: stmt.arity })
params.values[slot - 1] = value
return Ok(())
```

Caller is responsible for keeping the `params` value alive across
steps (see Pin 7 for the binding-vs-state split).

### `step(stmt, params, db)`

```
state = VdbeState::new(
    stmt.program.num_registers,
    stmt.program.num_cursors,
    stmt.program.num_aggregates,
    stmt.program.num_windows,
    db
)
state.set_params_arity(stmt.arity)
for slot in 1..=stmt.arity:
    state.set_param(slot, params.values[slot-1].clone())

# Drive execute_program; intercept ResultRow via the program's row_sink
# so the caller (or the lib-api wrapper) sees one Row per emitted row.
status = execute_program(&stmt.program, &mut state)
match status:
    HaltStatus::Ok           -> StepResult::Done
    HaltStatus::Row          -> StepResult::Row    (with row materialized into a caller-visible buffer; see Pin 6)
    HaltStatus::Error(cond)  -> StepResult::Error(cond)
```

In v1 the `step` API runs the program to its terminal Halt(Ok) and
returns `Done`; row materialization happens via the existing
`row_sink` callback the Program carries (the lib-api supplies a
sink that pushes each row into a per-statement vector the caller
reads via a sibling `current_row(stmt)` helper). An iterator-style
`step → Row | Done | Error` surface that pauses the program at each
ResultRow is admitted as a v1.1 follow-up; the spec captures the
intent here so target mappings can choose the canonical surface
without spec-shape change.

### `reset(stmt, state)`

```
state.set_pc(0)
for c in 0..stmt.program.num_cursors:
    state.take_cursor(c)        # idempotent close; storage releases
# aggregate / window slots are reinitialized lazily on next step
# (the per-kind init is idempotent under set_params_arity-equivalent
# rules in the existing VDBE state)
# bindings are NOT touched; params vector is preserved by contract
```

After `reset`, the next `step` re-issues the program from PC 0 with
the same bindings. Cursor handles are released so the program's
own `OpenRead`/`OpenWrite` re-opens them fresh.

## Correctness pins

1. **`prepare(sql)` parses + compiles + computes arity.** Arity is
   the max 1-based `idx` observed across every `Expr::Param` node in
   the parsed AST; 0 if none. Identical SQL text always yields the
   same arity.
2. **`bind(slot, value)` is 1-based.** Slot 0 is rejected; slot >
   arity is rejected with `BindError::SlotOutOfRange`. Slot in
   [1, arity] succeeds; the prior value at that slot (if any) is
   replaced.
3. **`step` requires arity bindings; missing bindings default to
   NULL.** When `step` initializes the per-state params vector via
   `set_params_arity(stmt.arity)`, every slot is initialized to
   `Value::Null`; the caller's bind calls overwrite. A statement
   that never had any of its slots bound runs with all-Null
   parameters — matches SQLite semantics.
4. **`reset` rewinds PC + cursors + clears any per-step state but
   preserves bindings.** PC = 0; every open cursor is taken (and
   storage releases the handle); aggregate / window slots are
   reset; **the params vector is NOT cleared**. A subsequent `step`
   re-runs with the same bindings.
5. **`BindParam` opcode reads `state.params[slot-1]` into
   `registers[dest_reg]`.** The opcode is the only way the program
   observes binding state. Slot 0 or slot > params_len at execute
   time Halts with `Error(OpcodeIllegal)` — the compiler's prepare
   phase pins arity, so a well-formed program never hits this.
6. **Rebind-then-step is idempotent for repeatable-execution
   semantics.** A caller that does `prepare; bind(1, A); step;
   reset; bind(1, A); step` MUST observe the same row outputs (and
   side-effect set, for INSERT/UPDATE/DELETE on a checkpointed
   storage state) as a caller that does `prepare; bind(1, A); step;
   reset; step`. Said differently: rebinding the same value is a
   no-op at the program-input level. This pins the semantics:
   bindings are positional values, not opaque tokens.
7. **Bindings live OUTSIDE the per-step VdbeState.** The `bind` API
   updates a caller-side `BoundParams { values }` vector; `step`
   copies the values into a fresh VdbeState's params slot vector via
   `set_params_arity` + per-slot `set_param`. This split is
   deliberate: it lets `reset` discard the entire VdbeState (the
   simplest, fastest reset path) without losing bindings, and it
   mirrors SQLite's `sqlite3_bind_*` (lives on the statement) /
   `sqlite3_reset` (clears state, preserves bindings) semantics.
   Targets MAY collapse the two in a target-idiomatic way (e.g. a
   Rust `PreparedStatement` may own both the program and a `Vec<
   Value>` of bindings, calling `step(&db) -> StepResult` directly)
   so long as Pins 1–6 hold observable.

8. **Auto-prepare INSERT-VALUES cache (per-connection).** When a
   connection's eager-execute API (the path that takes a raw SQL
   string and runs it end-to-end without an explicit prepare/bind/
   step ceremony) receives an INSERT statement matching the shape

       INSERT INTO <ident> [(<column>, ...)] VALUES (<lit>, ...);

   where every `<lit>` is one of {integer, real, single-quoted
   string with `''` escape, NULL}, the connection MUST:
     1. Normalize the SQL by replacing each literal with `?N`
        (1-based, in left-to-right order), capturing the literal
        values in parallel.
     2. Hash the normalized SQL into a per-connection cache.
     3. On cache miss, run prepare() against the normalized SQL
        and store the resulting Program (or target-equivalent
        compiled artifact) in the cache. The original SQL string
        does NOT need to be retained; the cache key is the
        normalized template only.
     4. Bind the captured literal values via the bind() path,
        then step().
   This is the load-bearing optimization for Lane 4 INSERT
   throughput on file-driven workloads where each statement has
   the same shape but different literal values. Empirically: at
   100k same-shape INSERTs in one transaction (the L4 corpus),
   skipping tokenize+parse+compile via this cache is +70% qps
   on the Rust target's --db-WAL bench (332k → 562k qps) and
   +92% on in-memory (590k → 1130k qps).

   Multi-row VALUES tuples, RETURNING, ON CONFLICT, expressions
   beyond bare literals, blob literals (`X'...'`), and any shape
   the spec'd literal grammar does not admit MUST fall through
   to the slow path (full prepare-from-original-SQL). The
   normalizer is intentionally narrow: false-negative cache
   misses are correct; false-positive cache hits are forbidden.

   Cache invalidation: any DDL that mutates the schema (CREATE,
   DROP, or ALTER on a TABLE / INDEX / VIEW / TRIGGER) MUST
   clear the auto-prepare cache before executing. Targets MAY
   choose finer-grained invalidation (per-table) but MUST NOT
   leave the cache stale across schema changes.

   This pin describes the eager-execute path. The explicit
   prepare/bind/step API of pins 1-7 is unaffected and remains
   the surface callers reach for when they want to amortize
   compile across many calls themselves.

## Ambiguities and v1 scope decisions

- **`?` in projection** — Admitted by the parser; `Param` is a
  legal expression in any expression position. The compiler routes
  it through expr-compile which emits `BindParam` directly.
- **`?` in WHERE matched by predicate-pushdown** — Admitted as a
  row-independent expression (see
  `/parts/compiler/parts/predicate-pushdown` Pin 3). This is the
  load-bearing case for the headline Lane 3 + Lane 4 wins.
- **`?` in INSERT VALUES tuple cells** — Admitted; the insert-
  compile path emits `BindParam` opcodes the same way expression-
  bearing positions do.
- **`?` in UPDATE SET right-hand side** — Admitted, same path.
- **`?` in HAVING** — Admitted; same path.
- **`?` in ORDER BY** — Deferred; see predicate-pushdown's note. The
  parser does NOT admit `?` in positional-int positions.
- **`?` in LIMIT / OFFSET** — Deferred; see predicate-pushdown's
  note.
- **Step semantics: pause-on-row vs run-to-completion.** v1 emits
  the run-to-completion form (the program drives every ResultRow
  through the row_sink callback before returning Done). A
  pause-on-row iterator form is an additive follow-up; the
  StepResult variant already admits Row/Done/Error so spec-side
  no change is required.
- **Statement type discrimination.** v1 admits SELECT, INSERT,
  UPDATE, DELETE for the prepare path; CREATE TABLE / CREATE
  INDEX / CREATE VIEW / DROP / ALTER are admitted as Done-on-step
  with no Row events but no special API surface (callers issue
  them via prepare + step, the program executes a side-effect-
  only run). Multi-statement SQL strings (semicolon-separated)
  are deferred — `prepare` consumes a single statement.

## Regeneration envelope

- Line budget: ~250-400 lines per target. The bulk is the prepare
  dispatch (per-statement-kind compile dispatcher) and the step
  loop. Bind / reset are short.
- No new VDBE opcodes; consumes `BindParam` (added in
  `/parts/vdbe/parts/opcodes-core`).
- Imports `tokenize`, `parse_statement`, `compile_statement`,
  `execute_program`, `VdbeState`, `Database`, `Value`,
  `RuntimeCondition`, and the per-statement compile entry points.

## Smoke probe (structural)

1. `prepare(db, "SELECT * FROM t WHERE id = ?")` returns a
   `PreparedStatement` with `arity == 1`.
2. `prepare(db, "INSERT INTO t VALUES (?, ?, ?)")` returns
   `arity == 3`.
3. `prepare(db, "SELECT 1 + 1")` returns `arity == 0`.
4. `bind(stmt, 0, ...)` returns `BindError::SlotOutOfRange`.
5. `bind(stmt, arity + 1, ...)` returns `BindError::SlotOutOfRange`.
6. `bind(stmt, 1, Integer(7)); step(stmt, db)` for an INSERT
   statement against a fresh table yields `StepResult::Done` and
   leaves the table with the bound row.
7. `bind(stmt, 1, Integer(7)); step; reset; step` (no rebind in
   between) reproduces the same effect — bindings preserved across
   reset (Pin 4 + Pin 6).
