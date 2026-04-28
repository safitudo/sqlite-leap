---
name: compiler/statements/pragma
kind: leaf
inherits:
  - /parts/storage/master.md
emits:
  c:    { path: src-c/compiler/statements/pragma.c, headers: [src-c/compiler/statements/pragma.h] }
  rust: { path: src-rust/src/compiler/statements/pragma.rs }
---

# Part: compiler/statements/pragma

Compiles `PRAGMA name [= value] | (arg)`. Recognizes the v2 core
subset plus the Phase C.7 expansion (~80 pragmas). Unknown pragmas
are silently no-op (mainline-compatible).

## Supported pragmas (Phase 6aw)

| Pragma | Semantics |
|---|---|
| `journal_mode [= ... ]` | Getter returns `wal`/`memory`. Setter accepts `WAL`, `MEMORY`, other values rejected silently. |
| `synchronous [= ... ]` | Getter returns integer (0=OFF, 1=NORMAL, 2=FULL, 3=EXTRA). Setter accepts those values; see §Synchronous semantics. |
| `foreign_keys` | Getter/setter boolean (advisory — FK enforcement out of scope). |
| `table_info(name)` | Returns one row per column with `{cid, name, type, notnull, dflt_value, pk}`. |
| `index_list(table)` | Returns rows `{seq, name, unique, origin, partial}`. |
| `page_size` | Fixed at 4096 in v2. Setter is no-op. |
| `user_version [= N]` | Integer stored in header. |
| `application_id [= N]` | Integer stored in header. |

Unknown pragma → emit a zero-row empty-columns program, no error.

## Synchronous semantics (Phase A.4)

`PRAGMA synchronous` controls the durability/throughput tradeoff
of write commits. The level is **per-connection state** (not
global); it is established at connection-open from the database
default and may be changed at any time. The setter accepts both
the symbolic names and the integer codes:

| Code | Symbol  | Mainline behaviour we match                                                       |
|------|---------|-----------------------------------------------------------------------------------|
| 0    | OFF     | No fsync at any commit boundary. OS may reorder; OS crash may corrupt the DB.     |
| 1    | NORMAL  | fsync at WAL checkpoint only. WAL frame appends + commit not fsynced individually. |
| 2    | FULL    | fsync after every WAL commit (commit-frame write). Default outside WAL mode.      |
| 3    | EXTRA   | FULL + fsync of the directory containing the WAL file after WAL replacement.      |

The default for new connections is `NORMAL` (matches mainline's
WAL-mode default per the v1 production roadmap §1.2).

### Pin S1 — four-level enum

The synchronous level is a closed enum with exactly four members:
`Off (0)`, `Normal (1)`, `Full (2)`, `Extra (3)`. **Canonical home
of the type is `parts/storage/parts/wal/shapes.json::SyncLevel`**
(every fsync site lives in storage; pragma is the user-facing
surface that re-imports the same type). Targets emit this as an
idiomatic enum (Rust `enum`, C `enum`, Zig `enum`, Go `iota`-block,
Python `IntEnum`). The integer codes are part of the on-the-wire
pragma surface — `PRAGMA synchronous = 2` and
`PRAGMA synchronous = FULL` are equivalent, both produce
`SyncLevel::Full`.

### Pin S2 — getter rendering

`PRAGMA synchronous` (no `=`) returns one row, one column named
`synchronous`, integer-typed, value in `{0,1,2,3}`. Targets MUST
NOT return the symbolic name (mainline returns the integer).

### Pin S3 — setter parsing

`PRAGMA synchronous = X` where X is parsed case-insensitively:
- `0`, `OFF`, `'off'`           → `SyncLevel::Off`
- `1`, `NORMAL`, `'normal'`     → `SyncLevel::Normal`
- `2`, `FULL`, `'full'`         → `SyncLevel::Full`
- `3`, `EXTRA`, `'extra'`       → `SyncLevel::Extra`

Any other token is silently ignored (mainline behaviour: keeps
the previous level). The setter returns zero rows.

### Pin S4 — per-connection lifetime

The level lives on the **connection state struct**, not on the
shared database. Two connections to the same database file may
hold different sync levels concurrently. The level affects only
fsync calls issued by THAT connection's writer. (Effect of mixing:
if connection A is OFF and connection B is FULL, frames written
by A are durable only to the OS-flush boundary; B's writes are
durable on every commit. This matches mainline.)

### Pin S5 — fsync gating obligation

Storage-layer fsync sites (file-format atomic-rename commit, WAL
frame commit, WAL checkpoint, WAL directory fsync) MUST consult
the connection's `SyncLevel` before issuing the fsync. The
mapping is specified in `parts/storage/parts/wal/master.md`
§"fsync discipline by synchronous level" (pins W15..W18). Each
storage site that calls fsync today must accept a `SyncLevel`
argument or call a connection-state accessor; **a storage site
that fsyncs unconditionally is out of compliance with this pin**.

### Pin S6 — accessor surface

Targets emit two accessors on the connection-state struct:

- `connection_get_synchronous(state) -> SyncLevel` — returns the
  current level.
- `connection_set_synchronous(state, level) -> unit` — replaces
  the level. Idempotent.

These are the only entry points the PRAGMA handler uses to read
or mutate the level. Storage callers use `connection_get_synchronous`
to decide whether to fsync at any given site. PRAGMA handlers and
storage code MUST NOT touch the field directly.

---

# Phase C.7 — full PRAGMA surface (~80 pragmas)

This phase extends the v2 core subset with mainline's published
PRAGMA surface (sqlite.org/pragma.html). Pragmas are grouped by
family. Unless explicitly stated otherwise:

- **Getter** form `PRAGMA name` returns one row, one column
  named `name`, integer- or text-typed per the table below.
- **Setter** form `PRAGMA name = value` mutates state and
  returns zero rows (mainline-compatible). Some pragmas
  ("query-style" — see Pin C7-2) return a row on set.
- **Persistence axis** is one of: `db-header` (lives in the
  database file header bytes — survives close/reopen for any
  connection), `db-shared` (per-database, in-memory only —
  shared across connections to the same DB handle), `per-conn`
  (per-connection state — does not affect siblings), or
  `compile-time` (constant baked at generation time, no setter).
- **Default** is the value returned for a freshly-opened
  database with no prior settings written.

### Pin C7-1 — pragma family registry is closed

Targets emit a single dispatch table mapping lowercase pragma
name to handler. The table is the union of the Phase 6aw
pragmas, the Phase A.4 synchronous pragma, and every pragma
named in §§Cache / Journal / Schema-integrity / Compile-time
intro / Stats / Auto / Other below. A pragma name not present
in the table dispatches to `pragma_unknown`, which emits a
zero-row, zero-column program. Pragma name lookup is
case-insensitive (mainline behaviour). Targets MUST NOT
register pragmas via string-comparison ladders — the dispatch
table is the spec contract.

### Pin C7-2 — query-style vs assignment-style

A pragma is **query-style** if its getter form returns rows
(e.g. `table_info`, `integrity_check`, `compile_options`).
Query-style pragmas accept arguments via `PRAGMA name(arg)` or
`PRAGMA name = arg` and emit rows in both forms. An
**assignment-style** pragma (e.g. `cache_size`, `synchronous`)
returns one row on the bare getter form and zero rows on the
setter form. The `kind` field on each pragma family below
states which it is. Returning rows from a setter for an
assignment-style pragma is out of compliance.

### Pin C7-3 — silently-ignored unknown values

For setters that accept a closed enum of values (e.g.
`journal_mode`, `locking_mode`, `auto_vacuum`, `encoding`),
unknown tokens are **silently ignored**: previous value
retained, no error, setter returns zero rows. This mirrors
mainline. Numeric-typed setters (e.g. `cache_size`,
`page_size`, `user_version`) accept any signed-64-bit integer
literal; values outside an individual pragma's documented
range are clamped per that pragma's rules below, never errored.

---

## §Cache family (assignment-style)

| Pragma | Persistence | Default | Notes |
|---|---|---|---|
| `cache_size` | per-conn | -2000 (~2 MiB) | Negative = KiB; positive = pages. |
| `cache_spill` | db-shared | enabled | Boolean or page-count. Controls dirty-page spill mid-txn. |
| `page_size` | db-header | 4096 | Settable only on empty DB or before first write; otherwise no-op. |
| `max_page_count` | db-shared | 1073741823 | Soft cap on file size in pages. |
| `mmap_size` | per-conn | 0 (compile-time default) | Bytes of file to mmap; 0 = disabled. |
| `secure_delete` | db-header tri-state | 0 (off) | `0`/`1`/`fast`. Zero-fills freed page payload on delete. |

### Pin C7-Cache-1 — cache_size sign convention

`cache_size = N`: if `N >= 0`, the cache holds at most `N`
pages. If `N < 0`, the cache holds at most `|N| * 1024` bytes
of pages (i.e. `|N|` KiB). Getter returns the value as last
set, preserving the sign. Targets MUST store the raw signed
integer, not a normalized page-count.

### Pin C7-Cache-2 — page_size mutation rules

The setter mutates the database header `page_size` field iff
the database is empty (zero pages allocated) OR has not yet
been written to in the current transaction. After data exists,
the setter is a silent no-op and the getter still returns the
existing header value. Implementations MAY restrict
`page_size` to the closed set `{512, 1024, 2048, 4096, 8192,
16384, 32768, 65536}`; values outside the set are silently
ignored. The Phase 6aw "fixed at 4096" rule remains the de
facto v2 default but is no longer a hard floor.

### Pin C7-Cache-3 — mmap and max_page_count clamps

`mmap_size` is clamped to `[0, compile_time_mmap_max]`; values
above the compile-time ceiling are silently capped.
`max_page_count` returns the *current* cap on getter; setter
writes the new cap and returns the cap actually applied
(equals the request unless it would shrink below the current
page count, in which case the current page count is returned
and the cap is set to that). `secure_delete` accepts `0`, `1`,
or `fast` (case-insensitive); `fast` is stored as enum `Fast`
and returned as integer `2` on getter (mainline rendering).

---

## §Journal family

| Pragma | Kind | Persistence | Default | Notes |
|---|---|---|---|---|
| `journal_mode` | assignment | db-shared | `wal` (v2) | Closed enum: `delete`/`truncate`/`persist`/`memory`/`wal`/`off`. |
| `journal_size_limit` | assignment | db-shared | -1 (no limit) | Bytes; -1 disables truncation. |
| `locking_mode` | assignment | per-conn | `normal` | Closed enum: `normal`/`exclusive`. |
| `wal_autocheckpoint` | assignment | db-shared | 1000 | Frame-count threshold for auto-checkpoint. |
| `wal_checkpoint` | query | n/a (action) | n/a | Returns one row `{busy, log, checkpointed}`. |

### Pin C7-Journal-1 — journal_mode closed enum + getter rendering

`journal_mode` setter accepts the six tokens above
case-insensitively; any other token is silently ignored
(Pin C7-3). Getter returns the current mode as a **lowercase
text value** in the column named `journal_mode`. The setter
ALSO returns one row containing the resulting mode (rare
exception to Pin C7-2: mainline returns the new mode on set so
clients can detect silent rejection of e.g. `wal` on a
non-shared-cache DB). Targets MUST emit the row on set.

### Pin C7-Journal-2 — locking_mode and journal_size_limit

`locking_mode` getter returns `normal` or `exclusive` (lowercase
text). Setter accepts those two tokens; on `exclusive`,
subsequent transactions retain the file-level lock until
explicit `normal` is set or the connection closes. The mode is
**per-connection** — siblings unaffected. `journal_size_limit`
is a signed integer; `-1` disables; getter returns the value
last set, setter returns zero rows.

### Pin C7-Journal-3 — wal_checkpoint action

`wal_checkpoint` (and the parameterized form
`wal_checkpoint(MODE)` where MODE is one of
`{passive, full, restart, truncate}`) is a **query-style action
pragma**: it triggers a WAL checkpoint and returns exactly one
row with three integer columns — `busy` (1 if a writer held
the WAL during the call, else 0), `log` (frames in the WAL
after the call), `checkpointed` (frames moved into the main DB
by the call). `wal_autocheckpoint = N` sets the threshold;
`N <= 0` disables the auto-checkpoint hook. Both pragmas
delegate to the WAL spec (`parts/storage/parts/wal/master.md`)
and MUST NOT implement checkpoint logic locally.

---

## §Schema-integrity family

| Pragma | Kind | Persistence | Default | Notes |
|---|---|---|---|---|
| `integrity_check[(N)]` | query | n/a | n/a | Rows of error strings, or one row `ok` if clean. |
| `quick_check[(N)]` | query | n/a | n/a | Like integrity_check but skips index/content cross-checks. |
| `foreign_key_check[(table)]` | query | n/a | n/a | Rows: `{table, rowid, parent, fkid}`. |
| `foreign_keys` | assignment | per-conn | 0 (off) | Boolean; advisory in v2. |
| `defer_foreign_keys` | assignment | per-conn | 0 | Boolean; defers FK violations until txn commit. |
| `ignore_check_constraints` | assignment | per-conn | 0 | Boolean. |
| `recursive_triggers` | assignment | per-conn | 0 | Boolean. |
| `trusted_schema` | assignment | per-conn | 1 | Boolean; 0 disallows non-deterministic functions in schema. |

### Pin C7-Integrity-1 — integrity_check / quick_check shape

Both pragmas return zero or more rows of one column named
`integrity_check` (or `quick_check`), text-typed. A clean
database returns exactly one row whose value is the literal
text `ok`. Errors return one row per finding, each holding a
free-form English description. Optional integer argument `N`
caps the number of rows emitted; default cap is 100. Targets
MUST NOT raise an error from these pragmas — corruption is
reported via rows, never via runtime fault.

### Pin C7-Integrity-2 — foreign_key_check shape

`foreign_key_check` walks every (table, foreign-key) pair and
emits one row per orphan child. Row shape:
`(table TEXT, rowid INTEGER, parent TEXT, fkid INTEGER)`.
Optional `(table)` argument restricts the walk. A clean
database returns zero rows. The pragma is read-only; it MUST
NOT modify the database.

### Pin C7-Integrity-3 — boolean assignment pragmas

`foreign_keys`, `defer_foreign_keys`, `ignore_check_constraints`,
`recursive_triggers`, `trusted_schema` accept the boolean
tokens `0/1/true/false/yes/no/on/off` (case-insensitive). The
getter returns the value as integer `0` or `1` (never the
symbolic form). All five live on the connection-state struct
(Pin S4 template) — siblings unaffected. v2 stores the bits
but enforcement of FK / CHECK / recursive-trigger semantics is
out of v2 scope; pragmas are advisory until those features
land.

---

## §Compile-time-introspection family (compile-time, getters only)

| Pragma | Default | Notes |
|---|---|---|
| `compile_options` | n/a | Multi-row text — one row per option string. |
| `sqlite_version` | "3.46.0-leap" (per build) | One row, one text column. |
| `library_version` | same as sqlite_version | Alias for compatibility. |
| `source_id` | per-build | Git-hash-style identifier of the LEAP build. |

### Pin C7-Compile-1 — content is a build-time table

The four pragmas above are pure compile-time constants. Targets
emit a single static array (Rust `&[&str]`, C `static const
char * const`, Zig `const`, Go package-level `var`, Python
module constant) holding the strings, populated by the
generator from `parts/build/manifest.spec.md` at emission
time. The pragmas have no setter; setter form is silently
ignored. Version strings MUST NOT be hard-coded inside the
pragma handler — they flow from the build manifest.

---

## §Stats / introspection family (query-style, getters only)

| Pragma | Argument | Row shape |
|---|---|---|
| `stats` | none | `(table TEXT, idx TEXT, stat TEXT)` (sqlite_stat1 surface) |
| `table_info(t)` | table name | `(cid, name, type, notnull, dflt_value, pk)` |
| `table_xinfo(t)` | table name | table_info + `hidden` column |
| `index_info(i)` | index name | `(seqno, cid, name)` |
| `index_xinfo(i)` | index name | index_info + `desc, coll, key` |
| `index_list(t)` | table name | `(seq, name, unique, origin, partial)` |
| `foreign_key_list(t)` | table name | `(id, seq, table, from, to, on_update, on_delete, match)` |
| `database_list` | none | `(seq, name, file)` — main + attached DBs |
| `collation_list` | none | `(seq, name)` |
| `function_list` | none | `(name, builtin, type, enc, narg, flags)` |
| `module_list` | none | `(name)` — registered virtual table modules |

### Pin C7-Stats-1 — schema introspection is read-through

`table_info`, `table_xinfo`, `index_info`, `index_xinfo`,
`index_list`, `foreign_key_list` all read from the in-memory
schema (parsed from `sqlite_schema`) and MUST NOT consult the
storage layer directly. Handler signature is
`(schema, table_or_index_name) -> rows`. Missing names produce
zero rows (mainline behaviour) — no error.

### Pin C7-Stats-2 — global lists

`database_list`, `collation_list`, `function_list`, `module_list`
return one row per registered entity. Order is registration
order (stable across calls within a connection). For
`function_list`, the `builtin` column is `1` for spec-defined
builtins and `0` for app-registered functions; v2 has no
app-registered functions, so the column is constantly `1`.

### Pin C7-Stats-3 — table_xinfo / index_xinfo extension columns

`table_xinfo` returns the `table_info` columns plus a `hidden`
integer column (`0` ordinary, `1` HIDDEN, `2` generated-virtual).
v2 has no hidden or generated columns, so the column is
constantly `0` for every row. `index_xinfo` adds `desc` (sort
order, 0/1), `coll` (collation name, text), `key` (1 if the
column is part of the index key, 0 if it's an auxiliary stored
column). Targets MUST emit these columns even when the values
are constant — clients select on column count.

---

## §Auto / behavioural family (assignment-style)

| Pragma | Persistence | Default | Notes |
|---|---|---|---|
| `auto_vacuum` | db-header | 0 (none) | Closed enum: `none`(0)/`full`(1)/`incremental`(2). Settable only on empty DB. |
| `incremental_vacuum[(N)]` | action (query) | n/a | Performs N-page incremental vacuum; returns zero rows. |
| `automatic_index` | per-conn | 1 | Boolean. Allow planner to build transient indexes. |
| `query_only` | per-conn | 0 | Boolean. When 1, all writes are rejected. |
| `read_uncommitted` | per-conn | 0 | Boolean. v2 ignores (WAL is already snapshot-isolating). |

### Pin C7-Auto-1 — auto_vacuum is header-bound, set-once

`auto_vacuum` lives in the database header (per fileformat
spec). Setter mutates the header field iff the database is
empty; otherwise silent no-op (Pin C7-3). Getter returns the
integer code (`0`/`1`/`2`). Tokens `none`/`full`/`incremental`
are accepted on set, but the getter NEVER returns the symbolic
name — integer always (mainline parity).

### Pin C7-Auto-2 — incremental_vacuum action

`incremental_vacuum` (no arg) reclaims all currently-free
pages on the freelist. `incremental_vacuum(N)` reclaims at
most `N` pages. The pragma is an action — it returns zero
rows regardless of arg form. It is a no-op when
`auto_vacuum != 2` (incremental mode). Targets MUST NOT raise
an error in the no-op case.

### Pin C7-Auto-3 — query_only enforcement obligation

When `query_only = 1`, every DML statement compile that would
emit a write opcode (Insert, Delete, Update, idx-write, schema
mutation) MUST short-circuit at compile time and emit a
runtime program that raises `READONLY` on first step. The
compiler consults `connection_get_query_only(state)` once per
compile. This is **not** advisory; it is a hard gate.
`read_uncommitted` is parsed and stored but has no v2 effect
(snapshot isolation in WAL mode subsumes it).

---

## §Other / miscellaneous family

| Pragma | Kind | Persistence | Default | Notes |
|---|---|---|---|---|
| `case_sensitive_like` | assignment | per-conn | 0 (LIKE case-insensitive) | Boolean. |
| `encoding` | assignment | db-header | `UTF-8` | Closed enum: `UTF-8`/`UTF-16le`/`UTF-16be`. Settable only on empty DB. |
| `legacy_alter_table` | assignment | per-conn | 0 | Boolean; chooses pre-3.25 ALTER semantics. |
| `optimize[(MASK)]` | action (query) | n/a | n/a | Triggers planner-stat refresh; returns zero rows. |
| `threads` | assignment | per-conn | 0 | Worker-thread count for sort/index. |
| `soft_heap_limit` | assignment | global | 0 (off) | Bytes; 0 disables. |
| `hard_heap_limit` | assignment | global | 0 (off) | Bytes; 0 disables. |
| `application_id` | assignment | db-header | 0 | Signed 32-bit integer. |
| `user_version` | assignment | db-header | 0 | Signed 32-bit integer; opaque to engine. |
| `schema_version` | assignment | db-header | 1 | Engine-managed; setter is admin-only. |
| `data_version` | query | db-shared | 1 (monotonic per write txn) | Read-only. |

### Pin C7-Other-1 — encoding is set-once on empty DB

`encoding` mutates the header iff the database has zero pages
allocated; otherwise silent no-op. Getter returns the literal
text token (`UTF-8` / `UTF-16le` / `UTF-16be`). v2 implements
only `UTF-8` for storage; setting `UTF-16le` or `UTF-16be` on
an empty DB IS accepted into the header byte but the storage
layer treats text payloads as UTF-8 regardless until the
encoding-multi codepath lands (out of v2 scope). The header
faithfully reflects the user's request — mainline can read it.

### Pin C7-Other-2 — header-bound integers

`application_id`, `user_version`, `schema_version` are signed
32-bit integers stored in fixed offsets of the database header
(see `parts/storage/parts/fileformat/master.md`). Setters
write the header bytes at txn-commit time; getters read the
live header. `schema_version` is engine-managed — incremented
automatically on every DDL — but the setter is honoured
(mainline parity for admin tools that need to bump it).
`data_version` has NO setter; it is incremented by the storage
layer on every write transaction commit and is per-database
(siblings see the same value, modulo their snapshot).

### Pin C7-Other-3 — soft/hard heap limits are global

`soft_heap_limit` and `hard_heap_limit` are process-global,
not per-connection or per-database. Setter mutates a process
singleton (`heap_limits_singleton`) protected by the storage
mutex. Getter returns the current value. Setting to `0`
disables the limit. The hard limit, if non-zero and exceeded
by an allocation, MUST cause that allocation to fail with
`OUT_OF_MEMORY`; the soft limit MUST trigger best-effort
cache eviction but never fail an allocation. Targets emit a
single shared accessor `heap_limits_get()` /
`heap_limits_set(soft, hard)` — pragmas are dispatchers, not
implementors.

### Pin C7-Other-4 — optimize is a stat-refresh action

`PRAGMA optimize` (and `optimize(MASK)` where MASK is a
bitfield) is an action that refreshes planner statistics on
tables whose `sqlite_stat1` rows are stale. v2 emits a no-op
program (returns zero rows, no errors) until the stat-refresh
codepath lands. The pragma MUST be present in the dispatch
table (Pin C7-1) so clients that call it unconditionally on
connection-close (a common idiom) see a clean zero-row result
rather than `pragma_unknown` dispatch. `legacy_alter_table`,
`case_sensitive_like`, `threads` are stored on the connection
state and consumed by their respective subsystems
(alter-table compiler, LIKE compiler, sort/index runtime).

---

## Phase pins

- **Phase 6aw** — PRAGMA core subset.
- **Phase A.4**  — real synchronous semantics: pins S1..S6 above
  plus pins W15..W18 in the WAL spec. Pre-A.4 the level was
  parsed but ignored; post-A.4 it gates fsync as specified.
- **Phase C.7**  — full PRAGMA surface (~80 pragmas) per
  sqlite.org/pragma.html. Pins C7-1..C7-3 (cross-cutting) plus
  family pins:
    - Cache (3): C7-Cache-1..3
    - Journal (3): C7-Journal-1..3
    - Schema-integrity (3): C7-Integrity-1..3
    - Compile-time intro (1): C7-Compile-1
    - Stats / introspection (3): C7-Stats-1..3
    - Auto / behavioural (3): C7-Auto-1..3
    - Other / miscellaneous (4): C7-Other-1..4
  Total Phase C.7 new pins: 23.

## Regeneration envelope

- Target leaf size: 800–1200 lines per target post-C.7
  (was 300–500 pre-C.7). Dispatch-table-driven; per-pragma
  handler bodies are small.
- Spec ≤ 500 lines.
