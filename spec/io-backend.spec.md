# I/O backend — async / platform dispatch — language-neutral spec

## Scope decomposition

Async I/O is a multi-phase feature. The current storage stack (Phases 3a/3b/3d/4a) performs all disk I/O synchronously via the platform's blocking `read`/`write`/`fsync`/`rename` primitives. This is adequate for correctness but leaves the L4 INSERT-throughput benchmark lane behind Turso, which uses `io_uring` on Linux. The spec is therefore decomposed:

- **Phase 5a — I/O backend abstraction.** Define a language-neutral I/O contract (a set of named operations + sequencing rules) such that storage-layer code is written against the abstraction, and each target can plug in a concrete backend (sync / io_uring / kqueue) without storage-layer edits. No behavioural change; this is purely an interface-shaping phase.
- **Phase 5b — io_uring backend (Linux).** Implement the async backend on Linux kernels ≥ 5.13 (required SQE opcodes: `IORING_OP_READ`, `IORING_OP_WRITE`, `IORING_OP_FSYNC`, `IORING_OP_RENAMEAT`, `IORING_OP_UNLINKAT`, `IORING_OP_OPENAT`, `IORING_OP_CLOSE`). Batch-submit per commit. Gate the L4 benchmark on this phase.
- **Phase 5c — kqueue backend (macOS / BSD).** Implement the async backend on Darwin 22+ (kqueue + AIO). Not required for L4 — macOS is a dev-loop platform, not a benchmark-publication platform — but required to meet the "Done" criterion "zero warnings on macOS arm64".
- **Phase 5d — fall-back sync backend.** For platforms without async support (older Linux, Windows if we ever add it, WASM), retain the Phase 3a synchronous path as a first-class backend selectable by compile-time or runtime configuration. Required for WASM (no io_uring in the browser sandbox).

Phase 5a is the minimum shippable sub-phase. It does NOT, on its own, change any benchmark numbers — but it unblocks 5b, which does. Phases 5b/5c/5d can land in any order after 5a.

## Phase 5a — I/O backend abstraction

### Goal

Define every disk I/O operation the storage layer performs as a named abstract operation. Concrete backends implement those operations however is idiomatic for the platform. The storage layer never names a syscall directly.

### Operations

Each operation is described by (inputs, outputs, error conditions, ordering guarantees). All operations are **logically** synchronous from the storage layer's point of view — the storage layer issues an operation and waits for its completion — but the BACKEND is free to batch, reorder (within the bounds of the ordering rules below), or perform the underlying syscalls asynchronously.

#### `io_open_read(path) -> handle`

Open an existing file for reading. On failure, raise `STORAGE_FILE_IO { operation: "open", path, reason }`.

#### `io_open_write(path, create: bool, truncate: bool) -> handle`

Open (or create) a file for writing. `create=true` creates the file if absent (exclusive-create semantics not required). `truncate=true` truncates to zero bytes if the file exists. On failure: `STORAGE_FILE_IO { operation: "open", path, reason }`.

#### `io_read(handle, offset, len) -> bytes`

Read `len` bytes starting at `offset`. Short reads must raise `STORAGE_FILE_IO { operation: "read", ... }`; the backend is responsible for looping on partial reads. On I/O error: `STORAGE_FILE_IO { operation: "read", path, reason }`.

#### `io_write(handle, offset, bytes) -> ()`

Write `bytes` starting at `offset`. Short writes must raise `STORAGE_FILE_IO { operation: "write", ... }`; the backend is responsible for looping on partial writes. On I/O error: `STORAGE_FILE_IO { operation: "write", path, reason }`.

#### `io_fsync(handle) -> ()`

Force all pending writes on this handle to durable storage. On I/O error: `STORAGE_FILE_IO { operation: "sync", path, reason }`. On platforms where `fdatasync` is sufficient (metadata unchanged), backends MAY use it instead. On macOS, `F_FULLFSYNC` is REQUIRED for flush-to-platter durability — backends MUST use it, not bare `fsync`, on Darwin.

#### `io_close(handle) -> ()`

Release the handle. Any pending operations on this handle must complete (or fail) before close returns. On I/O error during flush: `STORAGE_FILE_IO { operation: "close", path, reason }`.

#### `io_rename(old_path, new_path) -> ()`

Atomic rename. Semantics must match POSIX `rename(2)`: on the same filesystem, readers see either the old or the new file, never a mixture. On I/O error: `STORAGE_FILE_IO { operation: "rename", path: new_path, reason }`.

#### `io_unlink(path) -> ()`

Remove a file. If the file does not exist, MUST succeed silently (idempotent). On other I/O error: `STORAGE_FILE_IO { operation: "unlink", path, reason }`.

#### `io_fsync_dir(dir_path) -> ()`

Force the directory entry to durable storage. Required after `io_rename` on some filesystems (ext4 without `dirsync`). On macOS APFS, backends MAY treat this as a no-op. On I/O error: `STORAGE_FILE_IO { operation: "sync", path: dir_path, reason }`.

#### `io_exists(path) -> bool`

Test whether a file exists at `path`. No error raised; returns false on any "does not exist"-equivalent error. Other errors (permission denied, I/O) propagate as `STORAGE_FILE_IO { operation: "stat", path, reason }`.

### Ordering rules (normative)

From the storage layer's point of view, operations on the same handle are sequentially ordered: a `io_read` issued after a `io_write` to an overlapping range MUST observe the written bytes. A backend that reorders operations internally MUST preserve this guarantee.

Operations on different handles have no ordering guarantee unless the storage layer explicitly sequences them (e.g., issues `io_fsync` + awaits before starting the next operation).

`io_fsync` is a memory barrier: all prior writes on the same handle must be durable before `io_fsync` returns; subsequent writes are not affected.

`io_rename` MUST be ordered after any `io_fsync` on the source path (the commit protocol in `durability.spec.md` relies on this).

### Batching

A backend MAY batch multiple operations into a single syscall (e.g., io_uring submission queue) as long as the ordering rules above are preserved. The storage layer MUST NOT rely on any specific batch boundary; conversely, the backend MUST NOT delay a `io_fsync` or `io_rename` past its logical completion point.

### Backend selection

At compile time, each language target selects one or more concrete backends. The storage layer knows nothing about which backend is active; it only invokes the operations above. Selection rules:

- **C build**: sync backend mandatory (Phase 5d). io_uring backend (Phase 5b) enabled when `__linux__` and kernel features advertised at build time. kqueue (Phase 5c) enabled on `__APPLE__` / BSD. Selection at runtime by probing — first available wins; sync is always the last fallback.
- **Rust build**: sync backend always present. `cfg(target_os = "linux")` compiles in the io_uring backend as the default. `cfg(target_os = "macos")` compiles in kqueue.
- **WASM build**: sync backend only. io_uring / kqueue are unavailable in `wasm32-unknown-unknown`. Storage layer compiles unchanged; the sync backend plugs in.

### Error model

Every backend MUST raise the errors enumerated above with the exact condition names and field structure. Downstream code (storage layer, VDBE) catches by condition name, never by inspecting platform-specific error codes. Platform-specific detail (errno, `std::io::Error`) MAY be stashed in the `reason` field as a human-readable string for debugging.

### Non-goals (Phase 5a)

- Any behavioural change. All existing fixtures MUST continue to pass byte-identically.
- Any new VDBE opcodes. The storage↔I/O boundary is below VDBE.
- Concurrent readers. Phase 5a is single-reader, single-writer, same as Phase 4a. Concurrency belongs to Phases 4b / 4c.

## Phase 5 extension — async submission/completion model

Phase 5a described the I/O interface as "logically synchronous from the storage layer's point of view". Phase 5b (io_uring) and Phase 5c (kqueue/thread-pool) extend this: the storage layer is rebuilt around an **async submission/completion** model where issuing a submission and observing its completion are distinct events in time. This section defines the async interface layer that sits ON TOP of the ops above; it does not replace them. Targets that can support async I/O (C, Rust native) SHOULD use this layer to unlock the L4 throughput lane; WASM continues to use the sync interface only.

### Submission / completion records

Record shapes are defined in:
- `schema/io-submission.schema.json` — submission records (op, user_data, epoch, op-specific fields).
- `schema/io-completion.schema.json` — completion records (outcome, error_condition, result_bytes).

The records are **language-neutral contracts**: every field is either a small integer, a bounded string, or an enumerated tag. Generators bind them to native in-memory shapes.

### Enumerated backend error conditions

These are the conditions a completion record MAY carry. Each maps 1-to-1 with the storage layer's `STORAGE_*` surface (see `pager-async.spec.md` § "New error conditions").

- `IO_BACKEND_SHORT_READ` — fewer than `length` bytes could be read; the backend exhausted retries.
- `IO_BACKEND_SHORT_WRITE` — fewer than `length` bytes could be written.
- `IO_BACKEND_CANCELLED` — the op was aborted by a `cancel` submission or by bulk cancellation on epoch bump.
- `IO_BACKEND_EIO` — generic I/O error from the platform.
- `IO_BACKEND_ENOSPC` — out of disk space.
- `IO_BACKEND_ENOENT` — path does not exist (only raised for ops where this is an error — `unlink` does NOT raise it).
- `IO_BACKEND_EACCES` — permission denied.
- `IO_BACKEND_EEXIST` — exclusive-create requested and path exists.
- `IO_BACKEND_EINVAL` — backend rejected the submission shape (malformed offset, unaligned length where alignment is required, etc.).
- `IO_BACKEND_EINTR` — interrupted signal; backend's internal retry policy was exhausted.
- `IO_BACKEND_FULL_QUEUE` — the submission queue was at capacity and the submission could not be enqueued within the backend's internal deadline. Handled by the pager via backpressure (see `pager-async.spec.md` § "Backpressure").
- `IO_BACKEND_UNSUPPORTED` — the op or a required feature is unsupported by this backend at runtime.
- `IO_BACKEND_BACKEND_CRASH` — an unrecoverable internal failure; the session is fatal.
- `IO_BACKEND_TIMEOUT` — an operation exceeded a backend-internal deadline (rare; primarily for cancel races).

### Ordering guarantees restated for async

The ordering rules from § "Ordering rules (normative)" apply to the async interface with these refinements:

- Same-handle ordering is preserved across submissions iff the pager either (a) sets `link_prior = true` on the dependent submission, or (b) waits for the prior completion before submitting the next. Both are legal; platform backends MAY strengthen (ignore `link_prior` and always preserve order), never weaken.
- Cross-handle ordering requires explicit pager sequencing (a completion observed before the next submission is issued).
- The commit barrier — fsync-after-writes — is a MUST, enforced by the pager via either link or await.

### Backend selection (async-aware)

Extends § "Backend selection":

- On init, the selection layer probes in preference order: platform async backend first (io_uring on Linux, kqueue on Darwin/BSD), sync backend as fallback. First to report "ready" wins.
- Once selected, the backend is sticky for the session. Mid-session switching is forbidden (see `io-backend-iouring.spec.md` § "Fallback on runtime feature failure").

### Non-goals (Phase 5 async extension)

- Zero-copy fixed buffers. Deferred.
- Kernel poll threads. Deferred.
- Direct I/O / O_DIRECT. Deferred.
- Runtime PRAGMA for backend selection. Deferred.

See `pager-async.spec.md` for the state machine that consumes this interface, and `io-backend-iouring.spec.md` / `io-backend-kqueue.spec.md` for platform specifics.

## Phase 5b — io_uring backend (Linux)

### Goal

Implement the I/O operations above via `io_uring` submission/completion queues on Linux ≥ 5.13. Target: match or beat Turso's INSERT throughput on the L4 benchmark.

### Kernel requirements

- **Linux ≥ 5.13** (stable io_uring with SQPOLL, MSG_RING, and the opcodes listed below).
- **Opcodes**: `IORING_OP_READ`, `IORING_OP_WRITE`, `IORING_OP_FSYNC`, `IORING_OP_RENAMEAT`, `IORING_OP_UNLINKAT`, `IORING_OP_OPENAT`, `IORING_OP_CLOSE`.
- **Feature probes**: at first backend init, submit a no-op SQE and require completion. If the kernel returns `ENOSYS` or the expected opcodes are missing, fall back to the sync backend transparently (log once at WARN level).

### Ring configuration

- Ring size: **128 entries** (both SQ and CQ). Rationale: a typical commit batch is ≤ ~32 I/Os (one WAL append = one write per page + one fsync); 128 gives headroom without pinning excessive memory.
- `IORING_SETUP_SINGLE_ISSUER`: set when available (kernel ≥ 6.0). Asserts the storage layer is single-threaded at the ring boundary.
- `IORING_SETUP_COOP_TASKRUN`: set when available. Reduces context switches on completion delivery.
- No `IORING_SETUP_SQPOLL`. Rationale: SQPOLL requires CAP_SYS_NICE or a tuned kernel; sqlite-leap targets userland defaults. A user who wants SQPOLL can patch the flag.

### Submission discipline

- **Same-handle ordering via `IOSQE_IO_LINK`.** Two operations on the same handle that have a storage-layer ordering dependency MUST be linked so the kernel preserves order. Example: `write(page 0)` → `write(page 1)` → `fsync` — all three linked, so completion of the chain = durability of both pages.
- **Batching**: the storage layer may enqueue many SQEs before calling `submit` + `wait_for_completion`. The backend MUST NOT submit partial batches on a single operation boundary; submission happens at commit points (end-of-transaction, close, explicit `io_fsync`).
- **Completion draining**: after `submit`, the backend drains ALL CQEs before returning to the caller. A CQE with `result < 0` is mapped to the appropriate `STORAGE_FILE_IO` error by operation.

### Specific mappings

| Operation | SQE opcode | Fixed buffers? | Link prior? |
|---|---|---|---|
| `io_read(h, off, len)` | `IORING_OP_READ` | No (v1); fixed-buffer optimization deferred | only if prior write to same handle |
| `io_write(h, off, bytes)` | `IORING_OP_WRITE` | No | only if prior write to same handle |
| `io_fsync(h)` | `IORING_OP_FSYNC` with `IORING_FSYNC_DATASYNC` flag iff metadata unchanged | — | MUST link after prior writes |
| `io_close(h)` | `IORING_OP_CLOSE` | — | MUST link after prior ops on handle |
| `io_rename(o, n)` | `IORING_OP_RENAMEAT` | — | MUST link after the fsync of `o` |
| `io_unlink(p)` | `IORING_OP_UNLINKAT` | — | — |
| `io_open_read(p)` | `IORING_OP_OPENAT` with `O_RDONLY` | — | — |
| `io_open_write(p, c, t)` | `IORING_OP_OPENAT` with `O_WRONLY [\| O_CREAT] [\| O_TRUNC]` | — | — |
| `io_fsync_dir(d)` | `IORING_OP_FSYNC` on dir fd (open-then-fsync-then-close, all linked) | — | MUST link after rename |

### Error mapping

- `-EAGAIN` / `-EBUSY` on a ring-submit: retry up to 3 times with brief yield; on persistent failure, raise `STORAGE_FILE_IO { operation: "submit", reason: "ring full after 3 retries" }`.
- `-ENOSYS` on any op: treat as a backend-level failure; do NOT fall back mid-session (the ring is already in use; switching backends mid-flight is unsafe). Raise `STORAGE_FILE_IO { operation: <op>, reason: "io_uring opcode unsupported" }`.
- Other negative results: map the errno to a human-readable reason string; raise `STORAGE_FILE_IO`.

### Non-goals (Phase 5b)

- `IORING_REGISTER_BUFFERS` / fixed-buffer optimization. Profile-gated; attempt only if L4 numbers fall short.
- `IORING_SETUP_SQPOLL`. User-tuning opt-in; not default.
- Multishot reads. Not needed for the storage workload.

## Phase 5c — kqueue backend (macOS / BSD)

### Goal

Implement the I/O operations via `kqueue` + POSIX AIO on Darwin 22+ / FreeBSD 13+. Lower priority than 5b because macOS is not a published benchmark platform — but REQUIRED for clean builds and for meeting the macOS arm64 "Done" criterion.

### Mechanism

Darwin's `kqueue` is an event-notification system; the actual async I/O is issued via `aio_read` / `aio_write` (from `<aio.h>`) and completion is delivered as `EVFILT_AIO` events. Fsync is issued via `aio_fsync(O_SYNC, &aiocb)`. There is no async `rename` / `unlink` / `openat` on Darwin; those remain synchronous (same as the sync backend). This is acceptable because they are not hot-path operations.

### F_FULLFSYNC requirement

On Darwin, `fsync(2)` flushes the buffer cache but does NOT force the disk to flush its own cache to platter. For crash-durability guarantees equivalent to Linux, Darwin requires `fcntl(fd, F_FULLFSYNC)`. The kqueue backend MUST use `F_FULLFSYNC` on every `io_fsync` call. Cost: higher than `fsync`, but correctness trumps throughput on macOS (we do not bench-publish on Darwin).

### Non-goals (Phase 5c)

- Matching io_uring throughput on Darwin. Darwin's kernel async primitives are fundamentally weaker than io_uring. Do not optimise past "passes correctness suite with reasonable overhead".
- Windows IOCP. Out of scope entirely.

## Phase 5d — sync fallback backend

### Goal

Retain the Phase 3a synchronous backend as a first-class plug for the abstraction defined in 5a. Required for: WASM builds (no async primitives), feature-probe fallback on older Linux, developer-local builds that want the simplest path.

### Mechanism

Direct syscall mapping:

| Operation | Syscall |
|---|---|
| `io_open_read` | `open(2)` with `O_RDONLY` |
| `io_open_write` | `open(2)` with `O_WRONLY [\| O_CREAT] [\| O_TRUNC]` |
| `io_read` | `pread(2)` in a loop until `len` bytes consumed |
| `io_write` | `pwrite(2)` in a loop until `len` bytes written |
| `io_fsync` | `fsync(2)` (Linux) / `fcntl(F_FULLFSYNC)` (Darwin) |
| `io_close` | `close(2)` |
| `io_rename` | `rename(2)` |
| `io_unlink` | `unlink(2)` (silent on `ENOENT`) |
| `io_fsync_dir` | `open` dir → `fsync` → `close` on Linux; no-op on Darwin |
| `io_exists` | `stat(2)` / `access(2)` |

All error mapping identical to Phase 5a's error model.

### WASM specifics

In `wasm32-unknown-unknown`, the host environment provides the I/O primitives via imported functions (see `wasm-ffi.spec.md`). The sync backend is the only option; the host side of the FFI handles the actual storage. Operations map 1:1 to imported FFI calls.

## Test authority

Phase 5a is a structural refactor with no behavioural change. Its gate is that ALL existing fixtures (phase3a, phase3b, phase3d, phase4a, phase6-series, phase9-series) continue to pass byte-identically after the abstraction is introduced. No new fixture file is required for 5a — existing fixtures cover it transitively.

Phase 5b / 5c require platform-gated fixtures:

- `tests/roundtrip_io_uring_insert_bench.py` — Linux-only; drives INSERT throughput via the io_uring backend; asserts a minimum ops/sec ceiling that gates L4 benchmark publication.
- `tests/roundtrip_kqueue_correctness.py` — macOS-only; same fixture set as phase3d, but with `LEAP_IO_BACKEND=kqueue` forced. Asserts byte-identical output to the sync backend.

Phase 5d is covered by the existing sync-backend fixture corpus.

## Open questions (NOT yet pinned)

1. **Direct I/O.** Should the io_uring backend use `O_DIRECT` to bypass the kernel page cache? This reduces memory pressure but adds alignment constraints. Defer to profile-driven decision during 5b implementation.
2. **Polled I/O.** `IORING_SETUP_IOPOLL` can reduce completion latency on NVMe. Same deferral — profile first.
3. **Runtime backend switching.** Currently the backend is locked at compile time / first-init. A runtime `PRAGMA io_backend` would help benchmarking but adds test-matrix surface. Deferred.

These are documented here so they do NOT surface as spec drift during implementation — they are known gaps, deliberately left unfilled until data guides the decision.
