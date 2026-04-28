# Pin 19 — Open questions for follow-up

Companion to `master.md`. Each item is either resolved into a separate
landing (Pin 19a / 19b) or deferred with a clear trigger.

## Resolved into pre-19 landings

1. **`pk_index` representation in path-backed mode — Pin 19a.**
   Today `pk_index: BTreeMap<i64, u32>` (rowid → rowid-only).
   Pin 19 promotes the value to `PageLocation { page_no, cell_index }`.
   Targets that already shipped pin-16-amend's pk_index must migrate.
   Decision: land as **Pin 19a** before 19.1's cursor rewrite, so the
   two changes are independently reviewable. Tracked as task #420.

2. **`fileformat-write` reuse — Pin 19b.**
   The split helpers (`build_leaf_page`, `build_interior_table_page`,
   etc.) live in `fileformat-write/master.md` and are emitted as
   standalone runner code today. Pin 19 needs them callable from the
   cursor write path, not from a runner. Decision: extract them into a
   new shared part `parts/storage/parts/page-codec/` (encode_cell,
   build_leaf_page, build_interior_table_page, varint, serial-type
   picker), imported by both fileformat-write (runner) and btree-write
   (library). Tracked as task #421.

## Deferred with trigger

3. **Cache capacity for path-backed mode.** wal-bridge today defaults
   to 2000 pages = 8 MiB. Pin 19's RAM-growth pin Q3 implies that long
   transactions can push the cache past capacity. Trigger: when a
   single-transaction workload in the bench corpus exceeds 8 MiB of
   dirty pages. At that point: expose `PRAGMA cache_size` and add the
   partial-flush optimization. The 100k-INSERT L4 corpus stays well
   under (1000 pages × 4 KB = 4 MiB), so this is not blocking.

4. **Delete mode under pin 19.** Phase 19.1 keeps Delete mode on the
   whole-file serialize-and-rename path. Mainline's Delete mode
   actually does in-place page writes with a rollback journal sidecar
   — pin 19's cache-flush model could extend cleanly. Trigger: when a
   user requests `PRAGMA journal_mode=DELETE` performance parity. Not
   blocking; WAL mode is the publication-target journal.

5. **Backup engine.** `parts/storage/parts/backup-engine` today reads
   via mem-store row-vectors. After pin 19 the path-backed source has
   no row-vectors to read; the backup engine must decode pages via the
   cache. Trigger: cache-aware deserializer landing (out of scope for
   pin 19 itself; a follow-up). Until then, backup against path-backed
   sources falls through to the existing in-memory bridge with a
   transient round-trip.
