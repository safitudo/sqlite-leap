---
name: lib-api
kind: inner
inherits:
  - /spec/memory-discipline.spec.md
  - /parts/parser/master.md
  - /parts/compiler/master.md
  - /parts/vdbe/master.md
  - /parts/storage/master.md
emits:
  c:      { path: src-c/lib_api/mod.h }
  rust:   { path: src-rust/lib_api/mod.rs }
  zig:    { path: src-zig/lib_api/mod.zig }
  go:     { path: src-go/lib_api/mod.go }
  python: { path: src-python/lib_api/__init__.py }
---

# Part: lib-api

The user-facing library API. Wraps the parser → compiler → VDBE
pipeline behind a stable surface that resembles the `sqlite3_*`
C ABI's prepare/bind/step/reset/finalize lifecycle without
prescribing a specific ABI. Sub-parts:

- `prepared-statement` — `prepare(sql) -> PreparedStatement`,
  `bind(stmt, slot, value)`, `step(stmt) -> StepResult`,
  `reset(stmt)`. The prepare-once-execute-many shape that lifts
  Lane 4 (INSERT throughput) from sync-only to ≥ Turso. Bench-
  validated on Rust: 98k → 2.58M ips, 1.94× faster than mainline.

Future sub-parts (deferred): one-shot `exec(sql, params) -> rows`
convenience wrapper; a transaction surface; a connection pool
wrapper. None block the v1 stunt.

## Public interface

The lib-api is the surface a follow-on FFI / ABI / language-binding
layer will wrap. It deliberately exposes no opaque pointers and no
target-specific lifetimes in its master-spec form; per-target
mappings render the canonical idiom (Rust ownership, C handles,
Python class).
