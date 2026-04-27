---
name: lib-api/authorizer
kind: leaf
emits:
  rust:   { path: src-rust/lib_api/authorizer.rs }
  c:      { path: src-c/lib_api/authorizer.c, headers: [src-c/lib_api/authorizer.h] }
  zig:    { path: src-zig/lib_api/authorizer.zig }
  go:     { path: src-go/lib_api/authorizer.go }
  python: { path: src-python/lib_api/authorizer.py }
---

# Authorizer: per-action compile-time access control

The authorizer is a connection-scoped callback the application may
install to vet every individual action a SQL statement intends to
perform, **at compile (prepare) time**, BEFORE any bytecode is emitted
for that action. The callback receives an `AuthAction` describing one
candidate operation (e.g. `READ` on table `t` column `c`, or
`CREATE_TABLE` for new table `s`) and returns one of three verdicts:
`Ok` (permit), `Ignore` (permit, but treat the result as Null /
no-op), or `Deny` (refuse — `prepare` fails with `AuthDenied`).

This is mainline SQLite's `sqlite3_set_authorizer` surface
(sqlite.org/c3ref/set_authorizer.html — published spec). The point is
to give the embedder a chokepoint to enforce policy ("this statement
may not touch table `users`") without trusting per-query input
sanitization.

## Scope (v1)

Admitted:

- `set_authorizer(db, callback)` — installs / replaces / clears
  (callback = absent) the per-connection authorizer.
- 25 action codes covering the v1 SQL surface (see Pin 4): every
  CREATE/DROP/ALTER variant, every DML kind, READ (per-column),
  TRANSACTION, ATTACH/DETACH, PRAGMA, FUNCTION, RECURSIVE.
- Three verdicts: `Ok`, `Ignore`, `Deny` (Pins 5-7).
- Compile-time invocation only: the callback is called by the
  per-statement compiler as it walks the AST. Once `prepare`
  returns a `PreparedStatement`, no further authorizer calls fire
  for that statement — `step` does not re-authorize (Pin 9).
- Re-authorization on schema reload: a connection that re-parses a
  cached statement after a `SCHEMA_VERSION` bump (see
  `/parts/storage`) re-runs prepare and therefore re-runs the
  authorizer (Pin 11).

Deferred:

- Action codes for v1.1 surface (FTS5, R-tree, SAVEPOINT,
  REINDEX, ANALYZE, CREATE_VTABLE, COPY).
- Per-statement (vs per-connection) authorizer overrides.
- Authorizer for trigger bodies — admitted as a Pin (Pin 12) but
  the v1 trigger compiler is itself deferred.

## Declared shapes (`shapes.json`)

- `AuthAction` — variant enumerating the 25 v1 action codes; some
  carry name payloads (e.g. `Read { table, column }`,
  `CreateTable { schema, name }`). One variant per action code.
- `AuthVerdict` — variant: `Ok | Ignore | Deny`.
- `AuthorizerCallback` — function shape: takes an `AuthAction` and
  the per-connection user-data handle, returns an `AuthVerdict`.
- `AuthState` — per-connection record holding the current callback
  (present-or-absent) and an opaque user-data handle.
- `AuthDenied` — error condition surfaced as `PrepareError::Denied
  { action }` so the caller sees which action triggered the refusal.
- Functions: `set_authorizer`, `clear_authorizer`,
  `invoke_authorizer` (called by compilers).

## Action-code table (named constants)

The `AuthAction` variant carries one case per code below. The integer
column is the canonical numeric code targets MAY expose for FFI
parity with mainline SQLite (sqlite.org/c3ref/c_alter_table.html);
the name column is the spec-canonical identifier each generator
produces in its target-idiomatic form.

| Code | Name              | Payload fields                         |
|------|-------------------|----------------------------------------|
| 1    | CreateIndex       | schema, index_name, table_name         |
| 2    | CreateTable       | schema, table_name                     |
| 3    | CreateTempIndex   | schema, index_name, table_name         |
| 4    | CreateTempTable   | schema, table_name                     |
| 5    | CreateTempTrigger | schema, trigger_name, table_name       |
| 6    | CreateTempView    | schema, view_name                      |
| 7    | CreateTrigger     | schema, trigger_name, table_name       |
| 8    | CreateView        | schema, view_name                      |
| 9    | Delete            | schema, table_name                     |
| 10   | DropIndex         | schema, index_name, table_name         |
| 11   | DropTable         | schema, table_name                     |
| 12   | DropTempIndex     | schema, index_name, table_name         |
| 13   | DropTempTable     | schema, table_name                     |
| 14   | DropTempTrigger   | schema, trigger_name, table_name       |
| 15   | DropTempView      | schema, view_name                      |
| 16   | DropTrigger       | schema, trigger_name, table_name       |
| 17   | DropView          | schema, view_name                      |
| 18   | Insert            | schema, table_name                     |
| 19   | Pragma            | pragma_name, pragma_arg (present-or-absent) |
| 20   | Read              | schema, table_name, column_name        |
| 21   | Select            | (no payload)                           |
| 22   | Transaction       | operation_name (Begin / Commit / Rollback / Release) |
| 23   | Update            | schema, table_name, column_name        |
| 24   | Attach            | filename                               |
| 25   | Detach            | schema                                 |
| 26   | AlterTable        | schema, table_name                     |
| 27   | Reindex           | schema, index_name                     |
| 28   | Analyze           | schema, target_name                    |
| 29   | Function          | function_name                          |
| 30   | Recursive         | (no payload — fires once per CTE)      |

`schema` is `"main"` for the primary database, `"temp"` for the
temp namespace, or an attached schema name. Names are bare
identifiers (the parser has already lowered quoting). Targets MAY
collapse `Read` and `Update`'s payload into a tuple if the target
language is friendlier with positional records; the pin is that
table_name + column_name are both observable to the callback.

## Algorithm

### `set_authorizer(db, callback)`

```
db.auth_state.callback = present(callback)
return Ok(())
```

Replaces any prior callback. Idempotent. The callback's user-data
handle (the second parameter the callback receives) is stored
alongside the callback function — targets render this however is
idiomatic (Rust closure, C function pointer + `void* user`,
Python callable, etc.).

### `clear_authorizer(db)`

```
db.auth_state.callback = absent
return Ok(())
```

After clear, `invoke_authorizer` short-circuits to `Ok` for every
action (Pin 10).

### `invoke_authorizer(db, action)` — called by compilers

```
match db.auth_state.callback:
    absent -> return Ok                       # Pin 10
    present(cb) ->
        verdict = cb(action, db.auth_state.user_data)
        match verdict:
            Ok     -> return Ok               # compiler proceeds
            Ignore -> return Ignore           # compiler emits Null/no-op (Pin 6)
            Deny   -> return Deny             # compiler raises AuthDenied(action)
```

The compiler call sites are pinned (Pin 8). The callback MUST NOT
mutate the database (no recursive prepare/step) — see Pin 13. The
spec does not enforce non-recursion; targets MAY add a re-entry
guard.

### Compiler integration

For each AST node the per-statement compiler walks, it issues an
`invoke_authorizer` call BEFORE emitting opcodes for the
corresponding action. Examples:

- `compile_select`: for each table referenced, issue `Select`
  once per outermost SELECT, then `Read { table, column }` for each
  projected/filter-touched column. (Pin 4 cardinality.)
- `compile_insert`: issue `Insert { schema, table }` once;
  per-column writes do NOT issue Read but DO issue Update if the
  INSERT carries a `... ON CONFLICT DO UPDATE` clause (deferred —
  v1's UPSERT lowering is a follow-up).
- `compile_update`: issue `Update { schema, table, column }` once
  per SET-target column; issue `Read { schema, table, column }` for
  each column read in the SET RHS or WHERE.
- `compile_delete`: issue `Delete { schema, table }` once; plus
  `Read` for each column read in WHERE.
- `compile_create_table`: issue `CreateTable` (or
  `CreateTempTable` if the parser observed the `TEMP` keyword).
- `compile_pragma`: issue `Pragma { name, arg }` once.

## Correctness pins

1. **`set_authorizer(db, cb)` replaces the prior callback for that
   connection.** Per-connection state, not per-statement, not
   process-global. Concurrent connections are independent. The
   call is idempotent: setting twice with the same callback is
   indistinguishable from setting once.
2. **`set_authorizer(db, absent)` clears.** Equivalent to
   `clear_authorizer(db)`. After clear, every action is admitted as
   if no authorizer were installed (Pin 10).
3. **The callback fires at PREPARE time, not STEP time.** Prepare
   walks the AST and issues one authorizer call per action node;
   step never invokes the authorizer. A prepared statement that
   compiled successfully under authorizer X continues to execute
   even if the application later replaces X with a stricter Y —
   re-authorization requires re-prepare.
4. **The 30 action codes in the table above are the closed set
   for v1.** The compiler MUST issue exactly the cardinality the
   table prescribes: `Read` once per (table, column) pair the
   statement reads; `Update` once per (table, column) pair the
   statement writes; `Select` once per outermost SELECT (NOT per
   subquery — subqueries are inner SELECTs that share their parent
   `Select` authorization). `Recursive` fires once per recursive
   CTE seen.
5. **`AuthVerdict::Ok` admits the action unchanged.** The compiler
   emits the same opcodes it would have without an authorizer
   installed. Observable output is identical to the no-authorizer
   case.
6. **`AuthVerdict::Ignore` permits the action but neutralizes its
   value.** For `Read { table, column }`, the compiler emits a
   register-Null in place of the column-load opcode — the row is
   still produced but that column reads as Null. For
   `Update { table, column }`, the SET on that column is dropped
   (the column retains its prior value). For DDL / TRANSACTION
   / PRAGMA actions where "ignore the value but keep the structure"
   does not have a meaningful semantics, `Ignore` is treated as
   `Ok` (the compiler proceeds normally) — this matches mainline
   SQLite's documented Ignore behavior for non-Read/non-Update
   codes. Targets MUST NOT silently drop the action.
7. **`AuthVerdict::Deny` aborts prepare.** The per-statement
   compiler raises `CompileError::AuthDenied { action }`; `prepare`
   surfaces it as `PrepareError::CompileFailure(AuthDenied)`. No
   bytecode is emitted; no schema mutation is performed; the
   connection is unaffected.
8. **One authorizer call per action node, in source order.** The
   compiler walks the AST in left-to-right source order and issues
   authorizer calls in that same order. A statement that touches
   `t.a, t.b, t.c` issues three Read calls in the order `a, b, c`.
   This pins observable callback ordering for tests.
9. **Step does not re-authorize.** `step` consumes only the
   compiled program; it has no callback into the authorizer.
   Side-effect actions inside the program (an INSERT compiled
   from `INSERT ... SELECT`) were authorized at prepare time of
   the outer statement; they do not re-fire at step time.
10. **No-callback-installed is equivalent to all-Ok.** A connection
    with no authorizer set behaves as if every `invoke_authorizer`
    call returned `Ok`. The compiler MUST NOT skip the call site
    structure (so installing an authorizer mid-life of a connection
    immediately starts taking effect on the next prepare); it MAY
    short-circuit the dispatch.
11. **Schema-version bump invalidates a prepared statement; the
    re-prepare re-runs the authorizer.** When the storage layer
    bumps `schema_cookie` (DDL on the same or another connection),
    cached prepared statements MUST be re-prepared on next step
    (the existing schema-version check already pins this). The
    re-prepare path issues fresh `invoke_authorizer` calls; a
    callback installed since the original prepare WILL see them.
12. **Trigger bodies (deferred) authorize at trigger-create time.**
    When v1.1 admits triggers, the BEGIN-…-END body of a
    `CREATE TRIGGER` statement is itself compiled at create time
    and the authorizer fires for each action inside the body, with
    the action codes carrying the trigger's name as context. v1
    does not implement triggers; the pin reserves the semantics so
    a v1.1 spec extension does not need to renumber action codes.
13. **The callback MUST be side-effect-free with respect to the
    same connection.** Calling `prepare`, `step`, `set_authorizer`,
    or any DDL on the same `db` from inside the callback is
    undefined behavior at the spec level. Targets MAY enforce this
    with a re-entry flag; the spec does not require detection. The
    callback MAY read application-side state and MAY consult
    sibling connections.
14. **`Function` action covers ALL function calls in the
    statement.** Every scalar function, every aggregate function,
    every builtin; the action carries the function's lower-cased
    name. A statement using `length(x) + abs(y)` issues two
    `Function` calls in source order.
15. **`Recursive` fires once per WITH RECURSIVE CTE.** A non-
    recursive CTE does not fire `Recursive`; it fires only `Read`
    for the columns its body reads.
16. **`Pragma` fires before any pragma side-effect.** Read-only
    pragmas (`PRAGMA user_version`) and writing pragmas
    (`PRAGMA user_version = 7`) both issue `Pragma { name, arg }`;
    arg is `absent` for the read form, `present(value-as-string)`
    for the write form.

## Ambiguities and v1 scope decisions

- **Ignore on a primary-key column read.** Ignore replaces the
  loaded value with Null. If that column participates in the
  outer query's WHERE / JOIN predicate, downstream filtering
  evaluates against Null — i.e. the row likely drops out of the
  result. This is intentional: it lets the embedder enforce
  "this column is invisible" without changing the SQL.
- **Order of Read vs Select for joined SELECT.** `Select` fires
  once for the outermost SELECT, then Read fires for each column
  in source order across all joined tables. Subqueries do NOT
  fire a fresh `Select`.
- **Compound statements (UNION / INTERSECT).** Each branch fires
  its own `Select`; Read calls fire per branch.
- **CTEs.** A non-recursive CTE fires `Read` for each column its
  body references AND `Read` for each column the outer query
  references via the CTE alias — the CTE is materialized then
  read.

## Regeneration envelope

- Line budget: ~150-250 lines per target. The bulk is the
  `AuthAction` variant declaration; `set_authorizer` and the
  dispatch helper are short.
- No new VDBE opcodes; the authorizer affects opcode SELECTION at
  compile time, not opcode SEMANTICS at run time.
- Imports: `Database` (for the per-connection state slot),
  `CompileError` (for the AuthDenied variant).

## Smoke probe (structural)

1. `set_authorizer(db, deny_table("forbidden"))` then
   `prepare(db, "SELECT * FROM forbidden")` returns
   `PrepareError::CompileFailure(AuthDenied { action: Read { table:
   "forbidden", .. } })`.
2. Same authorizer, `prepare(db, "SELECT * FROM allowed")` returns
   `Ok(stmt)`; subsequent `step` produces rows normally.
3. `set_authorizer(db, ignore_column("t", "secret"))` then a
   `SELECT a, secret, c FROM t` returning row `(1, X, 3)` produces
   `(1, Null, 3)` — column blanked, row preserved.
4. `clear_authorizer(db)` after Pin-1's deny returns the connection
   to all-admit; the same `prepare` then succeeds.
5. Authorizer call ordering: `SELECT t.a, t.b FROM t WHERE t.c=?`
   produces calls in the order `Select; Read{t,a}; Read{t,b};
   Read{t,c}; Function` (none, no functions in this case).
6. `prepare(db, "CREATE TABLE x(a)")` under
   `deny_action(CreateTable)` raises AuthDenied.
7. Re-prepare on schema-cookie bump re-runs the authorizer — install
   a deny-all callback after a successful prepare, bump the
   schema_cookie via a sibling DDL, then call step on the cached
   statement: the re-prepare path raises AuthDenied.
