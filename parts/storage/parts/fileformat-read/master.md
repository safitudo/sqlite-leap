---
name: fileformat-read
kind: inner
shapes: ./shapes.json
emits:
  python: { path: src-python/fileformat_read_runner.py }
  rust:   { path: src-rust/examples/fileformat_read_runner.rs }
---

# File-format read (single-table, single-page)

Minimal probe of the SQLite on-disk format. Reads a mainline
SQLite-generated `.db` file with one table, one row, one page per
table. The probe verifies bidirectional format compatibility from
the **read** side — the write side comes later.

The shape grammar now supports all four framings this format needs:
fixed-width records, conditional fields (`when` gate on a sibling),
lists sized by a sibling field (`list_sized_by`), and opaque named
codecs for self-describing framings (SQLite's serial-type sequence).
Schema extensions landed in 2026-04-24 (Phase F); see
`schema/shape.schema.json` for the grammar.

## Reference corpus

`parts/eq-harness/corpus/fileformat/tiny.db.json` names the
expected read of the fixture at `tests/fixtures/tiny.db`
(regenerable via `sqlite3 tiny.db "CREATE TABLE t(id INTEGER
PRIMARY KEY, name TEXT, age INTEGER); INSERT INTO t VALUES (1,
'alice', 30);"`). Expected output:

```
header.page_size       = 4096
header.text_encoding   = 1 (UTF-8)
schema.rootpage['t']   = 2
row[1]                 = (NULL, "alice", 30)
```

## Declared shapes (in `shapes.json`)

### `DbHeader`

The 100-byte database header at file offset 0. Fixed layout
per sqlite.org/fileformat2.html. Every field has a fixed offset
and fixed width, so this fits the record grammar.

- `magic: blob[16]` — `"SQLite format 3\0"`.
- `page_size: u16_be` — page size in bytes (power of two; the
  special value `0x0001` means 65536).
- `write_version: u8`
- `read_version: u8`
- `reserved_space: u8` — unused bytes at the end of each page.
- `max_embed_frac: u8` — must be 64.
- `min_embed_frac: u8` — must be 32.
- `leaf_frac: u8` — must be 32.
- `change_counter: u32_be`
- `db_size_in_pages: u32_be` — in-header page count.
- `first_freelist_trunk: u32_be`
- `freelist_page_count: u32_be`
- `schema_cookie: u32_be`
- `schema_format: u32_be` — 1, 2, 3, or 4.
- `default_page_cache: u32_be`
- `largest_root_btree: u32_be` — autovacuum / incremental vacuum.
- `text_encoding: u32_be` — 1=UTF-8, 2=UTF-16le, 3=UTF-16be.
- `user_version: u32_be`
- `incremental_vacuum: u32_be`
- `application_id: u32_be`
- `reserved: blob[20]` — must be all zeros.
- `version_valid_for: u32_be`
- `sqlite_version: u32_be` — value of SQLITE_VERSION_NUMBER.

**Integrity checks:**
- `magic == "SQLite format 3\0"`
- `max_embed_frac == 64 && min_embed_frac == 32 && leaf_frac == 32`
- `reserved == zeros`

### `PageHeader`

B-tree page header. For interior pages, 12 bytes; for leaf pages,
8 bytes. On page 1 the header starts at offset 100 (after the
database header); on every other page it starts at offset 0 of
the page.

- `page_type: u8` — 0x02 = interior index, 0x05 = interior table,
  0x0A = leaf index, 0x0D = leaf table.
- `first_freeblock: u16_be` — 0 if none.
- `cell_count: u16_be`
- `cell_content_offset: u16_be` — offset within page; value 0
  means 65536.
- `fragmented_free_bytes: u8`
- `right_child: u32_be` — page number of the rightmost child.
  Declared in `shapes.json` with a `when` gate: present iff
  `page_type ∈ {0x02, 0x05}`. Each target emits this as a
  nullable / `Option<u32>` decoded conditionally.

## Grammar pieces now in shape.schema.json

Each framing below now has a declarative form. Per-target mapping
files supply the concrete decoder for opaque pieces (`varint_be`,
`codec`). Targets that want to verify their implementation can run
the equivalence harness against `tests/fixtures/tiny.db`.

### Varints — `varint_be` primitive

SQLite's 1–9 byte big-endian variable-length integer (rowids,
record header length, serial types, cell payload length) is now
a first-class primitive TypeRef. Each target's `mapping.md`
supplies the decoder (returns `(i64, bytes_consumed)`).

### Record header / serial types — `codec` TypeRef

The cell body's `(record_header_length_varint, serial_type_1_varint,
..., serial_type_N_varint, body_bytes)` layout is not shape-grammar
decomposable — each serial type tag encodes both discriminator and
length:

- 0 → NULL, 0 bytes
- 1 → i8
- 2 → i16_be
- 3 → i24_be
- 4 → i32_be
- 5 → i48_be
- 6 → i64_be
- 7 → f64_be
- 8 → Integer(0)
- 9 → Integer(1)
- 10, 11 → internal (reserved)
- N ≥ 12 and even → Blob of length (N-12)/2
- N ≥ 13 and odd  → Text of length (N-13)/2

Declared in `shapes.json` as `{ "codec": { "name":
"SqliteSerialTypeSequence", "decodes": { "list": "Value" } } }`.
Each target's mapping supplies the named decoder; the schema
carries only the name and the conceptual output type.

### Cell pointer array — `list_sized_by`

A page has `cell_count` u16_be pointers immediately after the
page header, each a byte-offset into the page.
`{ "list_sized_by": { "elem": "u16_be", "length_field":
"cell_count" } }` expresses "list whose length is this sibling
field." The schema cannot statically verify the sibling exists and
is an integer; targets check at emission time.

### Interior-page `right_child` — `when` gate

Conditional field, present iff `page_type ∈ {0x02, 0x05}`. Declared
inline inside the `PageHeader` record as `{ "type": "u32_be",
"when": { "field": "page_type", "in": [2, 5] } }`. Targets emit
this as `Option<u32>` / nullable plus a decode-time predicate.

## Reader contract

Per-target reader:

1. Opens the database file.
2. Reads and validates the 100-byte `DbHeader`.
3. Page 1: parses the page header (fixed shape) + sqlite_master
   row (varint + record header — hand-decoded for now).
4. Resolves the root page of table `t` from sqlite_master.
5. Reads that page's header + the single cell.
6. Decodes the row into `(rowid, [Value, ...])`.
7. Emits one row per table row, same format as the equivalence
   harness's `Value` encoding.

Readers are located at:

| Target | Path                                        |
|--------|---------------------------------------------|
| Python | `src-python/fileformat_read_runner.py`      |
| Rust   | `src-rust/examples/fileformat_read_runner.rs` |

Both consume `tests/fixtures/tiny.db` and emit the same JSON row
shape. The meta-runner `parts/eq-harness/eqcheck.py` is NOT used
for this probe directly because the corpus format (JSON describing
a VDBE program) doesn't apply; this probe uses its own tiny
harness `parts/storage/parts/fileformat-read/eqcheck.py`.

## Output contract (byte-identical across targets)

The runner's **sole stdout** is one line of JSON with this exact shape:

```json
{"header":{"page_size":4096,"text_encoding":1},"rows":[{"cols":[{"t":"Null"},{"t":"Text","v":"alice"},{"t":"Integer","v":30}],"rowid":1}],"schema_rootpage_t":2}
```

Key ordering MUST match (use an ordered dict / linked JSON writer / etc).
- Top keys, in order: `header`, `rows`, `schema_rootpage_t`.
- `header` keys in order: `page_size`, `text_encoding`.
- Each row object keys in order: `cols`, `rowid`.
- Each cell object keys in order: `t`, `v` (with `t` always present,
  `v` present unless `t == "Null"`).
- `cols` order is the column order as stored on-disk (for `tiny.db`
  that means `[id, name, age]` → in the serial-type sequence the id
  column serializes as NULL because INTEGER PRIMARY KEY is hoisted
  to the rowid, so cols emits `[{t:"Null"}, {t:"Text",v:"alice"},
  {t:"Integer",v:30}]`).

CLI: `<runner> tests/fixtures/tiny.db` → writes the JSON to stdout,
exits 0 on success, exits 1 on any integrity-check failure (bad
magic, corrupt reserved bytes, wrong max_embed_frac, etc.).

## Correctness pins

Numbered pins. Every numbered pin below MUST be satisfied by the
emission. The subagent MUST report per-pin satisfaction.

1. **DbHeader decode** — read 100 bytes at file offset 0, parse
   every field declared in `shapes.json::DbHeader` (big-endian per
   the `_be` suffix), validate the three integrity invariants
   (magic, embed_frac triple, reserved zeros). On any violation:
   exit 1 with a diagnostic line on stderr.
2. **PageHeader conditional decode** — when reading a page of type
   `0x02` or `0x05`, the `right_child` u32_be field is read at
   offset 8 of the page header (after `fragmented_free_bytes`). On
   leaf page types (`0x0A`, `0x0D`), the right_child is absent and
   the header is only 8 bytes. The emission MUST realize this as a
   nullable / `Option` value, not a constant read.
3. **Cell-pointer-array length binding** — after a PageHeader's
   fixed bytes, the cell pointer array has exactly `cell_count`
   u16_be entries. The emission MUST bind the loop count to the
   decoded `cell_count`, not to a hard-coded value.
4. **varint_be decode** — implement the SQLite 1–9 byte
   big-endian varint per `parts/targets/<lang>/mapping.md` §
   "Storage codecs". The decoder returns `(i64 value, usize
   bytes_consumed)`. Used for payload_length, rowid, record header
   length, and each serial type in the record header.
5. **SqliteSerialTypeSequence codec** — implement the serial-type
   table per `parts/targets/<lang>/mapping.md` § "Storage codecs".
   The codec consumes `(record_header_length, serial_type_1, ...,
   serial_type_N)` varints, then reads N body slots using the
   widths implied by each serial type. Serial types 0 → Null, 8 →
   Integer(0), 9 → Integer(1); 1..6 → signed big-endian integers
   of width {1,2,3,4,6,8}; 7 → f64_be; N≥12 even → Blob of length
   (N-12)/2; N≥13 odd → Text of length (N-13)/2.
6. **sqlite_master lookup** — the runner reads page 1 (file offset
   0, which is `page_size` bytes long; the PageHeader on page 1
   starts at offset 100 after the DbHeader, not offset 0). For
   each sqlite_master row, the runner extracts the `tbl_name`
   (column 2) and `rootpage` (column 3). It finds the row where
   `tbl_name == "t"` and uses that rootpage number as the table's
   root page index (1-based; page N is at file offset `(N-1) *
   page_size`).
7. **Output stream format** — emit **exactly one line** of JSON
   to stdout, matching the §"Output contract" shape with the
   exact key ordering specified. No trailing newline control
   beyond a final `\n`. No pretty-printing.
8. **No other I/O on stdout** — debug diagnostics go to stderr
   only. The single JSON line is the sole stdout content.
9. **CLI contract** — argv[1] is the path to a `.db` file. Exit
   0 on success, 1 on integrity failure or parse error.
10. **Generation scope** — per
    `spec/part-conventions.spec.md` §"Generation scope": no
    inline tests, no unused helpers beyond what the decoders need,
    no "# TODO" markers. The runner ITSELF has an authorized entry
    point (`main` / `__main__` guard) because it's a runner, not
    library code; emit the marker `leaplint: runner` within the
    first 8 lines of the file to opt into the runner exception
    (see §"Runner exception" in `spec/part-conventions.spec.md`).
    All other §Generation-scope rules still apply.

## Regeneration envelope

- Target line budget: **150–250 lines per runner**. The original
  hand-written emissions are 193 (Python) and 195 (Rust).
- No external dependencies beyond the target's stdlib + declared
  dev-deps (`serde_json` + `base64` for Rust runners, per
  `parts/targets/rust/mapping.md` §"Toolchain pin"). Python must
  use only stdlib.
- Runners are standalone — they inline the decoders rather than
  importing a library module. That keeps the probe self-contained;
  refactoring into a library is a later wave.

## Outcome criteria

- Both targets read the fixture without error.
- Both targets emit the exact single-line JSON above — **byte for
  byte identical**.
- The probe passes when `diff <(py_runner tiny.db) <(rust_runner
  tiny.db)` produces zero output.
