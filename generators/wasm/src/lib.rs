//! WASM wrapper for sqlite-leap.
//!
//! This crate is a thin convenience layer. The parent crate (`sqlite-leap` in
//! `../../src-rust/`) already exposes a complete C-ABI in its `wasm` module
//! (`leap_version`, `leap_alloc`, `leap_free`, `leap_db_new`, `leap_db_close`,
//! `leap_exec`). Those symbols, being `#[no_mangle] extern "C"` on the parent
//! crate, are propagated through the rlib into this crate's final
//! `wasm32-unknown-unknown` cdylib automatically — rustc emits every
//! `#[no_mangle]` function it compiled, regardless of which crate in the
//! dependency graph declared it.
//!
//! What this wrapper adds on top:
//!
//! - A `sqlite_leap_*`-prefixed public surface matching the task-spec shape:
//!   `sqlite_leap_open` / `sqlite_leap_exec` / `sqlite_leap_close`, plus
//!   companion `sqlite_leap_alloc` / `sqlite_leap_free` / `sqlite_leap_version`
//!   helpers so a caller doesn't have to mix the two naming conventions.
//!
//! - A `_force_link_engine_ffi` table: because the pass-through wrappers below
//!   could in principle be stripped if rustc decides none of them are
//!   reachable, we take function pointers to every engine FFI export. That
//!   forces the linker to retain them even under aggressive LTO.
//!
//! ## Design note — why not re-declare the engine's `leap_*` here?
//!
//! A prior version of this file re-exported `leap_alloc`, `leap_db_new`,
//! etc. as local `#[no_mangle] extern "C"` pass-through functions calling
//! `sqlite_leap::wasm::leap_alloc(..)`. That produced a wasm artifact with
//! infinite-loop function bodies: the wrapper's `leap_alloc` and the engine's
//! `leap_alloc` collapsed to the same `#[no_mangle]` symbol in the final
//! cdylib, so the call inside the wrapper resolved to itself. Lesson: never
//! re-declare a `#[no_mangle]` name that already exists in a dependency's
//! rlib — just let it propagate, and use rust-level paths to invoke it from
//! new wrapper functions with *different* export names.
//!
//! ## Gaps identified in the Rust engine's public API
//!
//! Flagging for a future spec revision (NOT fixing in src-rust/ per task
//! scope):
//!
//! 1. `Database::new()` is the only exposed constructor; there is no
//!    `Database::open(path)` for file-backed DBs. The WASM target has no
//!    useful file system anyway, but a sql.js-style "name this in-memory DB
//!    so you can reconnect to it" handle registry would help.
//!
//! 2. `leap_exec` always returns a full JSON buffer. For streaming large
//!    result sets out of wasm memory this is suboptimal — a cursor-style API
//!    (`leap_prepare` / `leap_step` / `leap_finalize`) would avoid copying
//!    the whole result set into a single allocation.
//!
//! 3. There is no `leap_last_insert_rowid` / `leap_changes` accessor. JS
//!    callers that want these today must parse the result JSON.
//!
//! 4. The parent crate pulls `std::fs` transitively. For a hermetic wasm
//!    build this is harmless (fs calls return errors at runtime on
//!    wasm32-unknown-unknown), but a future `no_fs` feature flag on
//!    sqlite-leap would shave a few KB of dead-stripped intrinsics.
//!
//! DO NOT CHEAT: everything here is composed from the engine's *public*
//! surface. No implementation borrowed from mainline SQLite, Turso, sql.js,
//! sqlite-wasm, or rusqlite.

use sqlite_leap::wasm as engine;

// ---------- Link-retention anchor ----------
//
// Collect raw function pointers to every engine FFI export into a static
// table. The static is `#[used]`, which tells the linker it must not be
// dropped even if nothing reads it. That in turn keeps each pointed-to
// function alive. Without this, `lto = "fat"` plus opt-level = "z" can decide
// the engine's `#[no_mangle]` functions are unreachable and strip them.
//
// Wrap the function-pointer array in a `Sync` newtype. Raw pointers are not
// `Sync` by default and `static` items must be `Sync`, but for a
// compile-time-constant keep-list with no runtime aliasing there is no
// soundness concern. The cast `fn(..) -> .. as *const ()` is legal in const
// context (unlike `as usize`, which is not).
struct SyncFnPtrs(#[allow(dead_code)] [*const (); 6]);
unsafe impl Sync for SyncFnPtrs {}

#[used]
static _FORCE_LINK_ENGINE_FFI: SyncFnPtrs = SyncFnPtrs([
    engine::leap_version as *const (),
    engine::leap_alloc as *const (),
    engine::leap_free as *const (),
    engine::leap_db_new as *const (),
    engine::leap_db_close as *const (),
    engine::leap_exec as *const (),
]);

// ---------- sqlite_leap_* public surface ----------
//
// These are the task-spec exports. They wrap the engine FFI under new names so
// there is no symbol collision. Each is a one-line forwarder; LTO inlines the
// body, so there's no performance cost.

/// Open a new database. Returns a non-zero handle on success; 0 on failure.
///
/// The filename pointer is currently ignored — every call produces a fresh
/// in-memory database. Pass 0 if you don't have a filename. See "Gaps" above.
#[no_mangle]
pub extern "C" fn sqlite_leap_open(_filename_ptr: u32) -> u32 {
    engine::leap_db_new()
}

/// Execute SQL against `handle`. Returns a packed `(ptr << 32) | len` pointing
/// at a UTF-8 JSON buffer that the caller MUST free with
/// `sqlite_leap_free(ptr, len)`.
///
/// The JSON shape matches the native cross-build harness:
///   success: `{"rows":[[...], [...]]}`
///   error:   `{"error":{"name":"...","fields":{...}}}`
#[no_mangle]
pub extern "C" fn sqlite_leap_exec(handle: u32, sql_ptr: u32, sql_len: u32) -> u64 {
    engine::leap_exec(handle, sql_ptr, sql_len)
}

/// Close a database previously returned by `sqlite_leap_open`.
/// Passing 0 or an already-closed handle is a silent no-op.
#[no_mangle]
pub extern "C" fn sqlite_leap_close(handle: u32) {
    engine::leap_db_close(handle);
}

/// Allocate `len` bytes in the wasm linear memory and return the pointer.
/// Returns 0 on failure (`len == 0` or OOM).
#[no_mangle]
pub extern "C" fn sqlite_leap_alloc(len: u32) -> u32 {
    engine::leap_alloc(len)
}

/// Free a buffer previously returned by `sqlite_leap_alloc` or the upper 32
/// bits of a `sqlite_leap_exec` result. `len` MUST match the original
/// allocation.
#[no_mangle]
pub extern "C" fn sqlite_leap_free(ptr: u32, len: u32) {
    engine::leap_free(ptr, len);
}

/// Version word: `major << 24 | minor << 16 | patch << 8 | build`.
#[no_mangle]
pub extern "C" fn sqlite_leap_version() -> u32 {
    engine::leap_version()
}
