---
name: fileformat-write
kind: inner
shapes: ./shapes.json
emits:
  python: { path: src-python/fileformat_write_runner.py }
  rust:   { path: src-rust/examples/fileformat_write_runner.rs }
---

# File-format write (single-page append probe)

Minimal probe of the SQLite on-disk **write** format. Reads an
existing mainline-compatible `.db` with one table on one page,
appends one row, rewrites the page, and writes the file back
atomically. The resulting `.db` MUST be readable by the mainline
`sqlite3` CLI **and** by our existing `fileformat_read_runner`.

This is the write analog of `fileformat-read`. Scope is deliberately
narrow: no page splits, no overflow, no indexes, no WAL. The proof
target is single-page append — the structural unknown of whether
the shape grammar can carry the write path cleanly.

## Reference fixture

Start from the same tiny fixture as fileformat-read:

```sql
CREATE TABLE t(id INTEGER PRIMARY KEY, name TEXT, age INTEGER);
INSERT INTO t VALUES (1, 'alice', 30);
```

Probe: append `(2, 'bob', 42)` via `insert_row(path, "t", [Null,
Text('bob'), Integer(42)])`. (The id column is NULL in the values
list because it's INTEGER PRIMARY KEY — hoisted to the rowid at
encode time.) Expected post-state:

```
sqlite3 out.db "SELECT * FROM t"
→ 1|alice|30
→ 2|bob|42
```

And our reader must produce 2 rows instead of 1.

## Declared shapes (in `shapes.json`)

- `WriteError { message }` — single failure channel.
- `WriteOk { new_change_counter, assigned_rowid, bytes_written }`.
- `insert_row(db_path, table_name, values) -> result<WriteOk, WriteError>`.

The write path reuses the READ shapes (DbHeader, PageHeader, serial
types, cell pointer array, varint) — those are defined in
`parts/storage/parts/fileformat-read/shapes.json` and MUST be
imported rather than redeclared. If the emission needs to DECODE
existing state before appending, it uses the read decoders;
ENCODE mirrors the decoders byte-for-byte.

## Write algorithm (single-page append)

```
insert_row(db_path, table_name, values):
    # 1. Read full file into memory
    bytes = read_file(db_path)
    header = decode_db_header(bytes[0:100])
    page_size = header.page_size

    # 2. Find root page of table_name from sqlite_master (page 1)
    page1 = bytes[0:page_size]
    root_page = lookup_rootpage(page1, table_name)
    # 1-based → file offset
    page_offset = (root_page - 1) * page_size
    page = bytes[page_offset : page_offset + page_size]

    # 3. Decode existing page header + cells
    ph = decode_page_header(page, is_page_one=False)
    require ph.page_type == 0x0D  # leaf table; no split in probe
    ptr_array_end = 8 + ph.cell_count * 2    # 8 = leaf header size
    cells = decode_cells(page, ph)           # list of (rowid, values)

    # 4. Assign new rowid
    max_rowid = max((c.rowid for c in cells), default=0)
    new_rowid = max_rowid + 1

    # 5. Encode new cell
    new_cell = encode_cell(new_rowid, values)
    # Cell layout (leaf table): payload_length_varint +
    #   rowid_varint + record_header + record_body.
    new_cell_len = len(new_cell)

    # 6. Check free space
    free_start = ptr_array_end
    free_end   = ph.cell_content_offset
    free_bytes = free_end - free_start
    required   = new_cell_len + 2   # new cell + new pointer entry
    if required > free_bytes:
        return Err(WriteError("page full — split deferred"))

    # 7. Place cell at (cell_content_offset - new_cell_len)
    new_content_offset = ph.cell_content_offset - new_cell_len
    page[new_content_offset : new_content_offset + new_cell_len] = new_cell

    # 8. Append pointer
    # Cell pointers are stored in reverse order of rowid, but for
    # a probe we append at the end — mainline sqlite's cell order
    # is a tree-order invariant, not a requirement of the file
    # format; the reader iterates by pointer index, so any order
    # that keeps pointers pointing at valid cells is legal.
    ptr_offset = 8 + ph.cell_count * 2
    write_u16_be(page, ptr_offset, new_content_offset)

    # 9. Update page header in place
    write_u16_be(page, 3, ph.cell_count + 1)            # cell_count
    write_u16_be(page, 5, new_content_offset)           # cell_content_offset

    # 10. Splice page back into bytes
    bytes[page_offset : page_offset + page_size] = page

    # 11. Bump DbHeader.change_counter
    new_counter = header.change_counter + 1
    write_u32_be(bytes, 24, new_counter)                # change_counter
    write_u32_be(bytes, 96, new_counter)                # version_valid_for

    # 12. Atomic write: write to tmp, fsync, rename
    tmp = db_path + ".tmp"
    write_file(tmp, bytes)
    fsync(tmp)
    rename(tmp, db_path)

    return Ok(WriteOk {
        new_change_counter: new_counter,
        assigned_rowid:     new_rowid,
        bytes_written:      len(bytes),
    })
```

## Encode cell (leaf table)

```
encode_cell(rowid, values):
    # 1. Build record header + body
    body = []
    types = []  # serial type varints
    for v in values:
        match v:
            Null       -> types.append(0)
            Integer(n) -> pick narrowest of {1,2,3,4,6,8}; append
                          signed big-endian bytes of that width;
                          special-case n == 0 → type 8; n == 1 → type 9
            Real(f)    -> types.append(7); append f64_be
            Text(s)    -> b = utf8(s); types.append(13 + 2*len(b));
                          body.append(b)
            Blob(b)    -> types.append(12 + 2*len(b)); body.append(b)

    types_bytes = concat(varint_be_encode(t) for t in types)
    header_len  = len(types_bytes) + varint_width(len(types_bytes))
                  # varint_width depends on header_len itself;
                  # iterate twice if the width changes (SQLite trick)
    header      = varint_be_encode(header_len) + types_bytes
    body_bytes  = concat(body)
    payload     = header + body_bytes

    cell = varint_be_encode(len(payload)) +
           varint_be_encode(rowid) +
           payload
    return cell
```

## Integer serial-type picker

Values -> narrowest fitting serial type:

| Range                                     | Serial type | Bytes |
|-------------------------------------------|-------------|-------|
| `n == 0`                                  | 8           | 0     |
| `n == 1`                                  | 9           | 0     |
| `-128 ≤ n ≤ 127` (and not 0/1)            | 1           | 1     |
| `-32768 ≤ n ≤ 32767`                      | 2           | 2     |
| `-8388608 ≤ n ≤ 8388607`                  | 3           | 3     |
| `-2^31 ≤ n ≤ 2^31 - 1`                    | 4           | 4     |
| `-2^47 ≤ n ≤ 2^47 - 1`                    | 5           | 6     |
| otherwise                                 | 6           | 8     |

## Varint encode

Mirror the decode table (parts/targets/<lang>/mapping.md §"Storage
codecs"). 1-byte encoding for values ≤ 0x7f. 2-byte: ≤ 0x3fff. Up to
9 bytes for full i64. Probe can emit the 1- and 2-byte cases only
if the fixture's values fit; MUST fall back to full encoder for
larger values.

## Atomic write discipline

1. Write entire file to `{db_path}.tmp`
2. `fsync(tmp)` — not just flush; commit to disk
3. `rename(tmp, db_path)` — POSIX atomic

If any step fails, leave original file untouched and return
`WriteError`. Do NOT write partially-formed bytes to the original
path.

## Correctness pins

1. **Byte-identical header framing** — DbHeader field offsets match
   the read spec. `change_counter` (offset 24) and
   `version_valid_for` (offset 96) both bump by 1 per insert.
2. **Page type preserved** — if input page type is `0x0D` (leaf
   table), output is `0x0D`. Do not rewrite to a different type.
3. **Cell count == pointer count == decoded cell list length** —
   after write, `cell_count` equals the number of pointers AND the
   number of cells decodable by re-reading.
4. **cell_content_offset is the MINIMUM pointer value** — new cell
   is placed at the lowest offset; all existing cells remain
   untouched.
5. **Page-full returns error, not corruption** — when
   `required > free_bytes`, return `WriteError("page full — split
   deferred")` without modifying the file on disk.
6. **sqlite3 CLI compatibility** — after write, running
   `sqlite3 <path> "SELECT * FROM t"` prints every row the reader
   saw PLUS the newly-inserted row, in rowid order. Tested via the
   runner.
7. **Fileformat-read round-trip** — after write, the existing
   `fileformat_read_runner <path>` prints `rows[N]` for the appended
   row with matching rowid and values.
8. **Atomic write** — if writing to `.tmp` fails or is interrupted,
   the original file is bit-identical to what it was before. Runner
   test: delete `.tmp`, verify original unchanged.
9. **INTEGER PRIMARY KEY hoist** — when the table schema has an
   INTEGER PRIMARY KEY column, the caller passes `Null` in that
   position of `values`; the encoder hoists the auto-assigned
   rowid to that column and serializes it as serial-type 0 (NULL)
   in the record body. This matches SQLite's storage convention.
10. **No invented helpers** — per §Generation scope. Runner has
    `leaplint: runner` marker.

## Runner contract

```
<runner> <db_path>
```

1. Reads `db_path` (must already have a `t` table per the fixture).
2. Calls `insert_row(db_path, "t", [Null, Text("bob"), Integer(42)])`.
3. On success, prints the WriteOk as JSON to stdout:
   ```json
   {"new_change_counter":N,"assigned_rowid":M,"bytes_written":K}
   ```
4. On failure, prints `{"error":"<message>"}` to stderr and exits 1.

The runner is standalone; it inlines the write algorithm rather than
importing a library module. Matches fileformat-read convention.

## Test harness

`tests/fixtures/tiny.db` is the input. The probe's pass criterion:

```bash
cp tests/fixtures/tiny.db /tmp/probe.db
<runner> /tmp/probe.db   # writes {"assigned_rowid":2,...}
sqlite3 /tmp/probe.db "SELECT * FROM t"
# expected: 1|alice|30
#           2|bob|42
python3 src-python/fileformat_read_runner.py /tmp/probe.db
# expected: two rows in the JSON output
```

Cross-target: Rust runner writes `/tmp/rust_probe.db`, Python runner
writes `/tmp/py_probe.db`. Both final files must be byte-identical
(same change_counter bump, same cell encoding, same rowid).

## Regeneration envelope

- Target line budget: **~250–350 lines per runner**. Larger than
  fileformat-read because the encoder is bidirectional work.
- No external deps beyond stdlib.
- Standalone runner files, not library modules.

## Outcome criteria

- Both runners emit structurally-identical JSON.
- After both runs, `sqlite3` CLI reads all rows correctly.
- The pair of output files are byte-identical (proves the two
  encoders agree on every bit they produce).
