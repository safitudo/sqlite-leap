# WASM FFI surface — language-neutral spec

Phase 7 exposes sqlite-leap through a minimal C-ABI surface suitable for the `wasm32-unknown-unknown` target. The same surface could be consumed from any language that speaks C ABI (Node.js WebAssembly, browsers, Python via ctypes, etc.), but Phase 7's target is browser/Node WASM.

This spec is Rust-target-only. The C target is not required to expose this surface — the C build produces a static library whose consumers use the native C headers.

## Scope (Phase 7)

- **Backend**: in-memory only. `wasm32-unknown-unknown` has no filesystem, so `open_database(path)` is NOT exposed. Only `create_database()` is reachable through the FFI. Phase 7 does NOT add WASI or any fs-backed WASM target; those are follow-up work.
- **Thread model**: single-threaded. No concurrency primitives.
- **Error surface**: FFI functions return a packed result (see "Packed result encoding" below). On error, the result is a JSON-encoded error object mirroring the native harness's error shape (name + fields).
- **Memory model**: the FFI uses explicit `leap_alloc` / `leap_free` entry points so the caller (JS) can write strings into WASM linear memory and pass `(ptr, len)` pairs. Rust owns the DB handles; JS holds opaque integer handles.

## FFI entry points

All entry points have C ABI (`#[no_mangle] pub extern "C"`).

### Memory management

```
fn leap_alloc(len: u32) -> u32
```
Allocate `len` bytes of Rust-owned memory and return its address in the WASM linear memory. The caller (JS) is expected to `leap_free` when done. Returns 0 if `len` is 0 or allocation fails.

```
fn leap_free(ptr: u32, len: u32) -> void
```
Free a region previously returned by `leap_alloc` OR by a `leap_exec` result's `ptr` field (see below). Caller MUST pass the matching `len`; passing a wrong `len` is undefined behaviour (same contract as Rust's `Box::from_raw` with slice length).

### Database handles

```
fn leap_db_new() -> u32
```
Create a fresh in-memory Database. Returns an opaque handle (non-zero) valid until `leap_db_close` is called. Handles are small integers assigned from a counter. Returns 0 on internal error.

```
fn leap_db_close(handle: u32) -> void
```
Release the database. After this, the handle is invalid. Calling `leap_exec` with an invalid handle returns a STORAGE-shaped error (see below).

### SQL execution

```
fn leap_exec(handle: u32, sql_ptr: u32, sql_len: u32) -> u64
```
Tokenize + parse + compile + run the UTF-8 SQL text at `(sql_ptr, sql_len)` against the database identified by `handle`. Returns a **packed result**: the upper 32 bits are a byte offset (pointer) to a UTF-8 JSON result buffer in WASM linear memory; the lower 32 bits are its length in bytes.

The caller MUST `leap_free(ptr, len)` on the returned buffer after consuming it.

### Packed result encoding

The returned u64 is `(ptr as u64) << 32 | (len as u64)`. JS unpacks as `[Number(r >> 32n), Number(r & 0xFFFFFFFFn)]`.

### Result JSON shape

A success result is:

```json
{"rows": [[<value>, ...], ...]}
```

where each `<value>` is a JSON number, string, or null — matching the mapping already established in the cross-build harness's JSON emission.

An error result is:

```json
{"error": {"name": "<ERR_NAME>", "fields": {<k>: <v>, ...}}}
```

where `<ERR_NAME>` is one of the existing `LEX_*`, `PARSE_*`, `STORAGE_*`, `EVAL_*` names from the native harnesses. The field set matches the native harness.

### Version / introspection

```
fn leap_version() -> u32
```
Returns a compile-time constant version identifier: `0x03_0b_00_00` in Phase 7 (major 3, minor 0b = Phase 3b feature level, patch 0, build 0). Useful as a sanity check after loading the .wasm.

## Non-goals (Phase 7)

- Persistence of any kind (all data lives in WASM linear memory; a page refresh loses it).
- Streaming results — every `leap_exec` serialises its full row set as JSON.
- Prepared statements / cursor APIs — Phase 7's SQL surface is one-shot per call.
- Direct column-level typed access — callers parse the JSON themselves.
- WASI / filesystem — Phase 7 targets `wasm32-unknown-unknown`. Later phases may add `wasm32-wasip1`.

## Build requirements (Rust target)

`src-rust/Cargo.toml`'s `[lib]` section MUST include `crate-type = ["cdylib", "rlib"]`. The `cdylib` is required for the wasm target to produce a `.wasm` file; the `rlib` preserves the existing native `cargo test` / `cargo run --bin …` flows.

The FFI module lives at `src-rust/src/wasm.rs` and is re-exported by `lib.rs` (`pub mod wasm;`).

## Test authority (Phase 7)

`tests/cross-build/phase7_smoke.mjs` is the executable specification. It's a Node.js ≥ 18 script that:

1. Instantiates the `.wasm` at `src-rust/target/wasm32-unknown-unknown/release/sqlite_leap.wasm` using the standard `WebAssembly.instantiate` API.
2. Confirms `leap_version()` returns the expected constant.
3. Creates a DB via `leap_db_new`.
4. Runs `CREATE TABLE`, `INSERT`, `SELECT` via `leap_exec` — asserting the JSON result matches the cross-build harness's expected rows.
5. Closes the DB via `leap_db_close` and verifies the handle is now invalid.

Exit 0 on all-green, 1 on first mismatch.
