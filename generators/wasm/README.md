# generators/wasm

WASM build target for sqlite-leap. This is the third of three builds
(C / Rust / WASM) and competes with `sql.js` / `sqlite-wasm` on benchmark
lane 6 (parse + SELECT in the browser).

## What's here

```
generators/wasm/
|-- README.md         # this file
|-- Cargo.toml        # thin wrapper crate: sqlite_leap_wasm
|-- build.sh          # one-shot: cargo build --target wasm32-unknown-unknown
|-- .cargo/
|   `-- config.toml   # neutralises src-rust/'s -C target-cpu=native
|-- src/
|   `-- lib.rs        # FFI pass-throughs + sqlite_leap_* convenience surface
`-- web/
    |-- index.html    # minimal demo page (SELECT 1; + smoke suite button)
    `-- app.js        # loader, TextEncoder/TextDecoder bridge, packed-u64 unwrap
```

The artifact lands in `src-wasm/sqlite_leap.wasm` at the repo root (gitignored
per CLAUDE.md).

## Design

This is **not** a fresh code generation step. The Rust engine in `src-rust/`
already exposes a complete C-ABI in its `wasm` module (see
`spec/wasm-ffi.spec.md`). This wrapper crate path-depends on `sqlite-leap`,
re-declares the `#[no_mangle]` FFI symbols (so they survive linker GC in the
downstream cdylib), and adds a convenience surface under the `sqlite_leap_*`
prefix matching the task spec.

**No `wasm-bindgen`, no `wasm-pack`, no `trunk`.** We target a plain
`wasm32-unknown-unknown` cdylib with raw C-ABI. JS callers use
`WebAssembly.instantiate` and the exported memory directly. This matches the
way `sql.js` and `sqlite-wasm` are embedded and keeps the toolchain minimal.

## FFI surface

All exports are `extern "C"` and use only `u32` / `u64` (pointers and lengths
in wasm32 linear memory are `u32`; 64-bit return values are packed
`(ptr << 32) | len`).

### Task-spec surface (`sqlite_leap_*`)

| Export                                   | Returns        | Notes |
|------------------------------------------|----------------|-------|
| `sqlite_leap_open(filename_ptr: u32)`    | handle (u32)   | Filename currently ignored. In-memory only. 0 = failure. |
| `sqlite_leap_exec(h, sql_ptr, sql_len)`  | packed u64     | High 32 = result ptr, low 32 = result len. JSON UTF-8. Caller frees. |
| `sqlite_leap_close(handle: u32)`         | void           | Idempotent on 0 / already-closed. |
| `sqlite_leap_alloc(len: u32)`            | ptr (u32)      | Allocate a linear-memory buffer for SQL input. |
| `sqlite_leap_free(ptr: u32, len: u32)`   | void           | `len` MUST match the original allocation. |
| `sqlite_leap_version()`                  | version (u32)  | Packed `major << 24 \| minor << 16 \| patch << 8 \| build`. |

### Engine-native surface (`leap_*`)

The parent crate's own FFI is also re-exported for parity with the Rust unit
test harness: `leap_version`, `leap_alloc`, `leap_free`, `leap_db_new`,
`leap_db_close`, `leap_exec`. Identical semantics to the `sqlite_leap_*`
variants; choose one naming convention per JS embedding.

### Result JSON shape

Identical to the cross-build harness (this is intentional — the same
`success_json` / `error_json` writers produce both the native harness output
and the wasm FFI output):

```json
// success
{"rows":[[1, "foo"], [2, "bar"]]}

// error
{"error":{"name":"LEX_UNEXPECTED_CHARACTER", "fields":{"pos": 3}}}
```

## Build

```sh
# Prereq (one time):
rustup target add wasm32-unknown-unknown

# Build:
./generators/wasm/build.sh

# Output:
ls -lh src-wasm/sqlite_leap.wasm
```

`PROFILE=dev ./generators/wasm/build.sh` for unoptimised, faster-iterating
builds.

### Why `.cargo/config.toml` in this directory

`src-rust/.cargo/config.toml` sets `rustflags = ["-C", "target-cpu=native"]`
which is invalid for wasm (there is no "native" wasm CPU). Cargo walks up from
the invocation dir to find configs, so placing a config here — which is on a
different path from `src-rust/` — shadows the native-CPU flag cleanly without
modifying `src-rust/`.

## Web harness

```sh
# From the repo root:
python3 -m http.server 8000

# Then open:
#   http://localhost:8000/generators/wasm/web/
```

The page auto-runs `SELECT 1;` and exposes a textarea for arbitrary SQL plus a
"run smoke suite" button that exercises CREATE TABLE / INSERT / SELECT /
aggregate paths.

## Gaps in the Rust engine's public API

These would benefit from a spec revision before polishing the WASM surface.
**Not** fixed in this scaffolding per task scope:

1. No `Database::open(path)` — only in-memory. The WASM target has no useful
   file system anyway, but a named-handle registry (sql.js style) would help
   reconnection patterns.
2. `leap_exec` always returns a full JSON buffer. A cursor-style
   `leap_prepare` / `leap_step` / `leap_finalize` API would avoid copying
   large result sets into a single wasm allocation.
3. No `leap_last_insert_rowid` / `leap_changes` accessors; JS callers that
   want those must parse the result JSON.
4. No `no_fs` feature flag on `sqlite-leap` — the crate pulls `std::fs`
   transitively; dead-strip handles it today, but an explicit flag would make
   the hermetic wasm build intent obvious.

## DO NOT CHEAT

Nothing here is ported from mainline SQLite, Turso, `sql.js`, `sqlite-wasm`,
`better-sqlite3`, or `rusqlite`. The wrapper only composes our own
spec-generated Rust engine.
