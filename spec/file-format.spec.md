# SQLite-compatible on-disk file format — language-neutral spec

Phase 3a introduces persistent database files with SQLite-compatible layout. This file is the authoritative on-disk spec for sqlite-leap. Derived from the published reference at `https://www.sqlite.org/fileformat2.html`; the source doc is allowed input per CLAUDE.md ("published file-format documentation — these are specs, not implementation"). Mainline SQLite's source code is NOT allowed input.

## Compatibility goal

A file written by sqlite-leap, containing only INTEGER / TEXT / NULL columns in single-page tables, MUST be readable by mainline SQLite 3.x. A file written by mainline SQLite, within the scope sqlite-leap supports (see § "Supported read surface" below), MUST be readable by sqlite-leap.

Out-of-scope features raise named storage errors on read (see § "Unsupported-on-read error surface").

## Endianness

Every multi-byte on-disk field is **big-endian**. In-memory representation in the running engine is host-native; encode/decode at the codec boundary.

## Header (offsets 0–99, always in page 1)

| Offset | Size | Field | sqlite-leap Phase 3a policy |
|--------|------|-------|-----------------------------|
| 0–15   | 16 | Magic string | Write literal `SQLite format 3\0` (16 bytes including trailing NUL). Read: reject if mismatched (`STORAGE_CORRUPT_HEADER`). |
| 16–17  | 2  | Page size (u16 BE; `0x0001` means 65536) | Write 4096. Read: accept 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536. |
| 18     | 1  | File format write version | Write 1 (rollback journal era). Read: accept 1 or 2; reject ≥3 with `STORAGE_CORRUPT_HEADER`. |
| 19     | 1  | File format read version | Same policy as offset 18. |
| 20     | 1  | Reserved bytes per page | Write 0. Read: accept any; compute `usable_size = page_size − reserved`. |
| 21     | 1  | Max embedded payload fraction | Write 64. Read: validate == 64 or raise `STORAGE_CORRUPT_HEADER`. |
| 22     | 1  | Min embedded payload fraction | Write 32. Read: validate == 32. |
| 23     | 1  | Leaf payload fraction | Write 32. Read: validate == 32. |
| 24–27  | 4  | File change counter (u32 BE) | Increment on every commit in Phase 3d+. Write 0 until then; read: ignored. |
| 28–31  | 4  | In-header database size in pages (u32 BE) | Write the actual page count. Read: trust if change counter matches offset 92; else recompute from file size. |
| 32–35  | 4  | First freelist trunk page | Write 0 (Phase 3a has no freelist). Read: if non-zero and freelist not supported, raise `STORAGE_UNSUPPORTED_FEATURE`. Phase 3c will revisit. |
| 36–39  | 4  | Total free pages | Write 0 in Phase 3a. Read: same treatment as offset 32. |
| 40–43  | 4  | Schema cookie | Increment on schema change. Write 0 initially. |
| 44–47  | 4  | Schema format number | Write 4. Read: accept 1–4. |
| 48–51  | 4  | Suggested cache size | Write 0. Read: ignored. |
| 52–55  | 4  | Largest root B-tree page (auto-vacuum) | Write 0 (auto-vacuum disabled). Read: if non-zero, raise `STORAGE_UNSUPPORTED_FEATURE`. |
| 56–59  | 4  | Text encoding | Write 1 (UTF-8). Read: only accept 1; others raise `STORAGE_UNSUPPORTED_FEATURE`. |
| 60–63  | 4  | User version | Write 0. Read: ignored (exposed later via PRAGMA). |
| 64–67  | 4  | Incremental vacuum mode | Write 0. Read: must be 0 if offset 52 is 0. |
| 68–71  | 4  | Application ID | Write 0. Read: ignored. |
| 72–91  | 20 | Reserved for expansion | Write zeros. Read: ignored. |
| 92–95  | 4  | Version-valid-for counter | Keep equal to offset 24. |
| 96–99  | 4  | SQLITE_VERSION_NUMBER of last writer | Write `3038000` (matches a recent SQLite 3.38 release; any modern mainline SQLite accepts this). Read: ignored. |

## Pages

Pages are numbered starting from **1** (page 1 contains the header + `sqlite_schema`'s root page). Page N begins at file offset `(N-1) * page_size`.

### Page types (first byte of page)

| Byte | Type | Phase 3a emits? | Phase 3b emits? | All-phase reads? |
|------|------|-----------------|-----------------|------------------|
| 0x02 | Index interior | No | No | Raise `STORAGE_UNSUPPORTED_FEATURE` |
| 0x05 | Table interior | No | **Yes** | **Yes** |
| 0x0a | Index leaf | No | No | Raise `STORAGE_UNSUPPORTED_FEATURE` |
| 0x0d | Table leaf | **Yes** | **Yes** | **Yes** |

Phase 3a is single-page-table-only: every user table has one root page of type 0x0d. Phase 3b lifts that restriction: tables MAY span arbitrarily many leaves linked by interior pages of type 0x05.

### Table-leaf page header (8 bytes, at start of page; for page 1, at offset 100)

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| 0      | 1    | Page type (`0x0d`) | |
| 1–2    | 2    | First freeblock offset | Write 0 (no freeblocks tracked in 3a). Read: ignored if 0. |
| 3–4    | 2    | Cell count (u16 BE) | |
| 5–6    | 2    | Cell content area start offset | 0 means 65536. Measured from page start. **Writer convention (Phase 3a): for an empty leaf at `page_size < 65536`, write `page_size` (not 0). For `page_size == 65536` (the u16-overflow case), write 0.** Both encodings are accepted on READ. |
| 7      | 1    | Fragmented free bytes | Write 0. Read: ignored if ≤ 60. |

Note: interior pages (0x05, 0x02) would add a 4-byte rightmost-child pointer at offset 8, making the header 12 bytes. Phase 3a does not emit them.

### Cell pointer array

Immediately after the page header: `cell_count` u16 big-endian offsets, each pointing to a cell's start within this page. Cells are ordered by ascending rowid (the key). The pointer array grows toward higher offsets; the cell content area grows toward lower offsets from page end.

### Table-leaf cell format (type 0x0d)

```
[varint: payload_size in bytes]
[varint: rowid]
[payload bytes]
[4-byte big-endian u32: first overflow page]   -- only if payload overflowed, NOT emitted in Phase 3a
```

Phase 3a never overflows: if a record's encoded size would exceed the single-page usable threshold, raise `STORAGE_PAGE_FULL`.

## Phase 3b — multi-page tables

### Table-interior page (type 0x05)

An interior table page routes cell lookups by rowid down the B-tree. It carries no row payload — only routing metadata.

#### Interior page header (12 bytes)

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| 0      | 1    | Page type (`0x05`) | |
| 1–2    | 2    | First freeblock offset | Phase 3b writes 0 (no freeblock tracking). |
| 3–4    | 2    | Cell count (u16 BE) | Number of interior routing cells. |
| 5–6    | 2    | Cell content area start offset | Same writer convention as leaf: write `page_size` for empty, `0` for page_size == 65536. |
| 7      | 1    | Fragmented free bytes | Write 0. |
| 8–11   | 4    | Right-child page number (u32 BE) | The page number of the subtree that holds rowids strictly greater than every cell key in this interior page. MUST be non-zero. |

#### Interior cell format (type 0x05)

```
[4-byte big-endian u32: left-child page number]
[varint: integer key (the largest rowid in the subtree rooted at left-child)]
```

No payload, no overflow. Each cell is exactly `4 + varint_length(key)` bytes.

#### Interior B-tree invariants (MUST hold on every on-disk state the writer produces)

1. **Ordered keys.** Cells in an interior page are ordered by strictly-ascending `key`.
2. **Subtree routing.** For cell `i` with key `k_i`, every rowid in the subtree rooted at `left-child[i]` is `≤ k_i`. Every rowid in the subtree rooted at `right-child` is `> k_N` where `k_N` is the last cell's key.
3. **Uniform leaf depth.** Every leaf descendant of a given root is at the same depth. (Append-only-split preserves this naturally.)
4. **Root identity.** The table's `rootpage` in `sqlite_schema` always points at the top of the tree. When a root splits, the ORIGINAL root page is REUSED as the new interior root (its content is replaced in place); the data formerly in the root moves to a newly-allocated child page. This keeps the `sqlite_schema.rootpage` value stable across splits.

### Split algorithm — writer side (append-only monotonic rowids)

Phase 3b assigns rowids monotonically per table (already specified in Phase 3a: start at 1, never reuse). All new rowids are strictly greater than every rowid already stored. This means INSERT always lands in the RIGHTMOST leaf of the tree. The writer does NOT need to handle mid-tree insertions.

**The split protocol below specifies the INVARIANTS that the on-disk state MUST satisfy after each INSERT, not a specific runtime algorithm.** Under Phase 3a's slurp-on-open / flush-on-close "simplicity strategy" (inherited by 3b — all I/O happens at open/close boundaries), an equivalent and acceptable implementation is to keep live rows in a flat in-RAM list during the session and rebuild the B-tree from scratch at flush time by greedily bin-packing rows into leaves, promoting the root to interior if the result spans more than one leaf. Both "incremental split on each INSERT" and "full rebuild at flush" implementations are legal as long as the post-flush on-disk state satisfies the invariants (ordered cells, stable `sqlite_schema.rootpage`, monotone rowids, uniform leaf depth). Cross-build byte-identity of files is NOT required in Phase 3b; Phase 3e may tighten this if needed.

**INSERT recipe:**

1. Walk the tree from `rootpage` following right-child / right-most-cell edges until a leaf is reached. Call this the **target leaf**.
2. Encode the new cell (payload + rowid varint + payload-size varint — same as Phase 3a).
3. If the target leaf has room (`cell_size + 2 ≤ page_free_bytes`): insert the cell at the end of the cell array (highest rowid so it sorts last), update cell pointer array, update cell-count and cell-content-area-start in the page header. Done.
4. Else the leaf is full: **split**.

**Split protocol:**

Let `L_full` = the full target leaf at page `P`. Let `row_hi` = the rowid being inserted (strictly greater than every rowid in `L_full`).

- **Case A: L_full is the table's root (the tree is a single leaf).** This happens exactly once per table — on the first split.
  1. Allocate a new page `R` (page number = current file page count + 1; extend the file by one page).
  2. Copy `L_full`'s contents byte-for-byte to page `R`. `R` is now a leaf holding all prior rows.
  3. Allocate a second new page `N` (page count + 2) and initialise it as an empty leaf.
  4. Write the new row's cell into `N`.
  5. Overwrite page `P` (the original root) as an **interior** page (`0x05`): one cell `{left-child = R, key = max_rowid_in_R}`, right-child = `N`. This preserves the `sqlite_schema.rootpage` pointer.
  6. Bump the in-header page count by 2.

- **Case B: L_full is a non-root leaf whose parent is the table root.** The tree is already 2-level (root interior + leaves).
  1. Allocate a new page `N` (page count + 1) and initialise it as an empty leaf.
  2. Write the new row's cell into `N`.
  3. In the parent interior:
     - Promote `L_full`'s former right-child role into an interior cell: add a new cell `{left-child = L_full, key = max_rowid_in_L_full}` at the end of the parent's cell array (strictly greater than every existing cell key, so ordering holds).
     - Update the parent's right-child to `N`.
  4. If the parent has room for the new interior cell: done (bump in-header page count by 1).
  5. Else: the parent is full — **STORAGE_PAGE_FULL**. Phase 3b does NOT split interior pages. At the default 4096-byte page size an interior page holds roughly `(4096 − 12) / (4 + 2)` ≈ 680 interior cells, each routing a leaf of ~400 tiny-row entries → ~270,000 rows per table. Interior-split support moves to Phase 3c.

- **Case C: L_full is a leaf deeper than 2 levels.** Phase 3b writers NEVER produce trees deeper than 2 levels, so this case cannot arise from writes. If encountered on READ (a pre-existing file written by mainline SQLite), the reader traverses it normally per the read algorithm below.

### SELECT / full-table-scan recipe — reader side

Arbitrary-depth trees MUST be read correctly (mainline SQLite may have written deeper trees). The Phase 3b cursor algorithm:

- **Rewind**: push the root page onto a path stack. While the current page is an interior, descend to the left-child of its first cell (or to the right-child if cell count is 0 — degenerate but legal), pushing each interior along the way. Stop when a leaf is reached. Position at cell 0 of that leaf.
- **Next**: advance within the current leaf. If the leaf is exhausted, pop the path stack and advance the parent cursor to its next cell or right-child. If that parent is exhausted, pop again. When popping an interior cursor, descend the leftmost path of the newly-exposed subtree.
- **Step-past-tombstone**: any leaf cell with a tombstone flag is skipped (Phase 3b keeps the tombstone mechanism from 3a — DELETE writes a tombstone bit; rows are not physically removed from the page).

### Where Phase 3b raises errors

- `STORAGE_PAGE_FULL` — only when the table root is a full interior (≥ ~680 children) AND a new leaf split would require a new interior cell. See Case B step 5. Single-row-too-large-for-any-page still raises (deferred to 3c's overflow pages).
- `STORAGE_CORRUPT_PAGE` — if an interior page's right-child is 0, or a cell's left-child is 0, or cell keys are not strictly ascending, or a routed subtree's page number exceeds the file's page count.
- All Phase 3a errors still apply (`STORAGE_FILE_IO`, `STORAGE_CORRUPT_HEADER`, `STORAGE_UNSUPPORTED_FEATURE`, `STORAGE_UNSUPPORTED_TYPE`).

### Non-goals for Phase 3b

Deferred features (surfacing any of them in generated code would be a spec violation):

- Interior-page splits → Phase 3c (would lift the ~270k rows/table cap).
- Freelist / page reuse → Phase 3c.
- Overflow pages for oversize rows → Phase 3c.
- Mid-tree inserts (non-monotonic rowids) → Phase 4 (user-controlled `INSERT … VALUES (rowid, …)` or `INTEGER PRIMARY KEY`).
- Deletion rebalancing (merging sparse leaves) → Phase 3c or later; Phase 3b leaves tombstoned cells in place and pays the read cost.
- Rowid varint signed interpretation under non-monotonic insertion — N/A because 3b stays monotonic.

### Test authority (Phase 3b)

`tests/cross-build/phase3b.json` is the executable specification for Phase 3b. Phase 3a and earlier must stay green.

## Varint encoding

Variable-length integer, 1–9 bytes, big-endian.

- **Bytes 1–8**: high bit set (`0x80 | (value_chunk & 0x7F)`), carrying 7 bits of value each.
- **Byte 9**: if the value doesn't fit in 8 varint-bytes (8 × 7 = 56 bits), byte 9 is taken as 8 raw bits (no high-bit-clear termination). So byte 9 carries 8 bits, not 7.

Encoding algorithm (writer):
1. If value fits in 7 unsigned bits, emit one byte with high bit clear.
2. Else emit up to 8 bytes with high bit set, each carrying the next 7 most-significant bits; terminate with a byte whose high bit is clear.
3. If the value would need more than 8 bytes, emit 8 bytes with high-bit-set 7-bit chunks followed by a 9th byte with the low 8 bits.

Decoding algorithm (reader): read bytes until high bit is clear OR 8 bytes have been consumed (then read one more raw byte).

**Signedness.** The varint form is unsigned (carries a non-negative integer up to 64 bits). Where a varint is used as a **rowid** (the cell key in a table-leaf cell), the decoded `u64` is reinterpreted as a signed 64-bit integer via two's-complement bitcast (`i64 = u64 as i64`). Phase 3a always assigns rowids in the monotonic range `[1, 2^63 − 1]` so this bitcast is a no-op, but generators MUST implement the signed interpretation to stay compatible with mainline SQLite-produced files that may have been written from the negative rowid range.

## Record format (for cell payloads)

```
[varint: header_size in bytes]          -- includes the size of THIS varint
[varint: serial_type_0]
[varint: serial_type_1]
...
[varint: serial_type_N-1]
[body: column_0_bytes]
[body: column_1_bytes]
...
[body: column_N-1_bytes]
```

`header_size` is the total number of bytes of the record header (the initial varint + all the serial type varints). Knowing header_size + payload_size (from the cell) lets the reader locate the column bodies.

### Serial types

| Serial type | Body size | Meaning | Phase 3a emits? | Phase 3a reads? |
|-------------|-----------|---------|-----------------|-----------------|
| 0 | 0 | NULL | **Yes** | **Yes** |
| 1 | 1 | 8-bit signed int | **Yes** (if fits) | **Yes** |
| 2 | 2 | 16-bit signed int BE | **Yes** (if fits) | **Yes** |
| 3 | 3 | 24-bit signed int BE | **Yes** (if fits) | **Yes** |
| 4 | 4 | 32-bit signed int BE | **Yes** (if fits) | **Yes** |
| 5 | 6 | 48-bit signed int BE | **Yes** (if fits) | **Yes** |
| 6 | 8 | 64-bit signed int BE | **Yes** | **Yes** |
| 7 | 8 | IEEE-754 64-bit float (big-endian byte order) | **Yes** (Phase 6g) | **Yes** (Phase 6g) |
| 8 | 0 | Constant 0 | No | **Yes** (yields INTEGER 0) |
| 9 | 0 | Constant 1 | No | **Yes** (yields INTEGER 1) |
| 10, 11 | — | Reserved | — | Raise `STORAGE_CORRUPT_PAGE` |
| ≥12, even | (N−12)/2 | BLOB | No | Raise `STORAGE_UNSUPPORTED_TYPE` |
| ≥13, odd | (N−13)/2 | TEXT (per header encoding) | **Yes** | **Yes** (UTF-8 only, per header offset 56) |

**Integer serial-type selection (writer):** for an integer value `v`, pick the SMALLEST serial type whose range includes `v`. Rationale: smaller encoding → smaller files → faster I/O → better Lane 4 and Lane 5.

```
0:                                     serial type 0  (NULL)
-128 ≤ v ≤ 127:                        serial type 1
-32768 ≤ v ≤ 32767:                    serial type 2
-8388608 ≤ v ≤ 8388607:                serial type 3
-2^31 ≤ v ≤ 2^31 - 1:                  serial type 4
-2^47 ≤ v ≤ 2^47 - 1:                  serial type 5
else (full i64):                        serial type 6
```

Phase 3a always uses serial types 1–6 for user INTEGER columns. Serial types 8 and 9 are accepted on READ (they decode to INTEGER 0 and 1) but never written.

**Real serial-type selection (writer, Phase 6g):** for a `Value::Real` (IEEE-754 double), the writer emits serial type 7 and the payload is the 8 raw bytes of the double in **big-endian byte order**. Generators on little-endian hosts (x86_64, arm64) must byte-swap the in-register double before writing; readers must byte-swap after reading. There is no attempt to compact a Real that happens to be an integer value (e.g. `1.0`); a Real always round-trips as serial type 7.

**Serial type is Value-derived, not column-derived.** The record encoder MUST choose the serial type from the runtime Value alone (its tag: NULL, Integer, Real, Text — plus magnitude for integers). The declared column type from the schema is NOT consulted during serial-type selection. A NULL in an INTEGER column encodes as serial type 0, not as a zero-valued integer. This keeps the record-encoding contract decoupled from any schema-registry lookup and matches mainline SQLite's "per-value, not per-column" storage discipline.

## The sqlite_schema table

Page 1 is always a table-leaf B-tree for `sqlite_schema`. Its root page is page 1 — the header shares the page.

`sqlite_schema` columns:

| Column    | Type    | Phase 3a value                            |
|-----------|---------|-------------------------------------------|
| type      | TEXT    | `'table'` (other types rejected on read)  |
| name      | TEXT    | The table's name (same as `tbl_name` in 3a)|
| tbl_name  | TEXT    | Same as `name` in 3a                       |
| rootpage  | INTEGER | Page number of that table's root page      |
| sql       | TEXT    | Canonical CREATE TABLE statement as the user wrote it (case-preserved for identifiers) |

On CREATE TABLE, sqlite-leap:
1. Allocates a new page (next free page number = current page count + 1, since no freelist in 3a). The N-th user table created in a file therefore lives on page `N + 1` (since page 1 is `sqlite_schema`). This deterministic numbering is mandatory for cross-build file byte-identity.
2. Initializes the new page as an empty table-leaf (type 0x0d, cell count 0).
3. Inserts a row into `sqlite_schema` describing the new table. The row's rowid is `K + 1` where `K` is the count of `sqlite_schema` entries that existed before this CREATE. sqlite_schema rowids form a contiguous monotone sequence starting at 1.
4. Increments the schema cookie (offset 40–43).
5. Updates the in-header page count.

On open, sqlite-leap reads page 1, parses `sqlite_schema` entries, and for each `type='table'` entry, records `(name, columns[], rootpage)` in its in-memory schema registry. Rows are lazily loaded from each root page when the table is queried.

### Canonical CREATE TABLE SQL — writer form (Phase 3a)

When serializing a table definition to the `sqlite_schema.sql` column, sqlite-leap MUST emit exactly this form:

```
CREATE TABLE <name> (<col1> <TYPE1>, <col2> <TYPE2>, ...)
```

Specifically: one ASCII space after `CREATE`, `TABLE`, and `<name>`; one space between each `<colN>` and its `<TYPEN>`; comma-space (`, `) between column definitions; no trailing semicolon; no surrounding whitespace. `<TYPEN>` is `INTEGER` or `TEXT` (uppercase, exactly as spec-enumerated). `<name>` and `<colN>` are emitted in their case-preserved as-parsed form.

### CREATE TABLE SQL — reader tolerance (Phase 3a)

On reopen, sqlite-leap parses each `sqlite_schema.sql` entry to recover `(name, columns[])`. The reader MUST accept:

- The canonical writer form above.
- Extra ASCII whitespace (` `, `\t`, `\n`, `\r`) anywhere a space or comma is allowed, including after `(` and before `)` and around commas.
- Case-insensitive keywords (`CREATE|create|CrEaTe`, `TABLE|table`, `INTEGER|integer`, `TEXT|text`).
- A single optional trailing semicolon.

The reader MUST reject (with `STORAGE_UNSUPPORTED_FEATURE` carrying `feature="create_sql_form"`):

- Quoted identifiers (`"x"`, `` `x` ``, `[x]`).
- Any column-constraint keywords (`NOT NULL`, `PRIMARY KEY`, `DEFAULT`, `CHECK`, etc.).
- Any type keyword other than `INTEGER` / `TEXT` (case-insensitive).
- Multiple statements, trailing garbage after the closing `)` beyond an optional semicolon.

This tolerance band is the minimum set that lets sqlite-leap-written files round-trip through mainline `sqlite3` (whose `.dump` + re-ingest path may normalise whitespace) without losing table definitions. Phase 4 widens the accepted surface.

## Supported read surface (Phase 3a)

We READ files that:

- Use any valid page size (512–65536).
- Contain only table-leaf pages (no interior, no indices).
- Use columns with serial types 0 (NULL), 1–6 (integer), 8, 9 (constants), or ≥13 odd (TEXT, UTF-8 only).
- Have no freelist, no auto-vacuum, no journal/WAL left by a crashed writer.
- Have UTF-8 text encoding (offset 56 = 1).
- Have empty or well-formed `sqlite_schema` entries of type='table' with simple `CREATE TABLE` SQL (within Phase 2a's grammar: INTEGER/TEXT columns only, no constraints).

Everything else raises `STORAGE_UNSUPPORTED_FEATURE` or `STORAGE_UNSUPPORTED_TYPE`. Phases 3b–3e, 4, 6 widen this surface.

## Unsupported-on-read error surface

New storage errors introduced in Phase 3a:

- `STORAGE_FILE_IO` — filesystem-level failure (open, read, write, sync). Fields: `path` (string), `operation` (one of `"open"`, `"read"`, `"write"`, `"sync"`, `"close"`).
- `STORAGE_CORRUPT_HEADER` — header fails validation (magic, fixed fractions, invalid page size, unreadable read version). Fields: `path` (string), `field` (string — which field failed), `expected` (string — brief description of the valid value or range), `got` (string or integer — what we actually saw).
- `STORAGE_CORRUPT_PAGE` — page contents fail validation (invalid page type byte, cell pointer out of range, reserved serial types 10/11, cell count implies content beyond page size). Fields: `page` (integer — page number), `reason` (string — short diagnostic).
- `STORAGE_PAGE_FULL` — a write operation (INSERT or UPDATE producing a larger record) would require more space than the remaining usable page region. Fields: `table` (string), `required_bytes` (integer — the full serialized cell size including its 2-byte pointer: `payload_size_varint + rowid_varint + payload_body + 2`), `available_bytes` (integer — `usable_size − 8 − 2 × current_cell_count − sum_of_existing_cell_sizes`, i.e. the bytes remaining between the cell pointer array's next slot and the cell content area). Tests that care about exact numerics set both fields explicitly; tests that only assert the error category omit them.
- `STORAGE_UNSUPPORTED_FEATURE` — the file uses a feature we don't implement yet (non-zero freelist, non-zero auto-vacuum, page type 0x02/0x05/0x0a, WAL mode, non-UTF-8 encoding). Fields: `path` (string), `feature` (string identifier).
- `STORAGE_UNSUPPORTED_TYPE` — a cell's serial type is one we don't handle (BLOB, FLOAT). Fields: `table` (string), `column` (string, if resolvable), `serial_type` (integer).

All propagate through the VDBE and executor unchanged, matching the existing `STORAGE_*` error convention.

## Creation protocol (on `open_database(path)` with path missing)

1. Allocate a single zero-filled page of 4096 bytes.
2. Fill in the header fields per the table above.
3. At offset 100 (end of header, start of page 1's B-tree content area), write an 8-byte table-leaf header with `page_type=0x0d`, `cell_count=0`, `cell_content_area_start = 4096` (or 0 which means 65536 for non-default page sizes — here 4096 so use 4096).
4. Write the page to the file.

The resulting 4096-byte file is a valid empty SQLite database. `sqlite3 file.db ".schema"` must produce no output and exit cleanly.

## Close protocol (on `close_database(handle)`)

1. For every dirty page in the in-memory cache, serialize to bytes and write to the correct offset.
2. Update the in-header page count (offset 28–31) if new pages were allocated during the session.
3. Flush (`fsync` equivalent) the file.
4. Release the file handle.

Phase 3a does NOT implement durability guarantees (no journal). A crash mid-write may corrupt the file. Tests never crash, so correctness is preserved; benchmark publication waits for Phase 3d.

## Test authority (Phase 3a)

`tests/cross-build/phase3a.json` is the executable specification for Phase 3a on-disk behaviour. Phase 2a's in-memory tests remain in force and MUST stay green (the in-memory backend is UNCHANGED).

## Phase 9a additions — empty index-leaf page (type 0x0a) and sqlite_schema 'index' rows

Phase 9a extends the writable on-disk surface to include **empty index-leaf pages** (type `0x0a`, cell count 0). Populated index-leaf pages (cell count > 0) and index-interior pages (type `0x02`) remain unsupported for 9a — they ship in 9b and 9d respectively.

### Index-leaf page (type 0x0a) — empty form (Phase 9a)

An empty index-leaf page has the same 8-byte B-tree header shape as a table-leaf page (type 0x0d), with `page_type=0x0a`:

| Offset | Size | Field                        | Phase 9a value |
|--------|------|------------------------------|----------------|
| 0      | 1    | Page type (`0x0a`)           | `0x0a`         |
| 1–2    | 2    | First freeblock offset       | `0x0000` (no freeblocks) |
| 3–4    | 2    | Cell count                   | `0x0000` (empty — Phase 9a) |
| 5–6    | 2    | Cell content area start      | `page_size` (or `0x0000` meaning 65536 for non-default page sizes) |
| 7      | 1    | Fragmented free bytes        | `0x00` |

Populated index-leaf cell layout (payload records + rowid-append key encoding) is deferred to Phase 9b.

### Index-interior page (type 0x02) — still unsupported in 9a

Reading or writing page type `0x02` still raises `STORAGE_UNSUPPORTED_FEATURE { feature: "page_type_0x02" }`. An empty index can always fit on a single leaf page, so 9a never produces an interior index page. Phase 9d (or earlier, when index cell counts grow) will lift this.

### sqlite_schema `type='index'` rows (Phase 9a)

Phase 9a widens the `sqlite_schema.type` accepted values from `{'table'}` to `{'table', 'index'}`:

| Column    | Type    | 9a 'index'-row value |
|-----------|---------|----------------------|
| type      | TEXT    | `'index'`            |
| name      | TEXT    | The index's name (as-parsed) |
| tbl_name  | TEXT    | The target table's name (as-parsed) |
| rootpage  | INTEGER | Page number of the index's root (a leaf-index page in 9a) |
| sql       | TEXT    | Canonical `CREATE INDEX` statement — see `sql-grammar.spec.md` § "Canonical `CREATE INDEX` writer form" |

Rowid assignment: `sqlite_schema` rows are written in **creation order across types**. A table-then-index sequence yields sqlite_schema rowids `1, 2` for the table and index respectively.

On DB open, index rows are parsed and their `(name, tbl_name, columns[], unique)` tuple is registered in the in-memory schema registry (`columns` and `unique` are recovered by parsing the `sql` column). In 9a, this registry entry is **informational only** — the query planner does not consult it.

### Phase 9a reader-tolerance changes (from Phase 3a)

Phase 3a reader raised `STORAGE_UNSUPPORTED_FEATURE` on any file containing page type `0x0a`. Phase 9a relaxes:

- **Empty index-leaf pages (type 0x0a, cell count 0):** accepted. The page is read but not traversed (since no cells exist).
- **Populated index-leaf pages (type 0x0a, cell count > 0):** still raise `STORAGE_UNSUPPORTED_FEATURE { feature: "index_leaf_with_cells" }`. Lifted in 9b.
- **Index-interior pages (type 0x02):** still raise `STORAGE_UNSUPPORTED_FEATURE { feature: "page_type_0x02" }`. Lifted in 9d.
- **`sqlite_schema` rows with `type='index'`:** accepted; parsed; registered. NOT consulted by query planner in 9a.

### Phase 9a writer-behaviour changes (from Phase 3a)

- On `CreateIndex` opcode dispatch (see `vdbe-opcodes.spec.md` § Phase 9a), the writer allocates a new page as an empty index-leaf (type 0x0a, cell count 0) and inserts a `type='index'` row into `sqlite_schema`. Schema cookie bumped; page count updated.
- Writer MUST NOT emit cells into index-leaf pages in 9a. Phase 9b adds the cell-emission path.
- Writer MUST NOT emit index-interior (0x02) pages. Phase 9d adds them when index trees need to split.

### Bidirectional compat guarantee (Phase 9a)

A sqlite-leap-written DB containing one or more 9a-scaffolded empty indexes:

1. Can be opened by mainline `sqlite3` — mainline sees the `CREATE INDEX` entry in `sqlite_schema` and registers the empty index. A subsequent query against the indexed table uses or doesn't use the index based on mainline's planner; either way it gets correct results (the table's data is unchanged). Mainline's `PRAGMA integrity_check` must pass.
2. A mainline-written DB containing empty indexes (e.g. `CREATE TABLE t(x); CREATE INDEX i ON t(x);` with no INSERTs) can be opened by sqlite-leap without error. Indexes are registered but not used.

The round-trip smoke suite in `tests/cross-build/roundtrip_smoke.py` (or a follow-on `roundtrip_index.py`) verifies this empirically.

## Phase 9be additions — populated index-leaf pages + index cell format

Phase 9be lifts the "empty index-leaf only" restriction from 9a. Index-leaf pages may now contain cells. Index cells reuse the Phase 3a record format for their payload, with the rowid appended as the final record column (no separate rowid varint like table cells have).

### Populated index-leaf page (type 0x0a, cell count > 0)

The 8-byte page header is identical to the 9a empty form except `cell_count > 0` and `cell_content_area_start < page_size`. The cell pointer array and the cell content area follow the same conventions as table-leaf pages:

- Cell pointers occupy bytes `[8, 8 + 2*cell_count)`. Each pointer is a 2-byte big-endian offset into the page at which a cell begins.
- Cells are laid out bottom-up in the cell content area (offsets decrease as more cells are added), exactly like table-leaf pages.
- Cell pointers are in KEY-SORTED order (not insertion order) — index cells must be sorted by their key tuple per the Phase 9be planner's ordering rules.

### Index cell format (type 0x0a, populated)

Each index cell has this layout:

```
[varint: payload_size in bytes]
[payload bytes]
```

**No rowid varint** — unlike table-leaf cells (which have a separate rowid varint before the payload), index-leaf cells only have the payload-size varint followed by the payload. The rowid is embedded IN the payload as the last record column.

**No overflow pointer in 9be** — cells MUST fit fully in-page. If a cell would exceed the page's usable space, backfill fails with `STORAGE_PAGE_FULL`. Phase 9d will add overflow handling.

### Index cell payload (record format)

The payload is a standard SQLite record (per § "Record format") with columns:

```
[indexed_col_0, indexed_col_1, ..., indexed_col_k-1, rowid_as_integer]
```

For a single-column index on a TEXT column with value `"hello"` and rowid `42`, the payload is a record of 2 columns:

- Column 0: TEXT `"hello"` — serial type ≥13 odd, body = UTF-8 bytes
- Column 1: INTEGER `42` — serial type 1 (fits in 8-bit signed), body = 1 byte

Encoded:

```
header_size_varint = 3  (this varint + 2 serial-type varints = 3 bytes total for a simple case; exact depends on text length)
serial_type_varint_0 = (5*2 + 13) = 23  (5 bytes of text, formula: 2*len + 13)
serial_type_varint_1 = 1                (INTEGER fits in 8-bit)
body: "hello"                            (5 bytes UTF-8)
body: 0x2A                                (1 byte, 42)
```

The enclosing cell prepends `payload_size_varint` (in this example, payload body = 3+5+1 = 9 bytes → `payload_size_varint = 9`).

### Index cell ordering

Cells on an index-leaf page are ordered by their record content, not by cell pointer offset. The comparison rule:

1. Compare columns one-by-one, left-to-right, using the type-aware rules from `sql-grammar.spec.md` § "Phase 9be backfill algorithm" (NULL-first, INTEGER/REAL numeric, TEXT byte-wise, type-class precedence NULL < INTEGER/REAL < TEXT).
2. First differing column determines order.
3. If all indexed columns are equal, the tie-breaker is the appended rowid (integer, ascending).

Because the rowid is embedded in the record, the comparison chain ALWAYS terminates — duplicate indexed-column tuples on different rows are still ordered by rowid.

### Phase 9be reader-tolerance changes

Lifts the 9a restrictions:

- **Populated index-leaf pages (type 0x0a, cell_count > 0):** accepted. Cells are parsed on open for well-formedness validation (header size, offset ranges); cell contents are NOT consulted by the query planner in 9be (planner uses compile-time index selection, runtime cursor traversal).
- **Index-interior pages (type 0x02):** STILL raise `STORAGE_UNSUPPORTED_FEATURE { feature: "page_type_0x02" }`. Lifted in 9d when index-tree splits land.

### Phase 9be writer-behaviour changes

On `CreateIndex` opcode with a non-empty target table:

1. Perform the 9a scaffold actions (collision check, page allocation).
2. Iterate existing table rows to build sorted index cells (per `sql-grammar.spec.md` § "Phase 9be backfill algorithm").
3. If total cell bytes > page's usable-space budget, raise `STORAGE_PAGE_FULL { table, required_bytes, available_bytes }`; release the allocated page; do NOT write the sqlite_schema row.
4. Otherwise, serialize cells into the 0x0a page (sorted order, bottom-up in content area), write page, write sqlite_schema row, bump schema cookie + page count.

DML maintenance (INSERT / UPDATE / DELETE updating the index) is NOT implemented in 9be — indexes go stale on subsequent DML. This is a documented non-goal; Phase 9c fixes it.

### Bidirectional compat (Phase 9be)

A leap-written DB with populated 0x0a indexes:

1. Openable by mainline SQLite. Mainline's `PRAGMA integrity_check` passes. Mainline's query planner MAY use the index; results match leap's.
2. A mainline-written DB with populated 0x0a indexes (single-leaf only — multi-page indexes with 0x02 interior pages still blocked) is openable by leap. Leap's equality planner uses it.

Phase 9d lifts the single-leaf restriction.

## Phase 9d additions — interior index pages + index-tree splits

Phase 9d unblocks the `STORAGE_PAGE_FULL` ceiling from 9be/9c by introducing **index leaf splits**, **interior index pages** (page type 0x02), and **arbitrary-depth index trees**. Bidirectional file-format compatibility with mainline SQLite is preserved.

### Interior index page layout (type 0x02)

Layout matches leaf interior table pages (type 0x05) structurally, but interior INDEX cells carry an index record (key cols + rowid) instead of a rowid-only key.

```
byte 0        : page-type byte = 0x02
bytes 1..2    : first freeblock offset (big-endian u16) — 0 if none
bytes 3..4    : cell count (big-endian u16)
bytes 5..6    : cell content area start (big-endian u16) — 0 interpreted as 65536
byte 7        : fragmented-free-bytes count (u8)
bytes 8..11   : rightmost child pagenum (big-endian u32) — non-zero
bytes 12..    : cell pointer array (cell-count × big-endian u16, each pointing into cell content area)
...
cell content area (grows down from page end):
each interior-index cell is:
  [4 bytes big-endian u32 : left-child pagenum]
  [varint : payload_size]
  [payload bytes : standard record (key_col_0 ... key_col_{k-1}, rowid_as_integer)]
```

**Traversal for search key `K`:**
- Binary-search the cells for the first cell whose record-key is `≥ K`. Descend into that cell's `left-child` pagenum.
- If every cell's record-key is `< K`, descend into the `rightmost child pagenum`.
- Standard B-tree descent; identical to mainline's traversal of 0x02 pages.

### Leaf split algorithm

Triggered when `IdxInsert` (Phase 9c) would cause a leaf's cell content to overflow the leaf's usable byte budget.

1. Allocate a new leaf page (new pagenum, empty 0x0a page).
2. Split the current leaf's cells + the new cell into sorted order (cells are maintained sorted; inserting the new one at its sort position produces an ordered sequence).
3. Distribute the sorted sequence between the old leaf and the new leaf. Target: each leaf gets as-equal-as-possible byte load. A simple split point is the median cell by count; a byte-balanced split is preferred but not required.
4. The SMALLER-key leaf keeps the original pagenum; the LARGER-key leaf takes the newly-allocated pagenum.
5. Promote a **separator key** to the parent interior page: the separator is a record equal to the FIRST cell of the larger-key leaf. The parent cell's `left-child` points at the original pagenum; after insertion, the parent's `rightmost child` (if this cell becomes the new rightmost separator) points at the new-leaf pagenum.
6. If no parent exists (the leaf was the root):
   - Allocate a new interior page (new pagenum, empty 0x02 page).
   - The new interior page becomes the new root: its first (and only) cell's `left-child` = old-leaf pagenum; its `rightmost child` = new-leaf pagenum.
   - The old-leaf pagenum is NO LONGER the index's root. Update `sqlite_schema.rootpage` for this index to the new interior pagenum.
7. Else (parent exists):
   - Insert the separator cell into the parent at its sort position.
   - If this parent would overflow, recursively split the parent (same algorithm — interior splits bubble up with their own separator promotion). A rare tree-height increase event.

### Interior-page split algorithm

When an interior page's cell content would overflow:
1. Allocate a new interior page.
2. Sort the existing cells + the new separator being inserted into a single ordered sequence.
3. Choose a middle cell to **promote** to the grandparent — this middle cell's `left-child` stays with the left half of the new split, and its record becomes the grandparent's separator. The grandparent's rightmost-child (for this sub-range) becomes the new interior page's pagenum.
4. Cells before the middle stay on the old interior page; cells after the middle move to the new interior page.
5. The old interior page's rightmost-child becomes the promoted cell's left-child. The new interior page's rightmost-child becomes what the old page's rightmost-child previously was.
6. Insert the promoted cell into the grandparent (recurse if grandparent overflows).
7. If no grandparent (the interior page was the root): create a new root as in leaf-split step 6.

### Cell-byte budget for split decisions

For a page with `page_size` bytes (typically 4096), the cell content area usable budget is:
- Leaf (0x0a): `page_size - 8` (header) - `2 × cell_count` (pointer array) bytes of cell content.
- Interior (0x02): `page_size - 12` (header, including rightmost-child 4 bytes) - `2 × cell_count` (pointers) bytes of cell content.

A generator is free to pick any split point that leaves both resulting pages under their usable budget post-split. A simple median-count split is sufficient for fixture correctness; a byte-balanced split is a perf-tuning improvement.

### Depth limit (soft)

There is no hard depth limit baked into the file format — a balanced index tree of depth `d` holds roughly `(cells-per-interior)^(d-1) × cells-per-leaf` rows. For page size 4096 and typical cell sizes, depth 2 handles 10s of thousands of rows, depth 3 handles millions, depth 4+ handles billions. Generators SHOULD support arbitrary depth; tests exercise up to depth 2 (a single interior level above leaves).

### Bidirectional compatibility contract (Phase 9d)

- **leap-written DBs with split indexes are readable by mainline SQLite:** mainline reads our 0x02 + 0x0a pages as valid interior/leaf index pages and descends correctly.
- **mainline-written DBs with split indexes are readable by leap:** our reader handles the standard 0x02 layout.
- Any extension beyond the standard layout (e.g. freeblock handling, fragmentation-reclaim) is a latent divergence risk — generators MUST NOT introduce layout variants not described in this section.
