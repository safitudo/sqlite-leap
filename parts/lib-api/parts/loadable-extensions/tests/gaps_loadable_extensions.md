# loadable-extensions — gaps

## Surface today
- `src-rust/loadable_extensions.rs` (531 LOC) is purely a C-ABI surface: `extern "C" sqlite3_load_extension`, `sqlite3_enable_load_extension`, the `Sqlite3ApiRoutines` shim table, dlopen/dlsym mapping (libloading), and the `fallback_symbol` filename → entry-point name heuristic.
- Per `parts/lib-api/parts/loadable-extensions/` the module is exposed to programs that link against the `cdylib` build of leap_sqlite. That's the bar: cdylib clients can call `sqlite3_load_extension` from C / FFI.

## SLT-visible blocker
- No SQL-side surface exists. There is no `load_extension(...)` scalar builtin (would live in `parts/builtins/...` or `scalar_*.rs`), and there is no `PRAGMA load_extension_enabled` arm — the slt_runner dispatch silently no-ops every PRAGMA.
- Therefore from `.slt`, the *only* observable behaviors are:
  - `SELECT load_extension('/anything')` → compile error (no such scalar) → `statement error` PASSes,
  - `PRAGMA load_extension_enabled = 1` → silent OK (no real toggle) → `statement ok` PASSes vacuously.
- Loading a real `.so` from a test would also be fragile (path / arch / glibc), so even with a SQL surface this should stay an error-path probe.

## What the smoke pins (7/7 PASS)
- Baseline CREATE/INSERT/SELECT live (3 records).
- `SELECT load_extension('/nonexistent.so')` errors out (1).
- 2-arg overload `load_extension(path, entry)` errors out (1).
- `PRAGMA load_extension_enabled = 1 / 0` silently OK (2 — documents the no-op bar).

## Wiring needed
1. Add a SQL scalar `load_extension(path [, entry])` that bridges to `sqlite3_load_extension` under a runtime-toggle gate. Spec pin: `parts/lib-api/parts/loadable-extensions/master.md` already pins the C-ABI; an SQL bridge needs its own master.md (compiler-side scalar dispatch + a per-Catalog "extensions enabled" boolean).
2. Real `PRAGMA load_extension_enabled` arm in `run_statement` (currently catch-all PRAGMA → no-op) so the `=0` case can refuse subsequent `load_extension(...)` calls.
3. Test fixture: a tiny harmless extension `.dylib` / `.so` co-emitted by the build, loaded into a temp DB, exposing one custom scalar — and an error-only smoke variant for `--no-extensions` builds.

## Honest stance
Today the load_extension surface from SLT *is* an error path. The smoke doesn't pretend otherwise. Mark this module's SLT coverage as "documents-the-blocker" until the SQL-scalar bridge lands.
