# Phase 3 planning — on-disk file format

Phase 3's goal: persistent database files that are **bidirectionally compatible** with mainline SQLite (mainline can read our files; we can read mainline's files). This is the largest leap yet — every part of the stack that touches data changes shape.

## Source of truth

- `https://www.sqlite.org/fileformat2.html` — published SQLite file-format specification. Allowed input per CLAUDE.md (published spec, not implementation).
- NOT allowed: mainline SQLite source, Turso, rusqlite, sql.js.

## Scope sub-phasing proposal

Phase 3 is too big to do in one shot. Proposed splits:

### Phase 3a — Persistence foundation (minimal single-page tables)

**Goals:**
- Open, read, write a `.db` file with SQLite-compatible 100-byte header.
- Page 1 = `sqlite_schema` table (B-tree leaf, type `0x0d`).
- Each user table has a root page (initially a single leaf page — no splits).
- INSERT/UPDATE/DELETE/SELECT operate on the table's root page.
- If a row doesn't fit on the current page → raise a new named error (`STORAGE_PAGE_FULL` or similar). No overflow pages yet.
- No freelist yet.
- No crash safety yet (writes go directly to disk; crash mid-write = corrupted file).
- **Test commitment:** mainline `sqlite3 our-file.db ".dump"` produces valid SQL; our engine reads files produced by mainline's `CREATE TABLE` + `INSERT` (single-page).

**New primitives needed:**
- `schema/page.schema.json` — abstract page shape (page type, cell count, cell content area offset, cells list).
- `schema/record.schema.json` — abstract record shape (header-size varint, serial types, column bodies).
- `schema/varint.*` — varint encoding/decoding, target-defined implementation.
- New error names: `STORAGE_PAGE_FULL`, `STORAGE_FILE_IO`, `STORAGE_CORRUPT_HEADER`, `STORAGE_CORRUPT_PAGE`.
- Expanded storage API: `open_database(path)`, `close_database(handle)`, `flush(handle)`.

**Affected parts:**
- **storage** — complete rewrite from in-memory list to page-backed. Biggest change.
- **vdbe** — cursor ops (Rewind/Next/Column) redirect to page-backed storage. Small change if the storage cursor abstraction is stable.
- **schema** — new page + record + varint schemas.
- **tokenizer / parser / compiler** — unchanged.
- **executor** — unchanged.

### Phase 3b — Multi-page tables (B-tree interior nodes, overflow)

- Interior pages (`0x05` for table, `0x02` for index).
- Leaf-page splits when full.
- Overflow pages for rows that exceed the per-page payload threshold (formula in file-format spec).
- Row count no longer bounded by page size.

### Phase 3c — Freelist + page reuse

- Freelist trunk + leaf pages.
- DELETE now returns pages to freelist when leaves become empty.
- INSERT prefers freelist over file extension.

### Phase 3d — Rollback journal (crash safety)

- `-journal` sidecar file.
- Before modifying a page, write the original to the journal.
- On recovery: replay journal to undo partial commits.
- Atomic commit via journal delete.

### Phase 3e — Full round-trip validation

- Large fixture set: create databases with mainline, open with ours, and vice versa.
- Multiple tables, mixed INSERT / UPDATE / DELETE sequences.
- All 2a, 2b, 2c-* fixtures still pass via the new on-disk backend (set a pragma or use on-disk storage by default).

## Key technical decisions to flag for Stan

1. **In-memory vs on-disk — are they co-resident or does on-disk replace in-memory?** The cleanest path is: on-disk is the ONLY storage starting Phase 3a; the in-memory model retires. Alternative: `:memory:`-style switch to keep tests fast. **Recommendation:** retire in-memory; all tests use on-disk (files can go in `/tmp` per test). Simpler, fewer paths to maintain.

2. **Little-endian vs big-endian internal representation.** SQLite's on-disk format is big-endian. Our internal register values are whatever the host CPU does (little-endian on aarch64 Mac, x86_64 Linux). We encode on write, decode on read. No choice.

3. **Page size.** SQLite defaults to 4096 bytes since 3.12.0. We'll default to 4096 for new databases, and read whatever the header says on existing files. Minimum 512; we should support all power-of-2 sizes up to 65536.

4. **Rowid semantics.** SQLite's table-B-tree rowids are 64-bit signed integers assigned at INSERT time (auto-increment unless `INTEGER PRIMARY KEY` column is present). Our Phase 2a-2c model used implicit "insertion index". In Phase 3 we need rowids for B-tree cells. **Recommendation:** auto-assign rowids starting at 1, increment by 1 per INSERT, skip over deleted rowids (matching SQLite's default behavior). `INTEGER PRIMARY KEY` column as rowid alias is a later feature.

5. **Record serial types for INTEGER / TEXT.** Our Phase 2a type system is strict INTEGER / TEXT / NULL. SQLite's serial types cover way more (6 integer widths, 2 constant-int shortcuts, float, blob). Minimal mapping: INTEGER → serial type 1/2/3/4/5/6 depending on value width (use smallest that fits); TEXT → serial type ≥13 odd; NULL → serial type 0. We don't emit BLOB or FLOAT in Phase 3; we should accept them on read (as something — opaque or error). **Recommendation:** on read, BLOB / FLOAT fields in user tables raise a new error `STORAGE_UNSUPPORTED_TYPE`. We won't write them.

6. **Atomicity unit.** Without a journal (3a through 3c), a single VDBE program could leave the file in a partial state on crash. Phase 3d adds rollback. For Phase 3a, mid-crash corruption is accepted (tests are non-crashing).

## Rough LOC estimate

- spec delta: +600–1000 lines (page format, record format, varint, file layout, error surface)
- schema delta: +200 lines
- parts delta: +300 lines (mostly storage master.md)
- tests delta: +500 lines per sub-phase
- generated code delta per language: +1500–2500 lines (storage rewrite, page codec, varint codec)

Phase 3a alone roughly doubles the project's generated-code footprint.

## Recommendation for autonomous run

Phase 3a is probably the **natural stopping point** for autonomous work. It introduces:

1. A genuinely new architectural pattern (page-backed storage) that has cross-language idiom implications (how do C and Rust each handle binary file I/O + buffer management?).
2. A decision point on in-memory retirement (see #1 above).
3. Potential spec ambiguities around edge cases (partial-row writes, encoding edge cases, header field meaning in degenerate states).

These are the kind of design calls Stan would want input on before committing. Drafting a full Phase 3a spec autonomously is possible, but the risk of having to unwind decisions after Stan returns is real.

**Proposed stopping point:** after Phase 2c-3 is green on both languages, leave src-c/src-rust in a good state, leave this plan document, and stop. Stan reviews this plan on return and directs Phase 3.

If Stan indicated "go further still," we can attempt Phase 3a — but with the understanding that some design calls may get revisited.
