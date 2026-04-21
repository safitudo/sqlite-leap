# I/O backend — kqueue / Darwin + BSD — language-neutral spec (Phase 5c)

This spec defines the behavioural contract a Darwin or BSD backend MUST implement to satisfy the abstract I/O backend contract (`io-backend.spec.md`). The name "kqueue" is used for familiarity; the spec does NOT prescribe the use of kqueue specifically — it prescribes the behaviour that an implementation using kqueue, POSIX AIO, a worker thread pool, or any combination MUST exhibit.

Companion specs:
- `io-backend.spec.md` — abstract contract.
- `schema/io-submission.schema.json`, `schema/io-completion.schema.json` — record shapes.
- `pager-async.spec.md` — pager state machine.
- `io-backend-iouring.spec.md` — sibling Linux backend.

## Applicability

This backend is used on Darwin (macOS 13+) and FreeBSD 13+. It is REQUIRED for the macOS arm64 "zero warnings" Done criterion. It is NOT the benchmark-publication platform; Linux-with-io_uring is.

## Fundamental constraint

Darwin does not offer a first-class async file-I/O primitive equivalent to io_uring. The backend MUST nevertheless expose the same submission/completion queue abstraction as `io-backend.spec.md` demands. Implementations typically combine:

- A kernel event-notification primitive (kqueue) for readiness-style events.
- Synchronous file-I/O syscalls (`pread`, `pwrite`, `fsync` — with Darwin-specific `F_FULLFSYNC`, `rename`, `unlink`, `open`, `close`) issued from one or more worker threads.
- A bounded worker-thread pool that consumes submissions and emits completions.

**The spec does NOT prescribe which combination.** A generator MAY use POSIX AIO + kqueue on Darwin; another MAY use a thread pool + a condvar-backed completion queue; another MAY use libdispatch. What the spec pins is the observable contract. All of these are legal iff the observable behaviour matches.

## Observable contract

### Submission queue

Capacity: `SQ_CAPACITY = 64`. Smaller than io_uring's 128 because the underlying implementation is thread-pool-bounded and deeper queues produce worse tail latency on Darwin. The pager's backpressure policy (see `pager-async.spec.md` § "Backpressure") adapts automatically since SQ_CAPACITY is a backend-reported value.

### Completion queue

Capacity: ≥ `SQ_CAPACITY`. Completions are observable in the same FIFO-per-handle order as on io_uring.

### Submission mapping

| Submission `op`   | Required behaviour                                                                                  |
|-------------------|-----------------------------------------------------------------------------------------------------|
| `open_read`       | Open read-only; emit completion with a handle id. MAY block the submission (run synchronously). |
| `open_write`      | Open for write; create / truncate per flags; emit completion with a handle id. |
| `read`            | Read `length` bytes at `offset` into `payload_buffer_ref`. Partial reads are retried internally. |
| `write`           | Write `length` bytes. Partial writes retried. |
| `fsync`           | Durability sync on the handle. On Darwin, the backend MUST request platter-level durability (the Darwin-specific "full fsync" facility), not buffer-cache-only durability. The `datasync` hint on the submission is IGNORED on Darwin — full fsync always. On FreeBSD, a normal fsync satisfies durability. |
| `fsync_dir`       | Durability sync on the parent directory. On APFS, this MAY be a no-op; on HFS+, it MUST be issued. The backend probes the filesystem type at `open_read` on the parent and caches the answer. |
| `close`           | Release the handle. Pending operations on this handle MUST drain before the close-completion is emitted. |
| `rename`          | Atomic rename. Darwin's `rename` is sufficient (no async-rename primitive exists on Darwin; the backend issues it synchronously from a worker). |
| `unlink`          | Remove the file. Idempotent on missing-file. |
| `cancel`          | Instruct the backend to abort the submission whose `user_data == cancel_target`. Because the worker may already be mid-syscall, cancel is best-effort: the target submission's completion may arrive as `cancelled` (if cancellation won the race) or as `ok`/`error` (if the syscall already committed). The cancel op's own completion is always emitted. |

### Ordering guarantees

Identical to the io_uring backend's observable contract:

- **Same-handle ordering:** preserved. If a generator uses a multi-worker thread pool, it MUST route same-handle submissions to the same worker (or otherwise serialise them) to keep FIFO order. Cross-worker reordering within a handle is forbidden.
- **Cross-handle ordering:** independent; pager-sequenced.
- **Commit barrier:** the commit-sealing fsync MUST be ordered-after all prior writes to the same handle, and its completion MUST be durable before the commit is observable.

### Buffer lifecycle

Same contract as `io-backend-iouring.spec.md` § "Buffer lifecycle": the pager keeps the referenced buffer live from submission to matching completion.

### Error mapping

| Native error       | Completion outcome | `error_condition`                          |
|--------------------|--------------------|--------------------------------------------|
| expected length transferred | ok        | —                                          |
| short transfer     | error              | `IO_BACKEND_SHORT_READ` / `IO_BACKEND_SHORT_WRITE` |
| "interrupted" (EINTR) | retried by backend; if persistent: error | `IO_BACKEND_EINTR`              |
| "no such file" (ENOENT)    | error      | `IO_BACKEND_ENOENT`                        |
| "permission denied" (EACCES) | error    | `IO_BACKEND_EACCES`                        |
| "already exists" (EEXIST)  | error      | `IO_BACKEND_EEXIST`                        |
| "invalid argument" (EINVAL)| error      | `IO_BACKEND_EINVAL`                        |
| "no space left" (ENOSPC)   | error      | `IO_BACKEND_ENOSPC`                        |
| "I/O error" (EIO)          | error      | `IO_BACKEND_EIO`                           |
| thread-pool saturated, no worker available before submission-queue deadline | error | `IO_BACKEND_FULL_QUEUE`      |
| full-fsync failure on Darwin | error    | `IO_BACKEND_EIO` with `reason = "F_FULLFSYNC failed"` |
| worker thread panic / pool crash | error| `IO_BACKEND_BACKEND_CRASH`                 |

### Concurrency

The pager is single-writer; readers may submit concurrently. The backend's internal concurrency (worker count) is a performance knob and invisible to the pager. Default worker count: 4 on Darwin (matches typical core count for dev machines); tunable via a build flag.

### Initialization and teardown

- **Init.** First `open_database` on this backend starts the worker pool and event primitive. Subsequent sessions share the pool.
- **Teardown.** Process exit signals workers to drain and join. `close_database` releases per-session handles; the pool persists.
- **Handle lifecycle during close.** When the pager issues a `close` submission, the worker that executes it MUST emit the close-completion only after all prior submissions on that handle have completed (or been cancelled). The pager's close grace window governs how long it waits for this drain.

## Durability: the F_FULLFSYNC requirement (Darwin only)

Darwin's bare fsync flushes the buffer cache but does NOT force the disk to flush its write cache to platter. For crash-durability guarantees equivalent to Linux, Darwin requires the F_FULLFSYNC fcntl. The kqueue backend MUST use F_FULLFSYNC on every `fsync` submission on Darwin, regardless of the `datasync` hint. Rationale: correctness trumps throughput on Darwin, which is not a benchmark-publication platform. Generators MAY expose a developer-only escape hatch (`LEAP_FSYNC_NOFULLSYNC=1`) that downgrades to bare fsync for fast local iteration; this escape hatch MUST NOT be compiled into release builds.

On FreeBSD, bare fsync suffices.

## Performance expectations

This backend is expected to be **slower than io_uring** under write-heavy workloads, because:
- Full fsync on Darwin is inherently slower than Linux fsync.
- Thread-pool dispatch adds fixed-cost overhead per op.
- No kernel batched-submit primitive; each op is a syscall.

This is acceptable. The Done criterion for Darwin is "clean build, zero warnings, correctness-suite passes", not "matches io_uring throughput". The L4 benchmark lane publishes Linux numbers only.

## Non-goals (Phase 5c)

- **Matching io_uring throughput.** Darwin's async primitives are fundamentally weaker.
- **Custom disk I/O tuning** (O_DIRECT, raw device access). Out of scope.
- **FreeBSD aio integration.** Deferred; v1 uses the thread-pool approach uniformly across Darwin and FreeBSD.
- **Windows IOCP.** Not on the sqlite-leap roadmap.

## Test authority

- **Behavioural equivalence:** every `tests/cross-build/phase*.json` fixture passing on the sync backend MUST pass byte-identically with the kqueue backend active.
- **Darwin-specific gate:** `tests/roundtrip_kqueue_correctness.py` (macOS-only) drives the full fixture set with `LEAP_IO_BACKEND=kqueue` forced; asserts byte-identity with sync-backend output.
- **Full-fsync verification:** a harness-level test verifies that `fsync` submissions on Darwin issue F_FULLFSYNC (observable via a syscall trace or an injected syscall-wrapper in debug builds). Part of the macOS CI gate.

## Cross-build equivalence

Both C and Rust Darwin builds MUST produce identical observable behaviour. Byte-identity of on-disk output is required (WAL framing is deterministic; only timing differs across backends).

## Fall-through

When this backend probes unavailable (which should not occur on supported Darwin/BSD kernel versions), the selection layer falls back to the sync backend. Unlike the io_uring fallback, the kqueue backend's failure mode is rare enough that it is treated as a configuration bug rather than a routine path.
