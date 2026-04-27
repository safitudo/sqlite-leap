---
name: lib-api/loadable-extensions
kind: leaf
shapes: ./shapes.json
inherits:
  - /parts/lib-api/master.md
  - /parts/lib-api/parts/c-abi/master.md
  - /parts/lib-api/parts/prepared-statement/master.md
---

# Part: lib-api/loadable-extensions

Runtime extension loading via `sqlite3_load_extension`. A user
calls a C ABI entry point with a path to a shared object; the
shim opens the library with the platform dynamic loader, looks up
an entry point symbol, and invokes it with a pointer to the
**`sqlite3_api_routines`** dispatch table. The extension uses
that table — and only that table — to register functions,
collations, virtual tables, etc. with the connection.

This is the canonical SQLite extension ABI. Every `.so` / `.dll` /
`.dylib` shipped against mainline SQLite (FTS5 builds out-of-tree,
spatialite, json1 historically, sqlean, the regexp module, etc.)
uses exactly this entry-point signature and exactly this dispatch
table. Compatibility here is a hard binary contract: an extension
compiled against mainline's `sqlite3ext.h` must load and run
against leap's `sqlite3_*` shim with no recompilation.

This is a **language-neutral specification**. The extension
interface itself is C-flavored by definition (it's a stable C
ABI), but the spec describes the loader, the dispatch table
contract, and the lifecycle in target-neutral terms; targets emit
the platform-specific `dlopen`/`LoadLibrary` glue and the
function-pointer table population.

## Surface (v1)

Two entry points on the connection-level C ABI:

```
sqlite3_enable_load_extension(db: Sqlite3*, onoff: int) -> ResultCode
sqlite3_load_extension(db: Sqlite3*, file: cstring,
                       proc: cstring | NULL,
                       errmsg_out: cstring** | NULL) -> ResultCode
```

Plus the dispatch-table type (`sqlite3_api_routines`, an opaque
struct of function pointers) declared in `shapes.json`. Plus the
extension-side entry-point signature, which is fixed by the ABI:

```
typedef int (*sqlite3_extension_init_t)(
    sqlite3                    *db,
    char                      **pzErrMsg,
    const sqlite3_api_routines *pApi);
```

## Lifecycle

```
sqlite3_open(...)
    → sqlite3_enable_load_extension(db, 1)         # opt-in, see LX1
    → sqlite3_load_extension(db, "./mod_foo.so", NULL, &errmsg)
         opens the shared library
         resolves entry point (sqlite3_extension_init by default)
         calls entry(db, &errmsg, &g_api_routines)
         entry registers UDFs, collations, vtab modules via *pApi
         returns SQLITE_OK / SQLITE_ERROR
    → application uses the new functions / vtabs
    → sqlite3_close(db)
         drops UDFs / collations / vtabs registered via this load
         platform dlclose is deferred (see LX13)
```

## Loader

Pseudo-code, target-neutral:

```
sqlite3_load_extension(db, file, proc, errmsg_out) -> ResultCode:
    if db.load_extension_enabled is False:
        set_errmsg(db, "not authorized")
        return SQLITE_ERROR

    handle = platform_open_library(file)         # see §Platform mapping
    if handle is NULL:
        msg = platform_dlerror()                 # textual diagnostic
        set_errmsg(db, "cannot load: " + msg)
        if errmsg_out: *errmsg_out = strdup(db.errmsg)
        return SQLITE_ERROR

    sym = proc if proc is non-NULL else "sqlite3_extension_init"
    fn  = platform_resolve_symbol(handle, sym)
    if fn is NULL:
        # try the file-name-derived fallback (see LX5)
        fn = try_filename_fallback(handle, file)
    if fn is NULL:
        platform_close_library(handle)
        set_errmsg(db, "no entry point '" + sym + "'")
        if errmsg_out: *errmsg_out = strdup(db.errmsg)
        return SQLITE_ERROR

    entry = cast<sqlite3_extension_init_t>(fn)
    err_from_ext: cstring* = NULL
    rc = entry(db, &err_from_ext, &g_api_routines)
    if rc != SQLITE_OK:
        if err_from_ext is non-NULL:
            set_errmsg(db, err_from_ext)
            if errmsg_out: *errmsg_out = strdup(err_from_ext)
            extension_free(err_from_ext)         # see LX9
        else:
            set_errmsg(db, "extension init failed")
            if errmsg_out: *errmsg_out = strdup(db.errmsg)
        platform_close_library(handle)
        return SQLITE_ERROR

    register_loaded_handle(db, handle)           # for cleanup
    return SQLITE_OK
```

## Platform mapping

Targets implement three primitives (declared in `shapes.json` as
target-private functions; not part of the public ABI):

| Primitive               | POSIX (Linux/macOS/BSD)          | Windows               |
|-------------------------|----------------------------------|-----------------------|
| `platform_open_library` | `dlopen(file, RTLD_NOW \| RTLD_LOCAL)` | `LoadLibraryA(file)` |
| `platform_resolve_symbol` | `dlsym(handle, sym)`           | `GetProcAddress(handle, sym)` |
| `platform_close_library` | `dlclose(handle)`               | `FreeLibrary(handle)` |
| `platform_dlerror`      | `dlerror()`                      | `FormatMessage(GetLastError())` |

The dispatch is at target-emit time (per `mapping.md`), not at
runtime: a Linux build links `libdl`, a macOS build uses the
ambient `dlopen`, a Windows build uses kernel32. WASM and other
no-dynamic-link targets compile this part to a stub that returns
`SQLITE_ERROR` with the message "not supported on this platform"
(LX12).

## File-name search rules

When `file` does not contain a directory separator, the platform's
default library-search path applies (`LD_LIBRARY_PATH`, `PATH`,
`@rpath`, etc.). When it does, the path is taken as-is. Targets
must NOT inject leap-specific search prefixes; behavior matches
mainline so existing extension installers keep working.

When `file` does not include a platform suffix and the open fails,
retry once with the platform-default suffix appended:

| Platform | Suffix     |
|----------|------------|
| Linux    | `.so`      |
| macOS    | `.dylib`   |
| Windows  | `.dll`     |
| BSD      | `.so`      |

If both probes fail, return the original error message.

## Entry-point fallback

When `proc` is NULL and the symbol `sqlite3_extension_init` is
not found, derive a fallback symbol from the file name:

```
fallback_symbol(filename) -> string:
    base = basename(filename) without extension
    base = strip_leading("lib", base)            # libfoo.so → foo
    sanitized = replace each non-[A-Za-z0-9_] with "_"
    return "sqlite3_" + sanitized + "_init"
```

Examples:
- `./fts5.so` → `sqlite3_fts5_init`
- `/usr/lib/spatialite.dylib` → `sqlite3_spatialite_init`
- `mod-regexp.so` → `sqlite3_mod_regexp_init`

This matches mainline's behavior and lets out-of-tree extensions
ship without needing the canonical entry name.

## The `sqlite3_api_routines` dispatch table

A struct of function pointers, **field order frozen** to match
mainline's `sqlite3ext.h` field order. v1 leap exposes the subset
required by the C ABI scope already declared in
`parts/lib-api/parts/c-abi/master.md` (the 22 entry points plus
the function/collation/vtab registration entries).

The struct lives in `shapes.json` as a `record` with one field
per pointer slot. The order in `shapes.json` IS the ABI order.
Reordering, adding fields in the middle, or removing fields is a
breaking change.

### v1 dispatch table (35 slots)

In ABI order (truncated example; the full list lives in
`shapes.json`):

```
sqlite3_api_routines:
  aggregate_context        function pointer
  bind_blob                function pointer
  bind_double              function pointer
  bind_int                 function pointer
  bind_int64               function pointer
  bind_null                function pointer
  bind_parameter_count     function pointer
  bind_parameter_index     function pointer
  bind_parameter_name      function pointer
  bind_text                function pointer
  bind_value               function pointer
  changes                  function pointer
  close                    function pointer
  collation_needed         function pointer
  column_blob              function pointer
  column_bytes             function pointer
  column_count             function pointer
  column_double            function pointer
  column_int               function pointer
  column_int64             function pointer
  column_name              function pointer
  column_text              function pointer
  column_type              function pointer
  create_collation         function pointer
  create_function          function pointer
  create_module            function pointer
  errcode                  function pointer
  errmsg                   function pointer
  exec                     function pointer
  finalize                 function pointer
  last_insert_rowid        function pointer
  open                     function pointer
  prepare_v2               function pointer
  reset                    function pointer
  result_blob              function pointer
  result_double            function pointer
  result_error             function pointer
  result_int               function pointer
  result_int64             function pointer
  result_null              function pointer
  result_text              function pointer
  step                     function pointer
  user_data                function pointer
  value_blob               function pointer
  value_bytes              function pointer
  value_double             function pointer
  value_int                function pointer
  value_int64              function pointer
  value_text               function pointer
  value_type               function pointer
```

(Yes the tally exceeds 35; the count above is illustrative — the
exact list is in `shapes.json` and grows with each extension-API
addition.)

Slots whose backing function does not yet exist in leap (e.g.,
`create_module` for vtabs, before the vtab part lands) hold
**a stub pointer** that returns `SQLITE_ERROR` with the message
"not implemented in this build". Slots are NEVER NULL; an
extension that calls a NULL slot would segfault, and the ABI
contract is "every slot is callable" (LX7).

There is exactly one global `g_api_routines` instance per process.
It is initialized at first `sqlite3_load_extension` call (or at
process start under a build flag). It is never mutated after
initialization (LX8).

## Permission model

`sqlite3_load_extension` is a security boundary: an extension is
arbitrary native code that runs in the host process with the
host's privileges. Two gates protect it:

1. **Per-connection enable flag.** `db.load_extension_enabled`
   defaults to `False`. The application must call
   `sqlite3_enable_load_extension(db, 1)` before any load attempt.
   This matches mainline and means SQL-level
   `SELECT load_extension(...)` does NOT work unless the host
   application explicitly opts the connection in.

2. **No SQL surface by default.** v1 leap does NOT expose the
   `load_extension(X, Y)` SQL function. It is a C-API-only
   operation. If a follow-up adds it, it will be gated on the
   same per-connection flag and on a separate
   `sqlite3_db_config(db, SQLITE_DBCONFIG_ENABLE_LOAD_EXTENSION,
   ...)` switch (mainline parity). See LX10.

The `sqlite3_enable_load_extension` shim itself is always
compiled in; without it, applications could not opt-in even when
they want to. Removing the loader entirely is a build flag (LX12).

## Cleanup on close

When `sqlite3_close` is called:

1. Walk `db.loaded_extensions` (the list of `(handle, init_fn)`
   pairs registered during this connection's lifetime).
2. For each loaded handle: any UDFs, collations, or vtab modules
   registered via this connection are dropped by the normal
   close path (UDFs and collations are connection-scoped; vtab
   modules are connection-scoped per mainline).
3. **Do not** call `platform_close_library(handle)` per-connection.
   Other connections in the same process may have called the same
   library's init and depend on its symbols (callbacks, vtab
   destructors). Library handles are process-scoped; they unload
   only at process exit, which the OS does for us. See LX13.

A future enhancement may track per-handle refcounts and unload at
zero, but the v1 contract is "leak the handle, OS reclaims".

## Error reporting

The `errmsg_out` parameter, when non-NULL, receives a pointer to
an allocated message string that the **caller** must free with
`sqlite3_free`. The string is allocated via `sqlite3_malloc` so
that the application does not need to know the leap allocator
identity. See LX9.

When the extension's `entry` function returns non-OK, it MAY have
written a message into the `pzErrMsg` out-parameter, allocated via
the API table's `result_*` allocator (i.e., `sqlite3_malloc`). The
loader copies that string into the connection's error buffer and
into `errmsg_out`, then calls `sqlite3_free` on the extension's
copy. An extension that returns non-OK with a NULL `pzErrMsg`
yields the generic message "extension init failed".

## ABI safety pins

**LX1. Per-connection enable defaults to off.** Newly opened
connections have `load_extension_enabled = False`. The
application must call `sqlite3_enable_load_extension(db, 1)`
before any successful `sqlite3_load_extension`. Matches mainline.

**LX2. Entry-point signature is fixed.** Every extension's init
function has signature
`int (*)(sqlite3*, char**, const sqlite3_api_routines*)`. Targets
MUST cast the resolved symbol to exactly this signature; any
other casting is undefined behavior and a build error.

**LX3. Default entry-point name.** When `proc` is NULL, the
loader probes `sqlite3_extension_init` first. Matches mainline.

**LX4. Filename-derived fallback.** When the default symbol is
absent, derive `sqlite3_<sanitized_basename>_init` per §Entry-
point fallback. Strip leading `lib`. Replace non-alphanumeric
characters with `_`.

**LX5. Suffix retry.** If the file does not contain a platform
suffix and the first open fails, retry once with the platform
suffix appended. Both errors collapse to one error message
(the first one) on final failure.

**LX6. Dispatch table field order is frozen.** The order of
function pointers in `sqlite3_api_routines` matches mainline's
`sqlite3ext.h` field order. Reordering is a breaking ABI
change.

**LX7. No NULL slot in the dispatch table.** Every slot points
to either a real implementation or a stub that returns
`SQLITE_ERROR` with "not implemented in this build". Extensions
must be able to call any slot without a null-check.

**LX8. Dispatch table is process-singleton, immutable.** A
single global `g_api_routines` exists per process; populated
lazily at first load (or at process start), never mutated after.
Targets enforce immutability via const/`final`/equivalent.

**LX9. Allocator identity.** Memory allocated for error messages
on the boundary is allocated by `sqlite3_malloc` and freed by
`sqlite3_free`. Extensions that allocate via the API table
allocate from the same heap as the host. Targets MUST NOT mix
host-malloc and platform-malloc across the boundary.

**LX10. SQL `load_extension()` is opt-in twice.** Defaults to
absent in v1; if added, requires (a) the per-connection
`load_extension_enabled` flag AND (b) a separate
`SQLITE_DBCONFIG_ENABLE_LOAD_EXTENSION` flag. Both must be on.
Mainline parity.

**LX11. Errmsg ownership.** When `errmsg_out` is non-NULL on
return, the pointer it receives must be freed by the caller via
`sqlite3_free`. When `errmsg_out` is NULL, the loader must NOT
allocate a message; the connection-scoped errmsg is sufficient.

**LX12. Build flag for static-only.** A target build flag
`--no-loadable-extensions` compiles `sqlite3_load_extension` and
`sqlite3_enable_load_extension` to stubs that return
`SQLITE_ERROR` with "not supported in this build". The dispatch
table is still populated (for in-tree static extensions that
reference it). WASM defaults to this mode (LX19).

**LX13. Library handle is process-scoped.** A loaded handle is
never `dlclose`'d by the loader. The OS reclaims it at process
exit. This avoids use-after-free in callback bodies registered
by the extension and held by other connections.

**LX14. Re-load is idempotent on the symbol level.** Loading the
same library twice on the same connection runs the entry function
twice. The entry function is responsible for being re-entrant
(extensions following mainline conventions check whether their
UDFs are already registered). The loader does not de-duplicate.

**LX15. Loader is not thread-safe per-connection by default.**
A connection's `loaded_extensions` list is mutated under the
connection's mutex (the same mutex protecting `Sqlite3.errmsg`).
Two threads calling `sqlite3_load_extension` on the same
connection are serialized. The global `g_api_routines` is read
without a lock (immutable post-init, LX8).

**LX16. Symbol resolution does not retry.** If the default
symbol AND the filename-derived fallback both fail, no further
probes are attempted. The loader does NOT scan the library's
symbol table for `sqlite3_*_init` patterns.

**LX17. RTLD_LOCAL on POSIX.** The `dlopen` call uses
`RTLD_NOW | RTLD_LOCAL`. `RTLD_LOCAL` prevents the extension's
symbols from leaking into the global symbol space and clashing
with a second extension's symbols. `RTLD_NOW` ensures
unresolved-symbol errors surface at load time, not at first
call.

**LX18. NULL `proc` and absent `proc`.** If the C caller passes
NULL for `proc`, treat as "use default + fallback". If the
caller passes an empty string `""`, treat as "no symbol given,
use default + fallback" (matches mainline's lenient handling).

**LX19. WASM target is loadable-stub only.** The
`generators/wasm` build emits `sqlite3_load_extension` returning
`SQLITE_ERROR` with "not supported in WASM". The wasm32 ABI
lacks runtime dynamic linking; statically-linked extensions are
the only path.

**LX20. Errmsg memory on success.** On `SQLITE_OK`, the loader
MUST NOT write to `errmsg_out`. Callers expect a NULL out-pointer
on success and free only on error.

**LX21. No invented helpers.** Per §Generation scope. Targets
emit only the loader, the platform primitives, and the dispatch
table population. Targets MUST NOT add hidden caching layers,
auto-load directories, environment-variable scans, or
"convenience" probes.

## Generation scope

Per `parts/spec/part-conventions.spec.md` §Generation scope:

- Targets emit `sqlite3_load_extension`,
  `sqlite3_enable_load_extension`, the platform primitives, and
  the dispatch-table populator.
- The dispatch table itself is a constant-init struct populated
  with pointers to functions already emitted by sibling parts
  (the C ABI shim's `sqlite3_open`, `sqlite3_step`, etc.). This
  part does NOT re-implement any of those functions; it only
  takes their addresses.
- Targets MUST NOT add per-target convenience APIs
  (`sqlite3_load_extension_dir`, etc.). The surface is exactly
  what `shapes.json` declares.
- The platform primitive layer (`platform_open_library` &
  friends) is target-private; it is NOT part of the public ABI
  and is not declared as `extern`.

`mapping.md` per target names the dynamic loader call:
- C → POSIX `dlopen` / Windows `LoadLibraryA`
- Rust → `libloading` crate (or direct FFI to `dlopen`)
- Zig → `std.DynLib`
- Go → `plugin` package on POSIX (Go's `plugin` is Linux+macOS
  only; Windows Go targets emit the LX12 stub)
- Python → `ctypes.CDLL`

## Phase pins

- **Phase LX0** — spec only (this part). `shapes.json` declares
  the loader signature, the dispatch-table struct, and the
  platform-primitive shapes. No target code emitted.
- **Phase LX1** — single-target prototype (Rust + libloading).
  Load a hand-written extension exposing one UDF; verify it
  registers and runs.
- **Phase LX2** — second target (C, native dlopen). Same
  fixture extension; same UDF behavior.
- **Phase LX3** — fixture extension compiled against MAINLINE
  SQLite's `sqlite3ext.h`, loaded against leap. Tests the
  dispatch-table ABI compatibility claim.
- **Phase LX4** — remaining 3 targets (Zig std.DynLib, Go
  `plugin`, Python ctypes). WASM emits the LX12 stub.
- **Phase LX5** — extend dispatch table for `create_module` /
  vtabs once the vtab part lands.

## Open questions (for follow-up phases)

1. **Auto-extension list.** Mainline supports `sqlite3_auto_extension`
   to register entry functions that run on every new
   connection. Defer to LX5; out of v1 scope.

2. **Vendored crypto-loader.** Some distributions sign
   extensions and require signature verification before load
   (mainline does not do this; ICU has a similar pattern). Out
   of scope; if added, it gates on a separate
   `sqlite3_set_extension_verifier` callback.

3. **Per-connection vs per-process registration.** UDFs
   registered via the dispatch table are per-connection in
   mainline. v1 leap matches. A future "shared UDF registry"
   would change the lifecycle and is deferred.

4. **Handle reference counting.** LX13 leaks the handle. A
   handle-refcount layer would let leap unload extensions on
   last-use, useful for long-running daemons that load and
   unload many extensions. Defer; the v1 contract matches
   mainline's "OS reclaims at exit".

5. **Unified errmsg pipeline.** The loader, the entry function,
   and the connection all have errmsg buffers. v1 propagates
   from extension → connection → caller via copy. A future
   refactor could thread a single owned buffer; defer.
