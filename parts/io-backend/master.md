---
name: io-backend
kind: inner
inherits:
  - /spec/memory-discipline.spec.md
  - /spec/durability.spec.md
  - /schema/io-submission.schema.json
  - /schema/io-completion.schema.json
emits:
  c:
    path: src-c/io_backend/mod.h
  rust:
    path: src-rust/src/io_backend/mod.rs
---

# Part: io-backend

Async I/O abstraction. Absorbs v1's `io-backend.spec.md`,
`io-backend-iouring.spec.md`, `io-backend-kqueue.spec.md`.

## Public interface

Submission / completion queues over four operations:

- `read(fd, buf, len, offset)` — pread-equivalent.
- `write(fd, buf, len, offset)` — pwrite-equivalent.
- `fsync(fd)` / `fdatasync(fd)` — durability barrier.
- `openat(path, flags)` / `close(fd)` — lifecycle.

Submission yields a token; completion is polled on the token. The
storage layer is synchronous-consumer-of-async-primitive: each
top-level storage call issues submissions, waits for completions,
then returns. True async-all-the-way-up is out of scope for v2.

## Sub-part map

- `parts/iouring/` — Linux. io_uring primitives. SQE packing,
  completion reaping.
- `parts/kqueue/` — Darwin/BSD. kqueue primitives. Falls back to
  synchronous `pread`/`pwrite` when kqueue doesn't naturally cover
  the op (it doesn't cover disk I/O on macOS 14+; use
  `aio_read`/`aio_write` or GCD). Behavior must be semantically
  equivalent.

## Target selection

The backend is chosen at compile time from the target platform:

- Linux → `iouring`
- Darwin/BSD → `kqueue`
- Other (WASM, Windows) → not supported in v2; storage falls back
  to synchronous I/O via a pass-through compatibility shim.

## Cross-sub-part invariants

### Completion ordering

Completions may arrive out of order relative to submission. The
caller correlates via tokens. Storage serializes before it returns
to the compiler's callers, so cross-operation ordering is never a
compiler concern.

### Durability

`fsync` does not return until the kernel reports durable. A
completed `write` + a completed `fsync` on its fd is the LEAP
definition of "durable write." See `/spec/durability.spec.md`.

### Error reporting

I/O errors surface as `IO_ERROR` with `{op, errno, path_if_known}`.
Sub-parts translate platform errors into this neutral shape.

## Composition

The parent emits a facade that selects the compile-time backend and
re-exports its surface.
