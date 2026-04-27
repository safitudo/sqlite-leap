---
name: lib-api/vfs
kind: leaf
shapes: ./shapes.json
inherits:
  - /parts/storage/parts/wal/master.md
  - /parts/storage/parts/fileformat-write-lib/master.md
---

# Part: lib-api/vfs

Virtual File System layer. The single seam between the storage stack
(`fileformat-read`, `fileformat-write-lib`, `wal`) and the host
operating system. Every byte the engine reads from or writes to a
database file, journal file, or WAL sidecar passes through a `Vfs`
implementation. Every directory entry the engine consults
(unlink-on-recover, hot-journal probe, atomic rename) goes through
the same seam.

The contract is a published interface from sqlite.org/vfs.html. We
implement the same shape so that:

1. Existing host integrations that expect to plug in a custom VFS
   (encrypted filesystems, network filesystems, in-memory test
   harnesses, browser-side `OPFS` shims) can target leap-sqlite
   without porting.
2. The WASM build, which has no `unix` syscalls, can ship its own
   VFS (`opfs`, `memdb`) and the rest of the engine never notices.
3. Test code can substitute a `MemoryVfs` and exercise the storage
   path with no disk involvement, deterministically.

This is **not** the io-backend layer (io_uring / kqueue async).
io-backend lives below the VFS — a Linux VFS implementation may
choose to dispatch its `xRead` / `xWrite` through io_uring; that is
internal to that VFS. The VFS spec only fixes the surface.

This is the foundational design pass for the VFS surface. **No
target code is emitted from this part yet.** Deliverable is the
language-neutral spec (this file) plus shape declarations
(`shapes.json`). Target lifts follow in a subsequent wave once the
shape stabilizes.

## Two interfaces

A VFS has two interface blocks:

- **`Vfs`** — handle-free operations on the namespace: open a file,
  delete a file, probe access, resolve a path, get randomness, sleep,
  read the wall-clock, surface the last OS error.
- **`VfsFile`** — operations on an open file handle: read, write,
  truncate, sync, query size, lock/unlock, file-control, sector-size
  hint, device-characteristic flags, and the shared-memory slots
  (`xShm*`) used by the WAL `-shm` index in concurrent multi-process
  WAL mode.

`Vfs.xOpen` is the constructor for `VfsFile`. Every other `Vfs`
operation is stateless from the engine's perspective (the VFS
implementation may keep its own state).

## Vfs interface (namespace operations)

```
xOpen(vfs, path, flags, requested_file_kind)
    -> VfsFile | RuntimeCondition
xDelete(vfs, path, sync_dir: bool)
    -> ok | RuntimeCondition
xAccess(vfs, path, mode: AccessMode)
    -> AccessResult { exists: bool, readable: bool, writable: bool }
xFullPathname(vfs, path)
    -> canonical_path: string | RuntimeCondition
xRandomness(vfs, n_bytes)
    -> bytes (length n_bytes)
xSleep(vfs, microseconds)
    -> microseconds_actually_slept
xCurrentTime(vfs)
    -> JulianDay (real, days since -4713-11-24 12:00 UTC)
xGetLastError(vfs)
    -> { code: int, message: string }
```

`flags` on `xOpen` is a bitset over:

- `OPEN_READONLY`, `OPEN_READWRITE`, `OPEN_CREATE`,
  `OPEN_DELETEONCLOSE`, `OPEN_EXCLUSIVE`, `OPEN_AUTOPROXY`,
  `OPEN_URI`, `OPEN_MEMORY`, `OPEN_NOFOLLOW`.

`requested_file_kind` is one of:

- `MAIN_DB`, `MAIN_JOURNAL`, `TEMP_DB`, `TEMP_JOURNAL`,
  `TRANSIENT_DB`, `SUBJOURNAL`, `SUPER_JOURNAL`, `WAL`.

`AccessMode` is one of `EXISTS`, `READ`, `READWRITE`. The VFS need
not distinguish all three on platforms where they collapse; it only
must answer the predicate the engine asked.

`xFullPathname` resolves a possibly-relative input to a canonical
absolute form. This is the path used to scope file-locks and to
synthesise sidecar paths (`<canonical>-journal`, `<canonical>-wal`,
`<canonical>-shm`).

`xRandomness` is the only RNG the engine consults for salts,
filenames of temp files, and any cryptographic-grade randomness the
storage stack needs. Targets MUST source this from a
cryptographically-acceptable platform RNG (per `wal` part §Salt
discipline).

`xCurrentTime` returns Julian Day as a real number. Engine code that
needs civil time converts at the call site.

`xGetLastError` returns an OS-flavored error pair the engine can
surface in user-facing diagnostics. The `code` is platform-specific;
the `message` is human-readable.

## VfsFile interface (per-handle operations)

```
xRead(file, offset, n_bytes)
    -> bytes (length n_bytes) | RuntimeCondition
xWrite(file, offset, bytes)
    -> ok | RuntimeCondition
xTruncate(file, new_size_bytes)
    -> ok | RuntimeCondition
xSync(file, flags: SyncFlags)
    -> ok | RuntimeCondition
xFileSize(file)
    -> size_bytes: int | RuntimeCondition
xLock(file, level: LockLevel)
    -> ok | RuntimeCondition
xUnlock(file, level: LockLevel)
    -> ok | RuntimeCondition
xCheckReservedLock(file)
    -> reserved_held_by_other: bool
xFileControl(file, op: FileControlOp, arg)
    -> FileControlResult | RuntimeCondition
xSectorSize(file)
    -> sector_bytes: int   # informational; affects sync hints only
xDeviceCharacteristics(file)
    -> DeviceCharBits      # bitset; see below

# Shared-memory slots (used by WAL -shm in multi-process mode)
xShmMap(file, region_index, region_size, extend: bool)
    -> SharedRegionRef | RuntimeCondition
xShmLock(file, offset_index, n_slots, kind: ShmLockKind)
    -> ok | RuntimeCondition
xShmBarrier(file)
    -> ok
xShmUnmap(file, delete_flag: bool)
    -> ok
```

### Lock levels

`LockLevel` is the SQLite lock ladder: `NONE`, `SHARED`, `RESERVED`,
`PENDING`, `EXCLUSIVE`. The ladder is monotonic on `xLock` (you may
only request a level >= current) and monotonic on `xUnlock`
downward. The semantics are:

- `NONE` — no lock held; any writer may proceed.
- `SHARED` — reader; multiple shared locks coexist.
- `RESERVED` — declared writer-intent; only one at a time; readers
  may continue.
- `PENDING` — writer waiting for shared locks to drain; new shared
  locks are blocked.
- `EXCLUSIVE` — writer holds the file alone.

The engine never holds `PENDING` directly; it is an internal step
of an `xLock(SHARED → EXCLUSIVE)` upgrade.

### SyncFlags

`SyncFlags` is a bitset:

- `SYNC_NORMAL` — flush data to durable storage.
- `SYNC_FULL` — flush data plus any filesystem metadata required
  for the file to be visible at its current size after a crash
  (e.g. fsync of containing directory after rename).
- `SYNC_DATAONLY` — caller asserts no metadata depends on this
  sync; on platforms with `fdatasync`, prefer it.

### DeviceCharBits

A bitset describing what the underlying device guarantees, used by
the engine to skip redundant work:

- `ATOMIC` — writes <= sector_size are atomic.
- `ATOMIC_512` / `ATOMIC_1K` / `ATOMIC_2K` / `ATOMIC_4K` /
  `ATOMIC_8K` / `ATOMIC_16K` / `ATOMIC_32K` / `ATOMIC_64K` —
  writes of that size and aligned to that size are atomic.
- `SAFE_APPEND` — appending to a file by extending it is atomic
  (writes never expose the new size before the new bytes).
- `SEQUENTIAL` — multiple writes issued in order are durable in
  order (rare; conservative VFS clears this).
- `UNDELETABLE_WHEN_OPEN` — Windows-style; `xDelete` may fail while
  any handle is open.
- `POWERSAFE_OVERWRITE` — overwriting a sector preserves the
  bytes outside the written range across power loss.
- `IMMUTABLE` — file cannot be modified through this handle.

A conservative VFS returns `0` (no characteristics asserted) and
the engine falls back to fully-defensive write protocols. A
high-confidence VFS (e.g. a modern Linux filesystem on a
sane storage stack) asserts `POWERSAFE_OVERWRITE | SAFE_APPEND`
and lets the engine skip redundant journal padding.

### ShmLockKind

`SHARED` or `EXCLUSIVE`. The shared-memory region carries the
WAL-index hash table (see `parts/storage/parts/wal/master.md`
§"wal-index file" open question). v1 leap-WAL uses an in-process
index; the `xShm*` slots exist on the interface for future
multi-process WAL but may return `NOT_IMPLEMENTED` on v1 VFS
implementations.

## File-control opcodes

`xFileControl` is the extension seam. Each opcode either reads
state from the VFS, mutates it, or both. Required v1 opcodes:

- `FCNTL_LOCKSTATE` — return current lock level (debug).
- `FCNTL_SIZE_HINT` — caller hints the eventual file size; VFS may
  preallocate.
- `FCNTL_CHUNK_SIZE` — caller suggests an allocation chunk; VFS
  rounds future extensions up to multiples.
- `FCNTL_SYNC_OMITTED` — engine notice that an `xSync` was skipped
  for performance; VFS may surface a warning.
- `FCNTL_HAS_MOVED` — query whether the file's path has changed
  underneath us (someone renamed the file since `xOpen`).
- `FCNTL_VFSNAME` — return the VFS's registered name.
- `FCNTL_PRAGMA` — pass a PRAGMA name+value pair; VFS may handle
  it, return `NOT_FOUND`, or surface an error.

VFS implementations MAY define additional opcodes; opcodes the VFS
does not recognise return `NOT_IMPLEMENTED` and the engine treats
that as a no-op success.

## Default unix VFS

Targets that run on POSIX systems ship a default VFS named `"unix"`.
Its semantics, in spec form (no language idioms):

- `xOpen` maps to `open(2)` with flags translated from the bitset.
  The returned `VfsFile` carries the file descriptor plus the
  canonical path (resolved by `xFullPathname`).
- `xRead` / `xWrite` map to `pread` / `pwrite` at the requested
  offset. Short reads zero-fill the trailing portion (engine
  contract: a read past EOF is not an error; it returns the bytes
  that exist plus zeroes, and the caller checks `xFileSize` if it
  needs to know whether EOF was hit).
- `xTruncate` maps to `ftruncate`.
- `xSync(SYNC_NORMAL)` maps to `fsync`; `SYNC_DATAONLY` to
  `fdatasync` where available.
- `xLock` / `xUnlock` use POSIX advisory byte-range locks
  (`fcntl(F_SETLK)`) on a published byte map: byte 1 = `RESERVED`,
  byte 2 = `PENDING`, bytes 3..258 = `SHARED` slots, bytes 3..258
  also serve as `EXCLUSIVE` when held as a write-lock. Engine code
  never sees the bytes; only the lock-level vocabulary.
- `xCheckReservedLock` probes the `RESERVED` byte with a
  test-and-no-set query.
- `xRandomness` reads from `/dev/urandom`.
- `xSleep` maps to `usleep` / `nanosleep`.
- `xCurrentTime` reads the wall-clock and converts to Julian Day.
- `xGetLastError` snapshots `errno` and `strerror`.
- `xSectorSize` returns 4096 unless the underlying filesystem
  reports otherwise via `statfs`/`statvfs`; it is an upper-bound
  hint, not a contract.
- `xDeviceCharacteristics` returns
  `POWERSAFE_OVERWRITE | SAFE_APPEND` on filesystems known to honor
  them; conservative `0` otherwise.

Targets that run on Windows ship a separate `"win32"` VFS with
analogous semantics (CreateFileW / LockFileEx / FlushFileBuffers).
Targets that run as WASM ship a separate `"opfs"` (or `"memdb"`)
VFS. Target-specific mapping lives in
`parts/targets/<lang>/mapping.md`, not here.

## Registration

A process holds a **VFS registry**: a list of named `Vfs`
instances plus a single "default" pointer. The registry is
discovered through three operations:

```
sqlite3_vfs_register(vfs, make_default: bool)
    -> ok | RuntimeCondition
sqlite3_vfs_unregister(vfs)
    -> ok | RuntimeCondition
sqlite3_vfs_find(name | nil)
    -> Vfs | not_found
```

Semantics:

- The registry is process-global. Multiple `Vfs` instances may be
  registered simultaneously; each has a unique `name` string.
- `register(vfs, make_default=true)` inserts `vfs` and points the
  default at it. Subsequent `find(nil)` returns `vfs`. The previous
  default remains registered under its name and is returnable by
  `find("its-name")`.
- `register(vfs, make_default=false)` inserts without disturbing
  the default.
- `unregister(vfs)` removes by identity; if `vfs` was the default,
  the default falls back to the previously-registered one (or
  `not_found` if none remain).
- `find(name)` returns the registered VFS with `name`, or
  `not_found` if absent.
- `find(nil)` returns the current default, or `not_found` if no
  VFS is registered.
- Registration is order-independent: any VFS may be registered
  before or after `open_database`. An `open_database` call that
  did not specify a VFS resolves to whatever the default is at
  open time; the binding is captured for the lifetime of the
  database handle and does not float if the default is later
  changed.

The registry is initialized empty. Targets ship a startup hook
that registers their default VFS (`"unix"`, `"win32"`, `"opfs"`,
or `"memdb"`) before the first `open_database` call.

A target's startup hook is an idempotent no-op if called twice;
multiple databases opening concurrently from different threads
must converge on the same registered default without racing.

## Multi-VFS coexistence

The engine routes each open database through the VFS that opened
it. The same process may have:

- DB-A open through `"unix"` (production data on local disk).
- DB-B open through `"memdb"` (test fixture).
- DB-C open through `"unix"` again but with `OPEN_NOFOLLOW`
  (paranoid host).

Each `Database` carries a reference to the `Vfs` it was opened
through; storage-layer calls always go via that reference. A VFS
implementation MUST be re-entrant across multiple `VfsFile`
instances (multiple databases through one VFS) and SHOULD be
thread-safe, but thread-safety is a per-target requirement
captured in `parts/targets/<lang>/mapping.md`.

## Sidecar paths

The storage stack synthesises sidecar paths by suffix:

- Rollback journal: `<db-canonical-path>-journal`
- WAL log: `<db-canonical-path>-wal`
- WAL shared-memory: `<db-canonical-path>-shm`
- Super-journal (multi-DB transactions): `<db-canonical-path>-mj{8-hex}`

These are constructed by string concatenation on the canonical
path returned by `xFullPathname`, then opened through the same
VFS that opened the main database. The VFS does not have to know
about sidecars as a category; it sees them as ordinary files with
a `requested_file_kind` of `MAIN_JOURNAL`, `WAL`, or
`SUPER_JOURNAL`.

## Error vocabulary

VFS operations surface errors as named conditions. The set v1
fixes:

- `IO_ERR` — generic I/O failure (read, write, sync).
- `IO_ERR_READ` / `IO_ERR_SHORT_READ` — read-specific.
- `IO_ERR_WRITE` — write-specific.
- `IO_ERR_FSYNC` — sync failed.
- `IO_ERR_TRUNCATE` — truncate failed.
- `IO_ERR_LOCK` — lock acquisition failed (resource).
- `IO_ERR_UNLOCK` — lock release failed.
- `IO_ERR_DELETE` — unlink failed.
- `IO_ERR_ACCESS` — access probe failed (separate from "file does
  not exist", which is a successful `xAccess` returning `exists:
  false`).
- `IO_ERR_NOMEM` — VFS out of memory.
- `BUSY` — lock held by another process; caller should back off.
- `READONLY` — write attempted on a read-only opening.
- `CANTOPEN` — `xOpen` could not produce a `VfsFile`.
- `NOT_IMPLEMENTED` — operation unsupported by this VFS
  (e.g. `xShmMap` on a v1 unix VFS that opted out of multi-process
  WAL).

Each named condition carries the OS-level code/message accessible
via `xGetLastError`.

## Out of scope (v1 VFS spec)

- Network filesystem advisory-lock quirks. The default `unix`
  VFS uses POSIX byte-range locks; behavior on NFS/SMB is
  filesystem-dependent and surfaces as `BUSY` or `IO_ERR_LOCK`.
- Encrypted-page hooks. Page encryption is out of v1 scope per
  CLAUDE.md `Deferred to follow-up stunts`. When added, it
  hooks below the VFS as a page-codec, not inside it.
- `xShmMap` cross-process semantics. v1 may return
  `NOT_IMPLEMENTED` for `xShm*`; in-process WAL index satisfies
  single-process use. Multi-process WAL is the W5 phase pin in
  the `wal` part.
- Async I/O. The VFS API is synchronous-shaped; an async
  io-backend lives below the VFS implementation as an internal
  detail (a Linux unix VFS may dispatch through io_uring while
  exposing the synchronous shape).
- File-format compatibility checks. The VFS sees opaque bytes;
  format validation is the storage layer's job.

## Correctness pins

**V1. Two-block interface.** A VFS implementation provides
exactly two interface blocks: `Vfs` (8 namespace ops) and
`VfsFile` (16 per-handle ops, of which 4 are `xShm*` and may
return `NOT_IMPLEMENTED` in v1). Targets MUST NOT collapse the
two blocks, and MUST NOT add engine-visible methods beyond the
spec list — extension goes through `xFileControl` opcodes.

**V2. Storage stack only talks to the engine through Vfs.**
`fileformat-read`, `fileformat-write-lib`, and `wal` MUST NOT
import platform I/O directly. Every byte goes through `xRead` /
`xWrite`; every sync goes through `xSync`; every namespace
operation goes through the four namespace ops on `Vfs`. The
linter enforces: no `open` / `read` / `write` / `fsync` /
`unlink` / `rename` calls in storage-layer emissions outside the
VFS implementation file.

**V3. xOpen is the only constructor of VfsFile.** Engine code
NEVER constructs a `VfsFile` directly; it always goes through
`Vfs.xOpen`. This makes the VFS the single seam for testing
substitution.

**V4. Lock ladder is monotonic.** `xLock(level)` requires
`level >= current_level`. `xUnlock(level)` requires
`level <= current_level`. Skipping levels upward (e.g.
`SHARED → EXCLUSIVE` directly) is permitted at the API surface;
the VFS implementation handles the intermediate `PENDING` step
internally.

**V5. xRead past EOF is not an error.** A read whose range
extends past the current file size returns the bytes that exist
followed by zero-fill for the remainder, and the result is
considered successful. Callers detect EOF by comparing requested
length to `xFileSize`.

**V6. xSync is the durability boundary.** Writes issued before
`xSync` MAY be visible to readers but are NOT guaranteed durable
across a power loss until `xSync` returns. `SYNC_FULL`
additionally guarantees that any rename or directory-entry
change required for the file to be visible at its post-sync
state is itself durable.

**V7. Process-global, named registry.** `sqlite3_vfs_register`,
`sqlite3_vfs_unregister`, `sqlite3_vfs_find` operate on a single
process-global registry. Each registered VFS has a unique
non-empty `name` string; collisions raise a `RuntimeCondition`
on `register`. `find(nil)` returns the current default.

**V8. Default-handoff is non-destructive.** Registering a new
default does NOT unregister the previous default; both remain
findable by name. Unregistering the current default falls back
to the most-recently-registered remaining VFS, or to "no
default" if none remain.

**V9. Database-to-VFS binding is captured at open time.** A
`Database` opened without an explicit VFS captures the current
default VFS for its lifetime. Later changes to the registry's
default do not migrate already-open databases.

**V10. Canonical paths come from xFullPathname.** Every sidecar
path (`-journal`, `-wal`, `-shm`, `-mj{hex}`) is built by
suffixing the result of `xFullPathname` on the user-supplied
input. The storage stack MUST NOT do its own path normalisation.

**V11. Sidecars open through the same VFS as the main DB.** A
WAL sidecar for a database opened via `"unix"` opens via
`"unix"`. Cross-VFS sidecar opens are a corruption condition.

**V12. xRandomness is the engine's only RNG.** Salts (per the
`wal` part), temp filenames, and any other random values the
storage stack needs come from `xRandomness`. Targets MUST source
this from a cryptographically-acceptable platform RNG; predictable
randomness is a security regression.

**V13. xCurrentTime is the engine's only clock.** Any
timestamp the storage stack records (e.g. WAL header timestamps
if added) flows through `xCurrentTime`. Tests substitute a fixed
clock by registering a VFS whose `xCurrentTime` is deterministic.

**V14. xFileControl unknown opcodes are no-op success.** A VFS
that does not recognise an opcode returns `NOT_IMPLEMENTED`; the
engine treats this as success. New opcodes MAY be introduced
without breaking older VFS implementations.

**V15. xDeviceCharacteristics defaults safe.** A VFS that does
not assert a characteristic returns 0 for that bit and the
engine falls back to fully-defensive protocols. False
assertions are a corruption condition (e.g. claiming
`POWERSAFE_OVERWRITE` on a filesystem that does not provide it
will produce torn writes the engine assumed could not occur).

**V16. xSectorSize is a hint, not a contract.** The engine uses
it to choose write-alignment heuristics. A wrong sector-size
hint cannot cause corruption on its own; it can only make the
engine slower or larger.

**V17. AccessMode predicates are independent.** `xAccess(EXISTS)`
returning true does not imply `xAccess(READ)` returns true; a
file may exist and be unreadable. Each predicate is answered
independently.

**V18. xShm* may return NOT_IMPLEMENTED in v1.** Multi-process
WAL via `-shm` is the W5 phase pin in the `wal` part; v1 VFS
implementations may decline the entire `xShm*` block. The engine
falls back to in-process wal-index when this occurs.

**V19. VfsFile lifetime is bounded by close.** A `VfsFile`
returned by `xOpen` is valid until the engine releases it
(target-specific close mechanism, declared in the target's
mapping). After release, all method calls are undefined; the
engine MUST NOT issue any.

**V20. No invented helpers.** Per the project-wide §Generation
scope rule. Targets emit only the interfaces and registration
functions declared here plus the default-VFS implementation
named in their mapping. No silent stubs, no inline tests, no
helper methods unrelated to the spec list.

**V21. Registry mutation is atomic.** A concurrent
`register` / `unregister` / `find` triple MUST NOT observe a
partial state (a name present but pointer null, or default
pointing at an unregistered VFS). Targets achieve this via a
target-specific mechanism (mutex on Rust/C/Go, GIL on Python,
single-threaded assumption on WASM).

**V22. xFullPathname is idempotent.** `xFullPathname(p)` applied
to an already-canonical path returns that same canonical path.
This is required for sidecar synthesis to be stable across
reopens.

**V23. Lock-level NONE is the post-close state.** Closing a
`VfsFile` while it holds any lock above `NONE` is a usage
error; the engine MUST `xUnlock(NONE)` before release. The VFS
MAY enforce this with a runtime check or a debug-only assertion.

**V24. Mainline-readable file naming.** The `"unix"` default VFS
MUST NOT munge the path (no implicit prefix, no implicit suffix)
between the user-supplied input and the on-disk filename, beyond
what `xFullPathname` does to canonicalise. A database file
written through leap's unix VFS at `/tmp/x.db` is a regular
file at `/tmp/x.db` that mainline `sqlite3` can open.

## Phase pins

- **Phase V0** — spec only (this file). `shapes.json` declares
  the two interfaces, the bitsets, the lock-level enum, and the
  three registration functions. NO target code emitted yet.
- **Phase V1** — single-target prototype (Rust). Implements the
  default `"unix"` VFS plus the registry. Storage layer rewired
  to go through the VFS for the tiny `tests/fixtures/tiny.db`
  smoke. No regression on the existing `fileformat-read` /
  `fileformat-write-lib` smokes.
- **Phase V2** — second target (C) for parity. Same shape
  surface, same smoke green.
- **Phase V3** — `"memdb"` VFS in both targets. Used by
  `tests/cross-build/` to exercise the storage path with no
  filesystem involvement; deterministic across runs.
- **Phase V4** — Multi-VFS smoke: open one DB through `"unix"`
  and another through `"memdb"` in the same process; verify
  each routes through its own VFS.
- **Phase V5** — `"opfs"` VFS for the WASM build. Inherits the
  same shape surface; Phase V5 is the WASM-side proof.
- **Phase V6** — `xShm*` real implementation, paired with WAL
  phase W5 (multi-process WAL). Until then, all targets return
  `NOT_IMPLEMENTED` and the WAL uses an in-process index.

## Regeneration envelope

- Spec line budget: ~600 lines (this file).
- shapes.json: ~150 lines (two interfaces, bitsets, enums, three
  registration functions).
- Target line budget (Phase V1+): ~400–600 lines per target for
  the default unix VFS plus the registry; the registry is small
  (~80 lines), the unix VFS dominates.
- No external deps beyond stdlib; the VFS IS the dependency
  boundary by design.
- Standalone runner per target for VFS smoke (open / write /
  read / sync / close on a tmp file); library module for
  storage-layer callers.

## Open questions (for follow-up phases)

1. **Encryption codec hook.** When v2 adds page encryption, does
   the codec live inside the VFS (one VFS per codec) or below
   it (one codec shared by all VFSes)? Mainline puts it below.
   Defer to v2 scoping.

2. **Async I/O surface.** The VFS API is synchronous-shaped.
   When io_uring lands (Phase W6 in the WAL part), the
   implementation dispatches asynchronously but presents a
   synchronous boundary; this is fine for write throughput but
   leaves read parallelism on the table. A future v2 spec MAY
   add an async-shaped sibling interface (`Vfs2`) that the
   engine prefers when present.

3. **WASM-side path conventions.** The `"opfs"` VFS does not
   have a real filesystem; paths are opaque keys. Does
   `xFullPathname` simply return the input unchanged, or does
   it canonicalise to a normalised form? Defer to V5.

4. **Per-VFS configuration.** Some VFSes need configuration
   (encryption key, cache size). Mainline uses URI query
   parameters parsed by the VFS; we inherit that contract via
   `OPEN_URI`. The exact URI parameter vocabulary is per-VFS
   and lives in each VFS's own master.md, not here.

5. **xCheckReservedLock false-positive handling.** On NFS,
   the reserved-lock probe can return false positives. Mainline
   degrades gracefully (treats it as `BUSY`); leap inherits
   that. Verify under test once a network-FS fixture exists.
