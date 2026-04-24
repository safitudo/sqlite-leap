---
name: io-backend/iouring
kind: leaf
inherits:
  - /spec/durability.spec.md
  - /schema/io-submission.schema.json
  - /schema/io-completion.schema.json
emits:
  c: { path: src-c/io_backend/iouring.c, headers: [src-c/io_backend/iouring.h] }
  rust: { path: src-rust/src/io_backend/iouring.rs }
---

# Part: io-backend/iouring

Linux io_uring implementation of the io-backend interface.

## Supported ops

`IORING_OP_READ`, `IORING_OP_WRITE`, `IORING_OP_FSYNC`,
`IORING_OP_OPENAT`, `IORING_OP_CLOSE`.

## Submission / completion

- SQE ring sized at 256 entries (configurable).
- Submissions packed into SQ; `io_uring_enter` flushes.
- Completions polled from CQ; outcomes delivered via token
  correlation to waiting callers.

## Durability guarantee

`IORING_OP_FSYNC` does NOT return until the kernel reports durable.
Paired with a preceding `IORING_OP_WRITE`, this is the LEAP
"durable write" primitive.

## Phase pins

- **Phase 5** — async I/O backend (Linux).
- **Phase 135** — io_uring backend (Linux path).

## Regeneration envelope

- Target leaf size: 500–800 lines per target.
- Spec < 100 lines.
