# I/O backend — io_uring (Linux) — language-neutral spec (Phase 5b)

This spec defines the behavioural contract a Linux backend based on io_uring MUST implement to satisfy the abstract I/O backend contract (`io-backend.spec.md`). It describes observable behaviour — not kernel APIs or language bindings. Generators (C, Rust) map the behaviour to their idiomatic binding.

Companion specs:
- `io-backend.spec.md` — abstract contract.
- `schema/io-submission.schema.json`, `schema/io-completion.schema.json` — record shapes.
- `pager-async.spec.md` — pager state machine that drives this backend.
- `io-backend-kqueue.spec.md` — sibling Darwin/BSD backend.

## Applicability

This backend is used exclusively on Linux kernels supporting the feature set described below. On other platforms (Darwin, WASM, older Linux), a different backend is selected at build-or-runtime per `io-backend.spec.md` § "Backend selection".

## Kernel feature requirements

The backend probes the following features at first initialization. Any missing feature causes the backend to REPORT itself unavailable; higher-level selection falls back to the sync backend (see `io-backend.spec.md` § "Phase 5d").

1. **Core ring setup.** The kernel provides a submission queue + completion queue pair with user-space memory-mapping.
2. **Ring opcodes.** The following submission opcodes MUST be available: one-shot read at offset, one-shot write at offset, file-data sync (with optional data-only flag), file-handle open-at relative to a directory descriptor, file-handle close, atomic rename-at, unlink-at, and submission-cancel-by-user-data.
3. **No-op probe.** At init, the backend submits a no-op and requires its completion before declaring readiness.
4. **Kernel version floor.** Kernel ≥ 5.13. Earlier kernels lack stable semantics for the cancel-by-user-data primitive.

If any probe fails, the backend raises `IO_BACKEND_UNSUPPORTED` to the selection layer.

## Ring configuration (observable contract)

Generators implement rings with the following size and flags:

- **Submission-queue capacity:** 128 entries. Rationale: a typical commit batches ≤ ~32 I/Os (dirty pages + fsync); 128 gives headroom. This is the `SQ_CAPACITY` value the pager assumes for backpressure (see `pager-async.spec.md` § "Backpressure").
- **Completion-queue capacity:** ≥ 128 entries (matching or exceeding SQ).
- **Single-issuer mode:** when the kernel supports it (≥ 6.0), enable it. This asserts single-threaded ring access, which matches the pager's single-writer model.
- **Cooperative task-run:** when supported, enable. Reduces context switches on completion delivery. Correctness-neutral.
- **No kernel-side poll thread.** The pager does NOT opt into a kernel poll thread. This choice favours wide deployment (no special capabilities required) over tail-latency reduction; a userland build flag MAY flip the default for benchmarking.

These are target defaults. A runtime override (environment variable, build flag) is permitted but MUST NOT change observable semantics — only performance characteristics.

## Submission mapping

Every `op` kind in `schema/io-submission.schema.json` maps to an observable backend behaviour as follows. Generators use the opcode appropriate to their native binding; this table describes the effect, not the specific symbol.

| Submission `op`   | Backend behaviour                                                                                          |
|-------------------|------------------------------------------------------------------------------------------------------------|
| `open_read`       | Open the path read-only, associate the returned file descriptor with a new opaque handle, emit completion with `result_bytes = handle_id`. |
| `open_write`      | Open the path writable; create if `create == true`; truncate if `truncate == true`. Emit completion with handle id. |
| `read`            | Read exactly `length` bytes at `offset` into `payload_buffer_ref`. Partial reads are retried by the backend until either full length is satisfied (emit success) or no further progress is possible (emit `IO_BACKEND_SHORT_READ`). |
| `write`           | Write `length` bytes from `payload_buffer_ref` at `offset`. Partial-write handling same as read. |
| `fsync`           | Data-and-metadata durability on the handle. If submission has `datasync = true`, MAY issue data-only durability. |
| `fsync_dir`       | Open the parent directory read-only, durability-sync it, close. All three linked so the completion observed reflects the end-of-chain. |
| `close`           | Release the handle. Any completions already in the CQ for this handle are delivered first. |
| `rename`          | Atomic rename from `path` to `new_path`. |
| `unlink`          | Remove `path`. Idempotent: a "does not exist" native error produces `outcome = ok`, not an error. |
| `cancel`          | Instruct the backend to abort the submission whose `user_data == cancel_target`. Completion of the cancel op itself is always emitted (so the pager learns the cancellation was processed). The cancelled submission's own completion may arrive as `outcome = cancelled` OR not at all if the native primitive raced with completion; the pager tolerates both. |

## Ordering guarantees

### Same-handle ordering

Two submissions on the same handle are ordered as follows:
- If both carry `link_prior = true`, the kernel observes them as a dependency chain; the second does not begin until the first completes.
- If the pager instead submits the second only after observing the first's completion, ordering is trivially preserved.
- The backend MUST NOT reorder same-handle writes among themselves, even without explicit linking, when the pager has submitted them in a single batch. (Rationale: WAL frame-append order is load-bearing.)

### Cross-handle ordering

Independent. The pager must explicitly sequence cross-handle dependencies (e.g., `fsync(main-db)` before `unlink(wal-sidecar)` during checkpoint).

### Commit barrier

The fsync that seals a commit MUST be submitted with `link_prior = true` to the most recent prior write on the same handle. Its completion MUST be observed before the pager transitions to `COMMIT_ACK` (see `pager-async.spec.md` § "Pager states").

### Cancel ordering

A cancel submission has no ordering dependency with other submissions; it is a side-channel instruction. Its completion may arrive interleaved with others.

## Buffer lifecycle

`payload_buffer_ref` binds to a native buffer. The backend treats it as borrowed: the pager MUST keep the buffer live and unmutated from the moment of submission until the matching completion is observed (or the buffer is explicitly cancelled and drained).

Fixed-buffer registration (the kernel's zero-copy buffer-pool facility) is **deferred to a future optimization phase**. v1 uses per-submission buffers. The pager's buffer-pool is opaque to the backend; the backend just reads/writes the bytes at the indicated address range.

## Error mapping

The backend consumes native completion records (which carry a signed result field) and emits `schema/io-completion.schema.json` records per this mapping:

| Native result        | Completion outcome | `error_condition`              |
|----------------------|--------------------|--------------------------------|
| result ≥ 0 (expected length for read/write) | ok   | —                              |
| 0 ≤ result < expected length (read/write)  | error | `IO_BACKEND_SHORT_READ` / `IO_BACKEND_SHORT_WRITE` |
| "interrupted" signal | retried by backend; if persistent: error | `IO_BACKEND_EINTR` (after internal retries exhausted) |
| "try again" / ring-busy | internal retry up to 3 times with brief yield; if still failing: error | `IO_BACKEND_FULL_QUEUE` |
| "no such file"       | error              | `IO_BACKEND_ENOENT`            |
| "permission denied"  | error              | `IO_BACKEND_EACCES`            |
| "already exists"     | error              | `IO_BACKEND_EEXIST`            |
| "invalid argument"   | error              | `IO_BACKEND_EINVAL`            |
| "no space left"      | error              | `IO_BACKEND_ENOSPC`            |
| "I/O error"          | error              | `IO_BACKEND_EIO`               |
| "operation unsupported" | error           | `IO_BACKEND_UNSUPPORTED`       |
| "operation cancelled" (for a cancel target) | cancelled | `IO_BACKEND_CANCELLED` if raised as an error by the pager; typically silent drop |
| anything else        | error              | `IO_BACKEND_EIO` with `reason` set to native diagnostic |

A backend-internal invariant violation (e.g., the ring memory-mapping is corrupt) MUST surface as `IO_BACKEND_BACKEND_CRASH`; the pager treats this as session-fatal.

## Submission batching and drain discipline

- **Batched submit.** The pager enqueues up to `SQ_CAPACITY` submissions before issuing a single submit-and-wait cycle. The backend supports batch submission as its native primitive.
- **Drain-all on submit.** After each submit-and-wait, the backend drains every available completion from the CQ and hands them back to the pager. The pager is then free to map, dispatch, or drop each completion per `pager-async.spec.md` § "Epoch stamping".
- **Non-blocking poll.** The backend exposes a non-blocking "any completions ready?" primitive for the pager's pre-submit drain policy (see `pager-async.spec.md` § "Backpressure" step 1).

## Initialization and teardown

- **Init.** The first `open_database` on this backend triggers ring setup, feature probe, and one no-op round-trip. All subsequent database sessions in the same process share the ring. (Alternative: per-session rings. v1 uses one shared ring per process for simplicity; profile-driven revisit if contention matters.)
- **Teardown.** Process exit releases the ring. A pager-level `close_database` only releases its own handles; the ring survives until process exit. Orderly shutdown drains the CQ.

## Concurrency

The ring is accessed by a single thread at a time. The pager guarantees this via its single-writer model. If a generator chooses to let multiple reader-sessions submit concurrently, it MUST serialise access to the submission primitive (the underlying system expects single-issuer semantics when that mode is enabled).

## Fallback on runtime feature failure

If the backend was selected at init but a later submission returns `IO_BACKEND_UNSUPPORTED` (e.g., a kernel update removed an opcode), the backend does NOT attempt to fall back to sync mid-session. Rationale: partial completions may be in flight; mixing backends risks ordering violations. Instead: propagate `IO_BACKEND_UNSUPPORTED` upward, which the pager converts to `STORAGE_IO_BACKEND_FAILED`. Session fails; caller re-opens with a different backend via configuration.

## Non-goals (Phase 5b)

- **Kernel poll thread.** Not enabled by default. Userland-opt-in reserved for future benchmarking.
- **Zero-copy fixed buffers.** Deferred.
- **Polled I/O on NVMe.** Deferred.
- **Multishot reads.** Not required by the storage workload.
- **Direct I/O (bypass kernel page cache).** Deferred; requires alignment constraints that complicate the buffer-ref contract.
- **Runtime backend switching.** The backend is selected at first `open_database` and sticky for the process lifetime.

## Test authority

Phase 5b correctness is gated by:

- **Behavioural equivalence:** every `tests/cross-build/phase*.json` fixture that passes on the sync backend MUST pass byte-identically with this backend active. No new fixture is needed for equivalence alone.
- **Throughput gate:** `tests/roundtrip_io_uring_insert_bench.py` (Linux-only) drives L4 INSERT throughput with this backend; asserts a minimum ops/sec floor. This is the gating test for publishing L4 numbers.
- **Ordering gate:** a harness-level instrumentation test verifies the commit-barrier invariants from `pager-async.spec.md` § "Ordering invariants (WAL under async)": it records the sequence of submission-op + completion-op observed and asserts the partial orders hold for every commit.

## Compatibility pins

- **Minimum kernel:** 5.13.
- **Maximum known-good:** tested on kernels through the current publication platform's version. Later kernels are expected to work; regressions get platform-gated fixture entries.
- **glibc / musl:** no dependence. The backend uses the raw syscall interface via its language's standard binding.
