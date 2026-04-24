---
name: io-backend/kqueue
kind: leaf
inherits:
  - /spec/durability.spec.md
  - /schema/io-submission.schema.json
  - /schema/io-completion.schema.json
emits:
  c: { path: src-c/io_backend/kqueue.c, headers: [src-c/io_backend/kqueue.h] }
  rust: { path: src-rust/src/io_backend/kqueue.rs }
---

# Part: io-backend/kqueue

Darwin / BSD kqueue-backed implementation. kqueue doesn't natively
cover disk I/O on macOS, so this sub-part falls back to synchronous
`pread` / `pwrite` / `fsync` paths behind the submission/completion
interface.

## Behavior

- Submissions → execute synchronously on the caller's thread.
- Completions → returned immediately; tokens remain for interface
  uniformity.
- fsync is `fsync(2)`; F_FULLFSYNC not used by default (macOS
  claims F_FULLFSYNC is slower; v2 defaults to fsync and documents
  the caveat for publication).

Semantic equivalence with the iouring backend is the bar: any test
that passes on Linux must pass on Darwin, modulo absolute timing.

## Phase pins

- **Phase 5** — async I/O backend (Darwin).
- **Phase 132** — kqueue backend (Darwin/BSD path).

## Regeneration envelope

- Target leaf size: 300–500 lines per target.
- Spec < 80 lines.
