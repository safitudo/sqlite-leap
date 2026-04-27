---
name: lib-api/c-abi
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /parts/lib-api/master.md
  - /parts/lib-api/parts/prepared-statement/master.md
emits:
  c:      { path: src-c/lib_api/c_abi.c, headers: [src-c/lib_api/sqlite3.h] }
  rust:   { path: src-rust/lib_api/c_abi.rs }
  zig:    { path: src-zig/lib_api/c_abi.zig }
  go:     { path: src-go/lib_api/c_abi.go }
  python: { path: src-python/lib_api/c_abi.py }
---

# C ABI shim — `sqlite3_*` compatibility surface

This part exposes the canonical `sqlite3_*` C ABI as a thin shim
over `lib-api/prepared-statement` and the underlying parser /
compiler / VDBE / storage parts. It is the surface every existing
SQLite-compatible application binds against (CPython's `sqlite3`,
`better-sqlite3`, JDBC, every ORM). Without this surface the C
build cannot be a drop-in replacement on any of the six benchmark
lanes that compare against mainline.

The shim translates the lib-api lifecycle (`prepare` / `bind` /
`step` / `reset`) into the C ABI's
`sqlite3_prepare_v2` / `sqlite3_bind_*` / `sqlite3_step` /
`sqlite3_reset` / `sqlite3_finalize` lifecycle, plus the
auxiliary surface (`sqlite3_open` / `_close` / `_exec` /
`_column_*` / `_errmsg` / `_changes` / `_last_insert_rowid` /
`_busy_timeout`). It is the **only** part allowed to speak the
mainline ABI; every other part stays language-neutral.

## Scope (v1)

Admitted (the 22 entry points named in CLAUDE.md scope, grouped):

| Group | Functions |
|-------|-----------|
| Lifecycle | `sqlite3_open`, `sqlite3_open_v2`, `sqlite3_close`, `sqlite3_close_v2` |
| One-shot exec | `sqlite3_exec` |
| Prepared statement | `sqlite3_prepare_v2`, `sqlite3_step`, `sqlite3_reset`, `sqlite3_finalize` |
| Column accessors | `sqlite3_column_count`, `sqlite3_column_type`, `sqlite3_column_int`, `sqlite3_column_int64`, `sqlite3_column_double`, `sqlite3_column_text`, `sqlite3_column_blob`, `sqlite3_column_bytes`, `sqlite3_column_name` |
| Bind | `sqlite3_bind_int`, `sqlite3_bind_int64`, `sqlite3_bind_double`, `sqlite3_bind_text`, `sqlite3_bind_blob`, `sqlite3_bind_null`, `sqlite3_bind_parameter_count` |
| Error / status | `sqlite3_errmsg`, `sqlite3_errcode`, `sqlite3_extended_errcode`, `sqlite3_changes`, `sqlite3_last_insert_rowid` |
| Concurrency | `sqlite3_busy_timeout` |

Deferred to follow-up parts: `sqlite3_create_function*`,
`sqlite3_backup_*`, `sqlite3_blob_open`, `sqlite3_stmt_status`,
incremental BLOB I/O, virtual tables (`sqlite3_module`),
authorizers, hooks, the `_v3` prepare variant with prepFlags.

## Declared shapes

The shapes for this part live alongside this `master.md` in
`shapes.json`. They are:

- `Sqlite3` — opaque connection handle. Owns: a database (parser +
  compiler + VDBE + storage stack), the most-recent error code +
  message, the changes counter, the last insert rowid, the
  busy-timeout milliseconds, and the threading mode tag.
- `Sqlite3Stmt` — opaque prepared-statement handle. Wraps a
  `PreparedStatement` (from the sibling part) plus a row cursor,
  the column-name vector frozen at prepare time, and the
  bind-parameter values vector. The handle holds a back-reference
  to its owning `Sqlite3` for error reporting.
- `ResultCode` — alias for the integer ABI return codes (table
  below). Every shim function returns one.
- `ColumnTypeCode` — alias for the column-type integer codes
  (table below).
- `OpenFlags` — alias for the bit-flag set passed to
  `sqlite3_open_v2` (`READONLY`, `READWRITE`, `CREATE`,
  `MEMORY`, `URI`, `NOMUTEX`, `FULLMUTEX`).
- `TextEncoding` — variant `UTF8 | UTF16LE | UTF16BE`. v1 admits
  UTF-8 only; UTF-16 entry points map UTF-16 → UTF-8 at the
  boundary.

The shim functions (`sqlite3_open`, `sqlite3_step`, etc.) are
declared in the `functions` section of `shapes.json`. Each is a
free function whose first parameter is the connection or
statement handle.

## Result codes (ABI-stable, do not renumber)

The shim must return exactly these integer values; downstream
applications compare numerically.

| Name | Value | Meaning |
|------|-------|---------|
| `SQLITE_OK` | 0 | Success |
| `SQLITE_ERROR` | 1 | Generic SQL or processing error |
| `SQLITE_BUSY` | 5 | Database file locked by another connection |
| `SQLITE_LOCKED` | 6 | Table within the database is locked |
| `SQLITE_NOMEM` | 7 | Allocation failure |
| `SQLITE_READONLY` | 8 | Attempt to write to a read-only database |
| `SQLITE_INTERRUPT` | 9 | Operation terminated by `sqlite3_interrupt` |
| `SQLITE_IOERR` | 10 | Disk I/O error |
| `SQLITE_CORRUPT` | 11 | Database file is malformed |
| `SQLITE_NOTFOUND` | 12 | Internal: table or record not found |
| `SQLITE_FULL` | 13 | Database or disk full |
| `SQLITE_CANTOPEN` | 14 | Unable to open database file |
| `SQLITE_PROTOCOL` | 15 | Database lock protocol error |
| `SQLITE_EMPTY` | 16 | Internal use; reserved |
| `SQLITE_SCHEMA` | 17 | Schema changed since prepare |
| `SQLITE_TOOBIG` | 18 | String/BLOB exceeds size limit |
| `SQLITE_CONSTRAINT` | 19 | Constraint violation |
| `SQLITE_MISMATCH` | 20 | Datatype mismatch |
| `SQLITE_MISUSE` | 21 | Library used incorrectly |
| `SQLITE_NOLFS` | 22 | OS lacks large-file support |
| `SQLITE_AUTH` | 23 | Authorization denied |
| `SQLITE_FORMAT` | 24 | Auxiliary format error |
| `SQLITE_RANGE` | 25 | Bind slot out of range |
| `SQLITE_NOTADB` | 26 | File is not a database |
| `SQLITE_ROW` | 100 | `sqlite3_step` produced a row |
| `SQLITE_DONE` | 101 | `sqlite3_step` reached completion |

Mapping from internal `RuntimeCondition` / `PrepareError` /
`BindError` / `StepError` variants to result codes lives in this
spec (see "Error mapping" below). It is a total function — every
internal condition must land on exactly one ABI code.

## Column type codes (ABI-stable, do not renumber)

`sqlite3_column_type(stmt, col)` returns one of:

| Name | Value | Internal `Value` variant |
|------|-------|--------------------------|
| `SQLITE_INTEGER` | 1 | `Integer(i64)` |
| `SQLITE_FLOAT` | 2 | `Real(f64)` |
| `SQLITE_TEXT` | 3 | `Text(string)` |
| `SQLITE_BLOB` | 4 | `Blob(bytes)` |
| `SQLITE_NULL` | 5 | `Null` |

These are the canonical 5 codes. The shim does not invent
additional codes.

## Open flags (ABI-stable bit set)

| Name | Value | Meaning |
|------|-------|---------|
| `SQLITE_OPEN_READONLY` | 0x00000001 | Open existing DB read-only |
| `SQLITE_OPEN_READWRITE` | 0x00000002 | Open existing DB read-write |
| `SQLITE_OPEN_CREATE` | 0x00000004 | Create if missing |
| `SQLITE_OPEN_URI` | 0x00000040 | Filename is a URI |
| `SQLITE_OPEN_MEMORY` | 0x00000080 | In-memory only |
| `SQLITE_OPEN_NOMUTEX` | 0x00008000 | Multi-thread mode (no mutex) |
| `SQLITE_OPEN_FULLMUTEX` | 0x00010000 | Serialized mode (full mutex) |

`sqlite3_open(filename, db_out)` is equivalent to
`sqlite3_open_v2(filename, db_out, READWRITE | CREATE, NULL)`.

## Threading model

Three modes, as declared on `Sqlite3` at open time. The shim does
NOT mandate a particular target's locking primitive; each target
mapping describes what "serialized" / "multi-thread" /
"single-thread" mean idiomatically (a mutex around state in C and
Rust; a GIL-bounded boundary in Python; etc.).

- **Single-thread**: caller promises only one thread ever touches
  any handle. No internal locking. (`SQLITE_OPEN_NOMUTEX` set,
  `FULLMUTEX` clear, library compiled `-DSQLITE_THREADSAFE=0`
  equivalent.)
- **Multi-thread**: distinct connections may be used concurrently
  on distinct threads; a single connection is single-threaded.
  This is the default. (`SQLITE_OPEN_NOMUTEX` set on a
  per-connection basis, library `THREADSAFE=2` equivalent.)
- **Serialized**: any connection may be used from any thread;
  the shim serializes access internally. (`SQLITE_OPEN_FULLMUTEX`
  set, library `THREADSAFE=1` equivalent.)

The choice does not change ABI return values; it changes only
whether two threads racing on a handle is defined behaviour
(serialized) or `SQLITE_MISUSE` (single-thread / multi-thread
violated).

## Memory ownership

The shim is the only LEAP-SQLite layer that allocates buffers
visible to a foreign caller. The discipline is the
mainline-published one and is the spec; per-target mappings choose
the idiomatic implementation primitive (calloc / Box::leak / Go
cgo handle, etc.).

- `sqlite3_malloc(n)` / `sqlite3_realloc(p, n)` / `sqlite3_free(p)`
  are the canonical allocation entry points. Buffers handed out by
  the shim (e.g. the duplicated `errmsg` returned by
  `sqlite3_exec`) are owned by the caller and must be released via
  `sqlite3_free`.
- Pointers returned by `sqlite3_column_text(stmt, i)` and
  `sqlite3_column_blob(stmt, i)` are owned by the **statement**
  and remain valid until the next `sqlite3_step`,
  `sqlite3_reset`, `sqlite3_finalize`, or any subsequent
  `sqlite3_column_*` call that triggers a type conversion on the
  same column. Callers that need to keep the data must copy.
- Pointers returned by `sqlite3_column_name(stmt, i)` are owned
  by the statement and remain valid until `sqlite3_finalize`.
- `sqlite3_errmsg(db)` returns a pointer owned by the connection
  and valid until the next call on that connection that overwrites
  the error slot, or `sqlite3_close`.
- `sqlite3_bind_text` / `sqlite3_bind_blob` accept a destructor
  parameter:
  - `SQLITE_STATIC` (= 0): caller promises the pointer outlives
    every step on this statement until `sqlite3_finalize` or the
    next bind on the same slot. Shim does not copy.
  - `SQLITE_TRANSIENT` (= -1, cast to pointer): shim copies the
    buffer immediately into shim-owned memory; caller may free
    its copy after the bind returns.
  - any other pointer value: a destructor function the shim must
    invoke once it is done with the buffer.

## Correctness pins

Numbered. These are the contractual invariants every target's
emission must satisfy. A target whose generated shim violates a
pin is a spec failure on that target.

1. **Result-code totality.** Every shim function returns a
   `ResultCode` from the table above. There is no "unknown" or
   negative return; each internal condition maps to exactly one
   listed code. The mapping table is authoritative; targets must
   not invent additional codes.

2. **`SQLITE_OK == 0`.** The literal numeric value of
   `SQLITE_OK` is `0`. `if (rc != 0)` is the canonical caller
   idiom and must keep working.

3. **`SQLITE_ROW == 100`, `SQLITE_DONE == 101`.** `sqlite3_step`
   returns `SQLITE_ROW` per emitted row, `SQLITE_DONE` exactly
   once after the final row, and any other code on error. After
   `SQLITE_DONE` or any error, the next `step` (without a
   `reset`) returns `SQLITE_MISUSE`.

4. **Opaque handles.** `Sqlite3` and `Sqlite3Stmt` are opaque to
   foreign callers. The shim never exposes layout, never invites
   pointer arithmetic, and never leaks a back-reference that
   outlives the handle. A target's emission MUST map both to a
   pointer-sized opaque handle in C-callable code.

5. **NULL-handle safety.** Passing a null pointer for `db` or
   `stmt` to any shim function returns `SQLITE_MISUSE`; the
   shim does not dereference. A null `db` to `sqlite3_close` is
   a no-op returning `SQLITE_OK` (matches mainline).

6. **`sqlite3_open` allocates and returns the handle out-param
   even on failure.** `sqlite3_open(filename, &db)` writes either
   a usable handle or a sentinel handle carrying the failure
   reason. The caller must always invoke `sqlite3_close(db)`.
   `sqlite3_close` on a sentinel handle releases its error
   message and returns `SQLITE_OK`.

7. **`sqlite3_close` returns `SQLITE_BUSY` if any unfinalized
   statement is outstanding.** The connection is not destroyed
   until every prepared statement on it has been finalized.
   `sqlite3_close_v2` defers the destruction (zombies the
   connection until the last statement finalizes) and always
   returns `SQLITE_OK`.

8. **`sqlite3_prepare_v2` arity.** The returned statement carries
   the parameter count `bind_parameter_count` reports. It equals
   the count of distinct anonymous `?` placeholders observed at
   parse (matching the sibling `prepared-statement` part). Slot
   indices for `bind_*` are 1-based; `0` and `> arity` are
   `SQLITE_RANGE`.

9. **Tail handling.** `sqlite3_prepare_v2(db, sql, n_byte, stmt_out,
   tail_out)` writes into `*tail_out` a pointer to the first byte
   of `sql` not consumed by the prepared statement (or to the
   trailing NUL byte if all consumed). The pointer aliases the
   caller's input buffer; the caller owns the lifetime.

10. **`sqlite3_step` lifecycle.** Legal call sequence:
    `prepare → (bind*)? → step+ → reset → (bind*)? → step+ → ... →
    finalize`. `step` after a `step` that returned `SQLITE_DONE`
    or any error code, without an intervening `reset`, is
    `SQLITE_MISUSE`. `step` on a finalized statement is
    `SQLITE_MISUSE`.

11. **`sqlite3_reset` rewinds, does not unbind.** After `reset`,
    the next `step` starts from PC 0 with the SAME bound values.
    Bindings are cleared only by `sqlite3_clear_bindings` (deferred
    in v1; targets MAY emit it as a thin wrapper that writes
    `Value::Null` to every slot). This matches Pin 7 of the
    sibling `prepared-statement` part.

12. **`sqlite3_reset` returns the prior step's error code.** If
    the most recent `step` returned an error code,
    `sqlite3_reset` returns the same code. Otherwise it returns
    `SQLITE_OK`. (A documented mainline quirk; matters for caller
    error-handling loops.)

13. **`sqlite3_finalize` is idempotent on a null pointer.**
    `sqlite3_finalize(NULL)` returns `SQLITE_OK`. Otherwise it
    returns the prior step's error code (same convention as
    `reset`) and releases all statement-owned memory.

14. **Bind-out-of-range is `SQLITE_RANGE`.** Slot index `0` or
    `> arity` from any `sqlite3_bind_*` returns `SQLITE_RANGE`
    and does not mutate the bindings vector.

15. **Bind-text encoding.** v1 admits UTF-8 text only.
    `sqlite3_bind_text16` / `sqlite3_column_text16` are deferred;
    targets MAY emit them as transcoding wrappers but are not
    required to in v1. The shim always reports
    `SQLITE_UTF8` (= 1) as the database text encoding.

16. **Column-count is fixed at prepare time.** `sqlite3_column_count`
    returns the same value for the lifetime of the statement; it
    is computed once during compilation and stored on
    `Sqlite3Stmt`. `sqlite3_column_name(stmt, i)` returns the
    same pointer (per-statement-owned) on every call for the same
    `i`.

17. **Column accessors are safe before the first `step`.** Before
    the first `SQLITE_ROW`, `sqlite3_column_count` and
    `sqlite3_column_name` return their compile-time values;
    `sqlite3_column_type` returns `SQLITE_NULL`; `_int` /
    `_int64` / `_double` return zero; `_text` / `_blob` return a
    null pointer; `_bytes` returns `0`. After `SQLITE_DONE` the
    same defaults apply.

18. **Column type-code mapping is exhaustive.** Every internal
    `Value` variant maps to exactly one `ColumnTypeCode` from the
    table above. There is no "other"; an internal extension that
    introduces a new variant is a spec gap.

19. **Type conversions in column accessors.** `sqlite3_column_int`
    on `Real` truncates toward zero; on `Text` parses the leading
    integer prefix per mainline rules; on `Blob` returns 0; on
    `Null` returns 0. `_double` mirrors with float coercion.
    `_text` on `Integer` / `Real` materializes the canonical
    string form into statement-owned memory and the resulting
    pointer is valid for the lifetime described under "Memory
    ownership". Calling `_text` then `_int` then `_text` on the
    same column is permitted; the second `_text` may invalidate
    the first `_text` pointer.

20. **`sqlite3_changes` reports the row count of the most recent
    INSERT / UPDATE / DELETE on this connection only.** SELECT,
    DDL, and PRAGMA do not reset it; another DML statement does.
    `sqlite3_last_insert_rowid` is sticky across SELECT and
    PRAGMA but updated by every successful INSERT.

21. **`sqlite3_errmsg(db)` returns a non-null UTF-8 pointer.**
    On a connection with no error it returns a pointer to the
    static string `"not an error"` (matching mainline). The
    pointer is valid until the next operation on `db` that may
    update the error slot.

22. **`sqlite3_busy_timeout(db, ms)` registers a default wait
    policy.** Subsequent operations that would return
    `SQLITE_BUSY` instead retry (with monotonic backoff) for up
    to `ms` milliseconds before reporting `SQLITE_BUSY`.
    `ms <= 0` disables the policy. The retry loop is
    cooperatively cancellable via `sqlite3_interrupt` (deferred:
    targets MAY no-op `sqlite3_interrupt` in v1).

23. **`sqlite3_exec(db, sql, callback, ctx, errmsg_out)`** parses
    `sql` as a sequence of one or more semicolon-separated
    statements and runs each via the prepare → step → finalize
    lifecycle. For each row of each row-producing statement the
    `callback` is invoked with `ctx`, the column count, an array
    of UTF-8 column-value strings (NULL pointer for `SQLITE_NULL`),
    and an array of column-name strings. A non-zero callback
    return aborts execution and returns `SQLITE_ABORT` (= 4); a
    null callback runs all statements without producing rows. On
    error, if `errmsg_out` is non-null, the shim duplicates the
    error message into `sqlite3_malloc`-owned memory and writes
    its pointer there; the caller frees with `sqlite3_free`.

24. **Error mapping is total and stable.** Every internal
    condition surfaces at this boundary. Mapping table:
    - `PrepareError::Lex(_)` / `Parse(_)` / `Compile(_)` →
      `SQLITE_ERROR`
    - `PrepareError::SchemaMissing` → `SQLITE_ERROR` (mainline
      uses `SQLITE_ERROR` with errmsg `"no such table: ..."`)
    - `BindError::SlotOutOfRange` → `SQLITE_RANGE`
    - `BindError::TypeMismatch` → `SQLITE_MISMATCH`
    - `RuntimeCondition::Constraint(_)` → `SQLITE_CONSTRAINT`
    - `RuntimeCondition::Locked` → `SQLITE_LOCKED`
    - `RuntimeCondition::Busy` → `SQLITE_BUSY`
    - `RuntimeCondition::Readonly` → `SQLITE_READONLY`
    - `RuntimeCondition::Corrupt` → `SQLITE_CORRUPT`
    - `RuntimeCondition::IoError` → `SQLITE_IOERR`
    - `RuntimeCondition::OutOfMemory` → `SQLITE_NOMEM`
    - `RuntimeCondition::Full` → `SQLITE_FULL`
    - `RuntimeCondition::Mismatch` → `SQLITE_MISMATCH`
    - `RuntimeCondition::Interrupt` → `SQLITE_INTERRUPT`
    - any unmatched / unforeseen condition → `SQLITE_ERROR`
      (never `SQLITE_OK`).

25. **No internal panic / abort across the shim boundary.** Every
    target's emission must catch internal aborts (Rust panics,
    Zig `unreachable`, Go panics, Python exceptions) and convert
    them to `SQLITE_ERROR` with `errmsg` set. The C shim is the
    public face of the library; it must never crash the host
    process from a SQL-input-triggered fault.

## Algorithm sketches

### `sqlite3_open_v2(filename, &db, flags, vfs)`

1. Allocate a `Sqlite3` shell with empty error slot and
   `changes = 0`, `last_insert_rowid = 0`, `busy_timeout_ms = 0`.
2. Determine open mode from `flags` per the table above. If
   `MEMORY` set or filename is `":memory:"`, allocate an
   in-memory database. Otherwise resolve the filesystem path and
   open via `/parts/storage` honouring `READONLY` / `READWRITE` /
   `CREATE`.
3. On failure, populate the connection's error slot with the
   mapped `ResultCode` + UTF-8 message; write the (sentinel)
   handle into `*db`; return the mapped code.
4. On success, write the handle and return `SQLITE_OK`.

### `sqlite3_prepare_v2(db, sql, n_byte, &stmt, &tail)`

1. Bound `sql` by `n_byte` (negative = treat as NUL-terminated).
2. Invoke the parser; on first failure, write the unconsumed tail
   pointer (if `tail` non-null), populate `db`'s error slot, and
   return `SQLITE_ERROR`. `*stmt` is null on failure.
3. Dispatch to the matching statement compiler; produce the
   `Program`, the compile-time `column_names` vector, and the
   `arity`.
4. Allocate a `Sqlite3Stmt` wrapping the `PreparedStatement`,
   the column-name vector, an empty `BoundParams` sized to
   `arity` filled with `Value::Null`, and a back-pointer to `db`.
5. Write the unconsumed tail pointer (or pointer-to-NUL if all
   consumed); write `*stmt` and return `SQLITE_OK`.

### `sqlite3_step(stmt)`

Delegates to the sibling `prepared-statement` part's `step`.
Translate the `StepResult`:
- `Row` → set the row cursor on `stmt`, return `SQLITE_ROW`.
- `Done` → clear the row cursor, set `last_insert_rowid` and
  `changes` on `stmt.db` if the statement was a DML; return
  `SQLITE_DONE`.
- `Error(cond)` → populate the connection's error slot via the
  mapping in Pin 24; return the mapped code.

### `sqlite3_column_<T>(stmt, i)`

1. If `stmt` is null or no current row is held, return the
   pre-step / post-done default per Pin 17.
2. Fetch the value at column `i` of the current row.
3. Apply the type conversion rules from Pin 19; cache any
   freshly-materialized buffer (e.g. integer-as-text) in the
   per-column statement-owned slot, evicting the previous
   buffer for that column.
4. Return the typed value (or pointer + bytes for `_text` /
   `_blob`).

### `sqlite3_finalize(stmt)`

1. If `stmt` is null, return `SQLITE_OK`.
2. Capture the most recent step's mapped result code (or
   `SQLITE_OK` if none).
3. Release the `Program`, column-name vector, bound-params
   vector, per-column materialization buffers, and back-reference
   to the connection. If the connection is in a `close_v2` zombie
   state and this was its last statement, finalize the connection
   too.
4. Return the captured code.

## Per-target mapping notes

The 5 targets' `parts/targets/<lang>/mapping.md` files describe
how this part is rendered idiomatically:

- **C**: emits a `sqlite3.h` header declaring the opaque
  `struct sqlite3` and `struct sqlite3_stmt` plus the function
  prototypes; `c_abi.c` defines them by holding a pointer to the
  internal `lib_api` types. Result-code constants are `#define`d
  in the header to the canonical integer values.
- **Rust**: emits `#[no_mangle] extern "C" fn sqlite3_*` symbols
  in `c_abi.rs` that wrap the safe `lib_api::prepared_statement`
  surface; opaque handles render as `*mut Sqlite3` /
  `*mut Sqlite3Stmt` over `Box`-allocated structs; panics are
  caught at the boundary via `std::panic::catch_unwind` and
  mapped to `SQLITE_ERROR`.
- **Zig**: emits `export fn sqlite3_*` with C-calling-convention;
  opaque handles are `*Sqlite3` / `*Sqlite3Stmt` allocated from
  the `lib_api` allocator; errors are mapped via a switch on the
  internal `RuntimeCondition` enum.
- **Go**: emits a cgo-flavoured shim in `c_abi.go` using
  `//export sqlite3_*`; opaque handles are returned via cgo
  handle indirection (`runtime/cgo.Handle`); recovered panics
  map to `SQLITE_ERROR`.
- **Python**: emits a `ctypes`-friendly module that mimics the
  shim surface in pure Python over `lib_api.prepared_statement`;
  exists for cross-target eq-harness coverage rather than as a
  consumable C ABI (Python cannot expose true `extern "C"`).

Mapping files in `parts/targets/<lang>/mapping.md` are the
canonical site for any toolchain pin (Pin "toolchain pin"
discipline applies — name the cgo / wasm-bindgen / rust-cc
version and the libc / WinAPI surface relied on).

## Out of scope (deferred)

- `sqlite3_create_function*`, `sqlite3_create_collation*`,
  `sqlite3_create_module*` — the extension-author surface.
- `sqlite3_backup_*`, `sqlite3_blob_*` — incremental I/O.
- `sqlite3_prepare_v3` `prepFlags`, `sqlite3_stmt_status`,
  `sqlite3_db_status` — stats / hint surface.
- `sqlite3_progress_handler`, `sqlite3_commit_hook`,
  `sqlite3_update_hook`, authorizers — observability surface.
- `sqlite3_bind_text16` / `sqlite3_column_text16` — UTF-16
  variants. May be added in a follow-up part once the encoding
  story (Pin 15) needs to admit UTF-16 callers.
- `sqlite3_serialize` / `sqlite3_deserialize` — in-memory DB
  marshalling.
