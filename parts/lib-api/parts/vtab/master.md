---
name: lib-api/vtab
kind: leaf
emits:
  rust:   { path: src-rust/lib_api/vtab.rs }
  c:      { path: src-c/lib_api/vtab.c, headers: [src-c/lib_api/vtab.h] }
  zig:    { path: src-zig/lib_api/vtab.zig }
  go:     { path: src-go/lib_api/vtab.go }
  python: { path: src-python/lib_api/vtab.py }
---

# Virtual table framework (lib-api/vtab)

The virtual-table surface lets a caller register a *module* (a named
table-like object backed by host-supplied callbacks) on a `Database`,
then issue ordinary SQL against it. The query path opens the vtab
through a cursor, negotiates an access plan via `xBestIndex`, walks
rows via `xFilter` / `xNext` / `xColumn` / `xRowid`, and (for writable
tables) mutates rows via `xUpdate`. The transactional callbacks
(`xBegin` / `xSync` / `xCommit` / `xRollback` / `xSavepoint` /
`xRelease` / `xRollbackTo` / `xRename`) bracket multi-statement work.

This is a **language-neutral** spec: callbacks are described by the
named conditions they raise and the named records they consume /
produce. Every per-target mapping (`/parts/targets/<lang>/mapping.md`)
renders the dispatch idiomatically (Rust trait + vtable struct, C
function-pointer struct, Python class with dunder methods, etc.) but
the observable behavior matches the pins below.

The framework is wired upstream of the storage facade: a vtab is NOT
a `parts/storage` table. The compiler's name-resolution layer learns
about a vtab through its registration record and routes table
references at compile time. At runtime the VDBE opens a vtab cursor
through this part; the storage layer is bypassed for vtab-backed
references.

## Public interface

The module surface is two halves: **registration** (admin) and
**dispatch** (per-statement runtime).

### Registration

- `register_module(db, name, module)` — installs `module` under `name`
  on `db`. The module is a record carrying the callback set described
  below. Returns success or `ModuleAlreadyRegistered`.
- `unregister_module(db, name)` — removes the module. Open vtab
  instances backed by the module continue running until disconnected;
  no new instances can be created. Returns success or
  `ModuleNotFound`.
- `list_modules(db)` — returns the registered module names.

### Vtab lifecycle (admin)

- `create_vtab(db, module_name, vtab_name, args)` — invokes the
  module's `xCreate` callback. The callback returns a vtab
  declaration (the `CREATE TABLE` schema string the SQL surface uses
  for column resolution) plus an opaque `vtab_handle` the module owns.
  The framework records the declaration in `db`'s schema registry so
  the compiler can resolve `vtab_name` like an ordinary table.
- `connect_vtab(db, module_name, vtab_name, args)` — invokes
  `xConnect`. Same shape as `xCreate` but does not perform side
  effects on the underlying backing store; used when re-opening a DB
  whose schema already records the vtab.
- `destroy_vtab(db, vtab_name)` — invokes `xDestroy`. Removes any
  backing-store side effects, then drops the schema entry.
- `disconnect_vtab(db, vtab_name)` — invokes `xDisconnect`. Releases
  the in-memory `vtab_handle` without touching the backing store.

### Dispatch (called by the compiler / VDBE)

The compiler discovers a vtab reference, calls `best_index(vtab,
constraints, order_by)` once at compile time to produce an
`IndexInfo`, then emits VDBE opcodes that, at runtime:

1. `open_cursor(vtab) -> CursorHandle`
2. `filter(cursor, idx_num, idx_str, argv)` (zero or more values)
3. loop: `eof(cursor)` ? if false read via `column(cursor, j)` /
   `rowid(cursor)`, then `next(cursor)`
4. `close_cursor(cursor)`

Writable-table mutations enter through `update(vtab, argc, argv)` (see
xUpdate semantics below).

Transactional callbacks (`xBegin` etc.) are invoked once per vtab per
transaction by the VDBE's transaction-bracketing opcodes; their
contract is below.

## Declared shapes (`shapes.json`)

- `Module` — the registration record. Carries the callback set as
  named function pointers / methods. See "Module shape" below.
- `VtabHandle` — opaque per-instance state owned by the module. The
  framework holds it by value and threads it back into every vtab
  callback. The framework never inspects its contents.
- `CursorHandle` — opaque per-cursor state owned by the module.
  Distinct from `parts/storage::CursorHandle` (which is a btree
  cursor); the names collide deliberately because both are abstract
  walkers.
- `Constraint { column: i32, op: ConstraintOp, usable: bool }` — a
  single WHERE constraint exposed to `xBestIndex`. `column = -1`
  denotes the rowid column. `usable = false` means the constraint
  cannot be honored on this iteration (the planner may set this to
  break dependency cycles).
- `ConstraintOp` — variant: `Eq | Lt | Le | Gt | Ge | Match | Like |
  Glob | Regexp | Ne | IsNot | IsNotNull | IsNull | Is | Limit |
  Offset`. The set is closed; new operators require a spec change.
- `OrderBy { column: i32, desc: bool }` — a single ORDER BY clause
  fragment exposed to `xBestIndex`.
- `ConstraintUsage { argv_index: u32, omit: bool }` — the planner's
  reply, parallel to the constraint list. `argv_index = 0` means the
  constraint is unused; nonzero `k` means the constraint's right-hand
  side is delivered to `xFilter` as `argv[k - 1]`. `omit = true`
  asserts `xFilter` will fully honor the constraint, so the VDBE need
  not re-check it after the row materializes.
- `IndexInfo` — the negotiation record. Carries the constraints,
  order_by, the per-constraint usage reply, the index plan number
  (`idx_num`), the optional plan string (`idx_str`), an
  `order_by_consumed` flag, and a cost estimate. See pins 4–8.
- `VtabUpdateOp` — variant inferred from `xUpdate`'s argv: `Delete |
  Insert | Update | Rename`. Pins 14–17 describe how the VDBE
  constructs argv before calling `update`.
- `VtabCondition` — variant of error conditions: `ModuleNotFound |
  ModuleAlreadyRegistered | VtabNotFound | DeclareInvalid |
  ConstraintViolation | ReadOnly | LockingError | Busy | Misuse |
  Internal { detail: String }`. Targets render as their canonical
  sum-of-errors.

### Module shape

A `Module` is a record of named callbacks. The callbacks are listed
in declaration order; targets render the record as a struct of
function pointers (C), a trait object + vtable (Rust), a class
satisfying a structural protocol (Python), or equivalent. None of
the callbacks may panic / abort; every failure path returns a
`VtabCondition`.

| Callback | Required | Returns | Notes |
|---|---|---|---|
| `xCreate(db, args) -> (VtabHandle, declare_sql)` | required for CREATE-style | success or `VtabCondition` | side effects on backing store admitted |
| `xConnect(db, args) -> (VtabHandle, declare_sql)` | required | success or `VtabCondition` | no side effects on backing store |
| `xDisconnect(vtab) -> ()` | required | infallible (any error logged) | releases in-memory handle |
| `xDestroy(vtab) -> ()` | required for CREATE-style | success or `VtabCondition` | inverse of xCreate |
| `xBestIndex(vtab, &mut IndexInfo) -> ()` | required | success or `VtabCondition` | reads constraints + order_by, writes usage + idx_num + idx_str + cost |
| `xOpen(vtab) -> CursorHandle` | required | success or `VtabCondition` | one cursor per concurrent walk |
| `xClose(cursor) -> ()` | required | infallible | releases cursor handle |
| `xFilter(cursor, idx_num, idx_str, argv) -> ()` | required | success or `VtabCondition` | positions cursor at first matching row |
| `xNext(cursor) -> ()` | required | success or `VtabCondition` | advances; may set EOF |
| `xEof(cursor) -> bool` | required | infallible | true once exhausted |
| `xColumn(cursor, j) -> Value` | required | success or `VtabCondition` | reads j-th column at current row |
| `xRowid(cursor) -> i64` | required | success or `VtabCondition` | reads rowid at current row |
| `xUpdate(vtab, argv) -> Option<i64>` | required for writable | success or `VtabCondition` | semantics in pins 14–17 |
| `xBegin(vtab) -> ()` | optional | success or `VtabCondition` | invoked once per write txn |
| `xSync(vtab) -> ()` | optional | success or `VtabCondition` | between BEGIN and COMMIT |
| `xCommit(vtab) -> ()` | optional | success or `VtabCondition` | finalize txn |
| `xRollback(vtab) -> ()` | optional | success or `VtabCondition` | abort txn |
| `xRename(vtab, new_name) -> ()` | optional | success or `VtabCondition` | ALTER TABLE RENAME |
| `xSavepoint(vtab, n) -> ()` | optional | success or `VtabCondition` | nested savepoint open |
| `xRelease(vtab, n) -> ()` | optional | success or `VtabCondition` | savepoint commit |
| `xRollbackTo(vtab, n) -> ()` | optional | success or `VtabCondition` | savepoint rollback |

Optional callbacks absent on a `Module` make the corresponding SQL
surface a no-op (e.g. a module without `xBegin` simply isn't notified
of transaction start). `xUpdate`-less modules reject any DML against
the vtab with `VtabCondition::ReadOnly`.

## Algorithm sketches

### `register_module(db, name, module)`

```
if db.modules.contains_key(name):
    return Err(ModuleAlreadyRegistered)
db.modules.insert(name, module)
return Ok(())
```

### `create_vtab(db, module_name, vtab_name, args)`

```
module = db.modules.get(module_name)?     // ModuleNotFound
(handle, declare_sql) = module.x_create(db, args)?
ast = parse_create_table(declare_sql)?     // DeclareInvalid on parse fail
db.schema_registry.install_vtab(vtab_name, ast.columns, handle, module)
return Ok(())
```

`connect_vtab` is identical except it calls `x_connect` and asserts
`vtab_name` is already known to the schema registry (or admits a
fresh entry on first connect; targets MAY relax to "either path
admitted" so long as Pin 11 holds).

### `best_index(vtab, where_terms, order_by)` (compile-time)

```
info = IndexInfo {
    constraints:    constraints_from(where_terms),
    order_by:       order_by_terms,
    usage:          [ConstraintUsage::unused(); constraints.len()],
    idx_num:        0,
    idx_str:        None,
    order_by_consumed: false,
    estimated_cost: f64::MAX,
    estimated_rows: 25,                   // SQLite default
}
vtab.module.x_best_index(vtab.handle, &mut info)?
return info
```

The compiler picks the plan returned by `xBestIndex`; it does NOT
call `xBestIndex` repeatedly. (Mainline SQLite calls multiple times
to explore alternatives; v1 picks one shot. A future spec change
admits the loop without changing the per-call contract.)

### Runtime walk (compiled into VDBE opcodes)

```
cursor = vtab.module.x_open(vtab.handle)?
vtab.module.x_filter(cursor, info.idx_num, info.idx_str, argv)?
loop:
    if vtab.module.x_eof(cursor): break
    for j in 0..vtab.column_count:
        registers[base + j] = vtab.module.x_column(cursor, j)?
    rowid_register = vtab.module.x_rowid(cursor)?
    emit_row(...)
    vtab.module.x_next(cursor)?
vtab.module.x_close(cursor)
```

### `xUpdate` argv shape

`argv` is a positional value vector. Conventions:

- `argv[0]` is the **old rowid** (or `Null` if there is no old row,
  i.e. for INSERT).
- `argv[1]` is the **new rowid** (or `Null` to ask the module to
  pick).
- `argv[2..]` are the **new column values** in declared column order.

Cases (Pins 14–17):

- `argc == 1` → DELETE the row whose rowid is `argv[0]`.
- `argc > 1` and `argv[0]` is `Null` → INSERT.
- `argc > 1` and `argv[0]` is non-Null and `argv[1] == argv[0]` →
  UPDATE in place.
- `argc > 1` and `argv[0]` is non-Null and `argv[1] != argv[0]` →
  RENAME-rowid (an UPDATE that also changes the rowid).

`xUpdate` may return `Some(rowid)` on INSERT to communicate the
chosen rowid back to the caller; on DELETE / UPDATE it returns
`None`. A module that rejects writes returns
`VtabCondition::ReadOnly`.

## Correctness pins

1. **Module registration is keyed by name on a single `Database`.**
   `register_module(db, name, module)` is rejected with
   `ModuleAlreadyRegistered` if the name is already taken on `db`.
   The same name on a different `Database` is independent.

2. **Module lifetime is bounded by the connection.** When a
   `Database` closes, every registered module's
   `xDisconnect` is called for every live vtab instance that
   module backs, in reverse-registration order. After `close`, no
   callbacks may fire. A module reference held by the caller after
   close is structurally inert (calling any vtab API on it returns
   `VtabNotFound` or the target's equivalent).

3. **`xConnect` and `xCreate` both produce a `(VtabHandle,
   declare_sql)` pair.** The framework parses `declare_sql` as a
   `CREATE TABLE` statement and installs the resulting columns into
   `db`'s schema registry. A `declare_sql` that fails to parse
   raises `VtabCondition::DeclareInvalid`; the framework does NOT
   record the vtab and does NOT keep `VtabHandle` alive (it calls
   `xDisconnect` to release it).

4. **`xBestIndex` reads constraints + order_by and writes usage +
   plan.** The framework constructs `IndexInfo` with
   `constraints`, `order_by`, and a default `usage` vector
   (every entry `argv_index = 0, omit = false`). The callback
   mutates `usage`, `idx_num`, `idx_str`, `order_by_consumed`, and
   `estimated_cost` in place. After the call returns, the
   framework treats those fields as the negotiated plan and does
   NOT mutate them further.

5. **`Constraint::usable = false` MUST be ignored by `xBestIndex`.**
   The framework sets `usable = false` on a constraint to signal the
   module that this iteration cannot honor it (e.g. the constraint's
   right-hand side depends on a row from a sibling table that is
   the outer of a join). A module that sets `argv_index != 0` for an
   unusable constraint is a programming error; the framework ignores
   the assignment (treating that slot as `argv_index = 0`) and may
   log.

6. **`ConstraintUsage::argv_index` is 1-based and dense.** The
   module assigns `argv_index = 1` to the first constraint whose
   value it wants delivered, `2` to the next, and so on. Gaps are
   programming errors; the framework treats a gap as truncating the
   argv (any constraint with `argv_index` beyond the gap is
   ignored). `argv` length at `xFilter` time is the maximum
   assigned `argv_index` (0 if none).

7. **`ConstraintUsage::omit = true` is a hint, not a contract
   change.** Setting `omit` lets the VDBE skip a redundant predicate
   re-check after the row materializes. If the module sets `omit =
   true` but `xFilter` does NOT actually honor the constraint, the
   query result is allowed to be wrong; the framework does not
   verify. (Same as mainline SQLite.)

8. **`order_by_consumed = true` asserts `xFilter` returns rows in the
   requested order.** When set, the VDBE skips the post-walk sort
   step. When unset (default), the VDBE sorts as if the vtab were a
   regular table. The module MUST NOT set `order_by_consumed = true`
   unless every entry in `order_by` is honored by the chosen plan;
   doing so otherwise produces incorrect query results.

9. **`estimated_cost` is informational; v1 ignores it.** The
   compiler does not currently call `xBestIndex` more than once
   (Pin 4 implies a single-shot). v1 records `estimated_cost` for
   potential future use (loop-based plan exploration) but does not
   branch on it. A module SHOULD still populate it honestly so v1.1
   does not require regeneration.

10. **`xOpen` may be called concurrently for the same `vtab`.**
    Multiple cursors may walk the same vtab at the same time
    (correlated subquery, recursive CTE, etc.). The module is
    responsible for cursor isolation. The framework guarantees that
    a single `CursorHandle` is never accessed concurrently from
    different threads.

11. **`xConnect` is idempotent across reopens; `xCreate` is not.**
    Calling `connect_vtab` for a vtab name that already exists in
    the schema registry refreshes the in-memory handle without
    side-effecting the backing store. Calling `create_vtab` for an
    existing vtab name is rejected (the schema registry signals a
    duplicate; the framework returns `VtabCondition::Misuse`).

12. **`xDestroy` is the inverse of `xCreate`; `xDisconnect` is the
    inverse of `xConnect`.** Disconnect releases in-memory state
    only; destroy releases backing-store state. `disconnect_vtab`
    on an already-disconnected vtab is a no-op. `destroy_vtab` on a
    disconnected vtab first reconnects (calls `xConnect`), then
    calls `xDestroy`, then disconnects.

13. **Every callback returns a `VtabCondition` on failure; the
    framework propagates as a `RuntimeCondition::VtabError`.**
    `xColumn`, `xFilter`, `xNext`, etc. failures abort the current
    statement at the VDBE; the cursor is closed via `xClose` (which
    is infallible by contract) and the program halts with
    `Error(VtabError(...))`.

14. **`xUpdate` argc==1 is DELETE.** `argv[0]` is the old rowid.
    The module deletes that row and returns `None`. A delete
    against a non-existent rowid is a module-policy decision (silent
    or `ConstraintViolation`); the framework does not mandate one.

15. **`xUpdate` argc>1 and argv[0]==Null is INSERT.** The new column
    values are in `argv[2..]`. If `argv[1]` is `Null`, the module
    picks the rowid and returns `Some(rowid)`. If `argv[1]` is
    non-Null, that integer IS the requested rowid; the module
    either honors it (returns `Some(rowid)`) or raises
    `ConstraintViolation` (rowid collides with an existing row).

16. **`xUpdate` argc>1 and argv[0]==argv[1] is UPDATE-in-place.**
    The module finds the row at `argv[0]`'s rowid, replaces its
    column values with `argv[2..]`, and returns `None`. The rowid
    does not change.

17. **`xUpdate` argc>1 and argv[0]!=argv[1] (both non-Null) is
    RENAME-rowid.** The module finds the row at `argv[0]`'s rowid,
    moves it to `argv[1]`'s rowid (replacing column values with
    `argv[2..]`), and returns `None`. A rowid collision is a
    `ConstraintViolation`.

18. **`xBegin` opens a write transaction; `xCommit` or `xRollback`
    closes it.** `xBegin` is invoked at most once per vtab per
    outer SQL transaction. If the outer transaction issues no DML
    against a vtab, that vtab's `xBegin` is NOT invoked. `xCommit`
    must succeed-or-fail atomically; on failure the framework
    invokes `xRollback` (matching mainline two-phase semantics).

19. **`xSync` runs after every modified vtab's pre-commit.** Order:
    `xSync` on every dirty vtab, then `xCommit` on every dirty
    vtab. `xSync` failure on any vtab causes `xRollback` to be
    issued on every vtab (including those whose `xSync` succeeded).
    This pin is a direct port of mainline's vtab two-phase commit.

20. **`xRename(vtab, new_name)` is invoked on `ALTER TABLE
    RENAME`.** The framework also updates the schema registry's
    vtab name binding. Failure rolls back both the registry update
    and the rename callback's effect (the module is responsible for
    the latter).

21. **`xSavepoint` / `xRelease` / `xRollbackTo` are keyed by an
    integer `n`.** `xSavepoint(n)` opens savepoint `n`; `xRelease(n)`
    commits it (and every nested savepoint with index > n);
    `xRollbackTo(n)` aborts it (and every nested savepoint with
    index > n). Indices are assigned by the framework, monotonically
    increasing within the outer transaction; the module treats them
    as opaque labels.

22. **An optional callback absent on a `Module` makes the SQL action
    a no-op or a `ReadOnly` rejection.** Specifically: a module
    without `xUpdate` rejects DML with `VtabCondition::ReadOnly`. A
    module without `xBegin` / `xSync` / `xCommit` / `xRollback`
    runs DML transparently — the framework simply does not call the
    missing callbacks. A module without `xRename` rejects
    `ALTER TABLE RENAME` with `ReadOnly`. A module without
    savepoint callbacks rejects `SAVEPOINT` with `ReadOnly`.

23. **A vtab is opaque to the storage facade.** `parts/storage`'s
    `Database` does not page, journal, or WAL-checkpoint vtab data.
    The vtab's module is solely responsible for any persistence.
    Bidirectional file-format compatibility (Pin in
    `parts/storage`) is unaffected by vtab presence: the on-disk
    image of the SQLite header schema may carry a CREATE VIRTUAL
    TABLE statement (mainline-compatible) but no vtab data pages.

24. **`xColumn` returns an OWNED `Value`.** Same boundary as
    `parts/storage::cursor_column` (Pin in `parts/storage/master.md`,
    "Column ownership"). The framework hands the value to the VDBE's
    `set_register`, which takes ownership. A module that returns a
    borrowed value is a programming error; targets MAY enforce by
    requiring a clone at the boundary.

25. **`xRowid` failure does NOT poison `xColumn` reads.** A row whose
    `xRowid` raises `VtabCondition` may still have legible column
    values. The VDBE compiles `xRowid` reads only when the SQL
    actually references the rowid; otherwise `xRowid` is not called.
    A module MAY raise `Internal` from `xRowid` on a tableless vtab
    (e.g. an eponymous module that has no natural rowid) so long as
    the SQL never asks for it.

26. **Constraint operators outside `ConstraintOp` are NOT exposed to
    `xBestIndex`.** The compiler filters where-terms; only those
    whose operator is in the variant set appear in `IndexInfo`.
    Other terms (e.g. arbitrary expressions) become post-filter
    predicates the VDBE re-checks after `xColumn` materializes.

27. **`idx_str` is owned by the module across the cursor's
    lifetime.** `xBestIndex` allocates `idx_str`; the framework
    holds it for the duration of the compiled plan and passes it by
    reference to `xFilter`. The module is responsible for the
    string's storage lifetime; targets that need explicit free
    (C, Zig) call a module-supplied `xFreeIdxStr` (admitted as an
    optional 28th callback in target mappings, not in the canonical
    Module shape — its presence is a target-mapping concern).

## Ambiguities and v1 scope decisions

- **Eponymous modules** (a module that IS its own table, no
  `CREATE VIRTUAL TABLE` needed) — admitted as a v1 follow-up. The
  shape change is small (a flag on `Module`); the dispatch path is
  unchanged.
- **`xFindFunction`** (overload SQL functions per-vtab) — out of
  scope for v1.
- **`xShadowName`** — out of scope.
- **Multi-call `xBestIndex`** — Pin 4 says one shot. Mainline
  iterates plans; v1 takes the first.
- **`xIntegrity`** (PRAGMA integrity_check pass-through) — deferred.
- **WITHOUT ROWID virtual tables** — out of scope; v1 vtabs always
  expose a rowid (Pin 25 admits a `xRowid`-raising module only when
  the rowid is never referenced).

## Regeneration envelope

- Line budget: ~400-700 lines per target. Bulk is the IndexInfo
  negotiation and the xUpdate argc-dispatch; registration and
  cursor open/close are short.
- No new VDBE opcodes; the compiler routes vtab references through
  existing OpenRead / OpenWrite / Filter / Next / Column / Rowid
  ops with a "vtab" cursor kind discriminator (target-mapping
  concern, not spec-shape).
- Imports: `Value`, `RuntimeCondition`, `Database`, `ParseError`,
  the schema registry's `install_vtab` entry, and the parser's
  `parse_create_table`.

## Smoke probe (structural)

1. `register_module(db, "echo", echo_module)` succeeds; a second
   call rejects with `ModuleAlreadyRegistered`.
2. `create_vtab(db, "echo", "t1", [])` invokes `xCreate`, parses
   `declare_sql`, and registers `t1` in the schema registry.
3. `SELECT * FROM t1 WHERE k = 7 ORDER BY k` calls `xBestIndex`
   exactly once, then `xOpen`, then `xFilter` with `argv = [7]`
   (assuming the module set `argv_index = 1` on the `k = ?`
   constraint), then `xNext` / `xColumn` / `xRowid` until `xEof`
   returns true, then `xClose`.
4. `INSERT INTO t1 VALUES (NULL, 1, 2)` calls `xUpdate` with
   `argv = [Null, Null, 1, 2]` (argc=4, INSERT case); the module
   returns `Some(rowid)`.
5. `DELETE FROM t1 WHERE rowid = 5` calls `xUpdate` with
   `argv = [Integer(5)]` (argc=1, DELETE case).
6. `UPDATE t1 SET k = 99 WHERE rowid = 3` calls `xUpdate` with
   `argv = [Integer(3), Integer(3), 99, ...]` (argc>1, argv[0]==argv[1],
   UPDATE-in-place case).
7. `BEGIN; INSERT INTO t1 ...; COMMIT;` calls `xBegin` once, then
   `xUpdate`, then `xSync`, then `xCommit`. `ROLLBACK` instead of
   `COMMIT` calls `xRollback` and skips `xSync` / `xCommit`.
8. A module without `xUpdate` causes any DML against its vtabs to
   fail with `VtabCondition::ReadOnly` (Pin 22).
9. `xBestIndex` setting `usage[0].argv_index = 1` and `omit = true`
   on the `k = ?` constraint causes the VDBE to skip the post-walk
   `k = 7` re-check (Pin 7).
10. `db.close()` invokes `xDisconnect` for every live vtab in
    reverse registration order (Pin 2).
