---
name: fileformat-write
kind: inner
shapes: ./shapes.json
emits:
  python: { path: src-python/fileformat_write_runner.py }
  rust:   { path: src-rust/examples/fileformat_write_runner.rs }
---

## Pin 19b note: codec extraction

The byte-encoding helpers (`encode_cell`, `build_leaf_page`,
`build_interior_table_page`, `encode_varint_be`, `serial_type_for`,
`usable_size`) are owned by `/parts/storage/parts/page-codec/`. This
part imports them via `inherits:` and uses them inside the page-write
orchestration (insert/split/root-collapse). After Pin 19b's sibling
regen lands, the helper definitions in this file are stubs that call
through to `page-codec`; until then, this file's helper bodies remain
the canonical source.

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
        # v2: split path. See §Split algorithm below.
        return split_and_insert(bytes, header, root_page, table_name,
                                ph, cells, new_rowid, values)

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
        did_split:          false,
    })
```

## Split algorithm (v2: leaf split + root-split)

The probe handles all four split cases (append-side only):

| Case                                                 | Probe support |
|------------------------------------------------------|---------------|
| Leaf split, parent is interior with room             | YES           |
| Root-split (leaf root → interior root + 2 leaves)    | YES           |
| Non-root leaf split (parent is existing interior)    | YES           |
| Recursive parent split (parent interior is also full)| YES           |

The trigger is `required > free_bytes` inside the leaf append branch.
At that point the caller has already decoded `cells` (existing rowid
+ values) and computed `new_rowid`. We choose the simplest split
policy: **append-side split** — keep all existing cells on the old
leaf, put only the new cell on the new leaf. This is suboptimal for
random insert workloads but is exactly correct for the rowid-ascending
INSERT pattern the probe exercises (INTEGER PRIMARY KEY auto-rowid),
and it keeps the spec small. Mainline-SQLite reads the result
identically regardless of how cells are distributed across siblings,
because the b-tree invariant is "rowids in left subtree < divider <
rowids in right subtree" — and append-side meets that.

```
split_and_insert(bytes, header, root_page, table_name, ph_old, cells_old,
                 new_rowid, new_values):
    # 1. Determine if root_page IS the table's root.
    # In the probe, root_page comes from sqlite_master and is always the
    # root, so root-split applies whenever parent has not been recorded
    # (we have no parent stack — the probe walks one level).
    # The probe-scope rule: if root_page is the b-tree root AND it's a
    # leaf (page_type == 0x0D), this is the root-split case.
    if ph_old.page_type == 0x0D:
        return root_split(bytes, header, root_page, ph_old, cells_old,
                          new_rowid, new_values)
    else:
        # ph_old is interior: the "page full" trigger reached us from a
        # recursive-split descent below; dispatch to interior_split.
        return interior_split(bytes, header, root_page, ph_old,
                              interior_cells_old, new_divider, parent_stack)

root_split(bytes, header, root_page_no, ph_old, cells_old, new_rowid, new_values):
    page_size  = header.page_size
    # 2. Allocate two new leaf pages at the file tail.
    old_db_size = header.database_size  # u32 at offset 28
    left_page_no  = old_db_size + 1     # 1-based
    right_page_no = old_db_size + 2
    # Grow the byte buffer.
    bytes.extend(zeros(2 * page_size))
    new_db_size = old_db_size + 2

    # 3. Build the LEFT leaf: all existing cells, no new cell.
    #    Build the RIGHT leaf: only the new (rowid, values) cell.
    new_cell = encode_cell(new_rowid, new_values)
    left_page  = build_leaf_page(page_size, cells_old, ph_old.is_page_one_alias)
    right_page = build_leaf_page(page_size, [(new_rowid, new_values)], false)

    # 4. Splice them into the byte buffer at left/right offsets.
    bytes[(left_page_no  - 1) * page_size : left_page_no  * page_size] = left_page
    bytes[(right_page_no - 1) * page_size : right_page_no * page_size] = right_page

    # 5. Convert the OLD root page in place to an interior table page.
    #    The interior page contains exactly one cell:
    #      child_page = left_page_no, key = max_rowid_in_left
    #    and right_child = right_page_no.
    max_left_rowid = cells_old[-1].rowid   # cells_old sorted ascending by rowid
    new_root = build_interior_table_page(
        page_size,
        is_page_one    = (root_page_no == 1),
        right_child_pn = right_page_no,
        cells          = [InteriorCell { child: left_page_no, key: max_left_rowid }]
    )
    bytes[(root_page_no - 1) * page_size : root_page_no * page_size] = new_root

    # 6. Update DbHeader.database_size and change_counter.
    new_counter = header.change_counter + 1
    write_u32_be(bytes, 24, new_counter)         # change_counter
    write_u32_be(bytes, 28, new_db_size)         # database_size (page count)
    write_u32_be(bytes, 96, new_counter)         # version_valid_for

    # 7. Atomic write (same as single-page path).
    write_atomic(bytes)

    return Ok(WriteOk {
        new_change_counter: new_counter,
        assigned_rowid:     new_rowid,
        bytes_written:      len(bytes),
        did_split:          true,
    })
```

### Descent: find the insertion leaf (append-side)

For any tree whose root is an interior page, the insert path walks
down to the rightmost leaf (since append-side insert always targets
`new_rowid > all existing rowids`, which means the last child in key
order). The descent records a **parent stack**: each entry is
`(page_no, page_header, slot_index)` where `slot_index` is the cell
index in that interior page that we descended through, or the
special marker `RIGHT_CHILD` if we followed the right-child pointer.

```
descend_to_append_leaf(bytes, header, root_page_no):
    stack = []
    cur_page_no = root_page_no
    loop:
        page  = page_slice(bytes, cur_page_no, header.page_size)
        ph    = decode_page_header(page, is_page_one=(cur_page_no == 1))
        if ph.page_type == 0x0D:   # leaf table
            return (stack, cur_page_no, ph, page)
        require ph.page_type == 0x05   # interior table
        # append-side: descend rightmost child
        stack.append(ParentFrame {
            page_no:     cur_page_no,
            header:      ph,
            slot:        RIGHT_CHILD,
        })
        cur_page_no = ph.right_child
```

### Non-root leaf split (parent is interior, parent has room)

Triggered when a leaf `L` at page `L_pn` is full, and its parent `P`
at page `P_pn` is an interior table page with enough free bytes to
host one more divider cell.

```
non_root_leaf_split(bytes, header, parent_stack, L_pn, ph_L, cells_old,
                    new_rowid, new_values):
    page_size  = header.page_size
    reserved   = header.reserved_space
    # 1. Allocate a new leaf at the file tail.
    old_db_size = effective_db_size(header, bytes, page_size)
    Lnew_pn = old_db_size + 1
    bytes.extend(zeros(page_size))
    new_db_size = old_db_size + 1

    # 2. Build the two leaves (append-side split):
    #    L keeps all old cells. Lnew holds only the new cell.
    L_page    = build_leaf_page(page_size, reserved, cells_old,    is_page_one=False)
    Lnew_page = build_leaf_page(page_size, reserved, [(new_rowid, new_values)],
                                is_page_one=False)
    splice_page(bytes, L_pn,    page_size, L_page)
    splice_page(bytes, Lnew_pn, page_size, Lnew_page)

    # 3. Update the parent P. The descent arrived at L via right-child
    #    (append-side). After split, L is no longer right-most; Lnew is.
    #    Insert a divider cell  { child: L_pn, key: max_rowid(L) }
    #    AT THE END of P's cell array (ascending-key order preserved,
    #    because max_rowid(L) > all previous divider keys on P).
    #    Set P.right_child = Lnew_pn.
    P_frame       = parent_stack.pop()
    P_pn          = P_frame.page_no
    ph_P          = decode_page_header(page_slice(bytes, P_pn, page_size),
                                       is_page_one=(P_pn == 1))
    P_cells_old   = decode_interior_cells(page_slice(bytes, P_pn, page_size), ph_P)
    new_divider   = InteriorCell { child: L_pn, key: cells_old[-1].rowid }

    # Space check on P.
    divider_bytes  = 4 + varint_width(new_divider.key)  # u32 child + varint key
    ptr_entry      = 2
    free_on_P      = (ph_P.cell_content_offset - reserved)
                     - (ph_P.header_size + ph_P.cell_count * 2)
    if divider_bytes + ptr_entry > free_on_P:
        # Parent itself is full — escalate to recursive_parent_split.
        return recursive_parent_split(bytes, header, parent_stack,
                                      P_pn, ph_P, P_cells_old,
                                      new_divider, Lnew_pn,
                                      new_rowid, assigned_rowid=new_rowid)

    P_cells_new   = P_cells_old + [new_divider]
    P_page_new    = build_interior_table_page(
                       page_size, reserved,
                       is_page_one    = (P_pn == 1),
                       right_child_pn = Lnew_pn,
                       cells          = P_cells_new)
    splice_page(bytes, P_pn, page_size, P_page_new)

    # 4. Bump DbHeader.database_size, change_counter, version_valid_for.
    new_counter = header.change_counter + 1
    write_u32_be(bytes, 24, new_counter)
    write_u32_be(bytes, 28, new_db_size)
    write_u32_be(bytes, 96, new_counter)

    write_atomic(bytes)
    return Ok(WriteOk { new_change_counter: new_counter,
                        assigned_rowid:     new_rowid,
                        bytes_written:      len(bytes),
                        did_split:          true })
```

### Recursive parent split

Triggered when inserting a divider into an interior page `P` would
overflow it. We split `P` the same way we split a leaf: append-side
(since divider keys are inserted in ascending order on the append
path). The new interior page `Pnew` receives the newly-introduced
divider + the new right-child pointer; `P` keeps all existing
dividers; the *previous* right-child of `P` becomes a trailing
divider on `P` whose key = the key of the divider that bumps it
(per SQLite file-format: keys on an interior page are the maxima of
their left subtrees, so the old right-child's key is the max rowid
of its subtree, i.e. the key of the new divider we were inserting).

Subtlety: to hand up a clean divider to the grandparent, the
recursive split MUST yield a single `grand_divider = InteriorCell {
child: P_pn, key: <max rowid in left-of-Pnew subtree> }` — see below.

```
recursive_parent_split(bytes, header, parent_stack,
                       P_pn, ph_P, P_cells_old,
                       incoming_divider,     # InteriorCell that couldn't fit on P
                       incoming_right_child, # new right-child at level below
                       assigned_rowid):
    page_size = header.page_size
    reserved  = header.reserved_space

    # Append-side policy — P stays UNCHANGED. Pnew is a fresh
    # rightmost interior with a single divider (the incoming one)
    # and right_child = incoming_right_child. Grandparent receives
    # a divider pointing to P with key = incoming_divider.key
    # (which equals the max rowid currently reachable through P,
    # because incoming_divider was produced by splitting P's former
    # rightmost leaf, whose max rowid is exactly that key).
    #
    # Why unchanged-P works: before the split, P.right_child
    # pointed at leaf L. L kept all its existing cells, so the
    # subtree rooted at P still covers the SAME rowid range it
    # did before. The NEW rowid now lives under Pnew. P's
    # right_child still resolves to L (unchanged), which is
    # correct because L is no longer the global rightmost leaf —
    # but it IS the rightmost leaf reachable through P.

    # Allocate Pnew at tail.
    old_db_size = effective_db_size(header, bytes, page_size)
    Pnew_pn     = old_db_size + 1
    bytes.extend(zeros(page_size))
    new_db_size = old_db_size + 1

    # Pnew carries NO divider cells; just right_child pointing at
    # the newly-introduced child at the level below. All existing
    # rowids remain reachable through P; only rowids above the old
    # max (i.e. newly-inserted ones) are reachable through Pnew.
    Pnew_page = build_interior_table_page(
        page_size, reserved,
        is_page_one    = False,
        right_child_pn = incoming_right_child,
        cells          = [])
    splice_page(bytes, Pnew_pn, page_size, Pnew_page)

    # Divider to hand up: routes rowids ≤ key into P, rest into Pnew.
    # key = max rowid currently reachable through P = incoming_divider.key
    # (which = max rowid of the leaf that previously was P's rightmost
    # descendant, unchanged after the leaf split since that leaf kept
    # all its cells).
    grand_divider = InteriorCell { child: P_pn, key: incoming_divider.key }

    if parent_stack.is_empty():
        # P was the root interior. We need to create a NEW root
        # interior at the old root page number. But P_pn IS the old
        # root page number — and we just wrote P's new contents there.
        # So instead we allocate another new page and move P to it,
        # then rewrite P_pn as the new root. Equivalently: allocate
        # a fresh page for the new root and re-point... but simpler:
        # because the root page number is stored in sqlite_master,
        # we cannot change it. Therefore: when P IS the root and P
        # would split, we must do a "root interior split":
        #   1. Copy P's new content onto a freshly allocated P_moved page.
        #   2. Rewrite the original root-page bytes as an interior with
        #      one cell { child: P_moved, key: grand_divider.key } and
        #      right_child = Pnew_pn.
        return root_interior_split(bytes, header, P_pn, P_page_new,
                                   Pnew_pn, grand_divider.key,
                                   new_db_size, assigned_rowid)

    # Else: propagate grand_divider up one level.
    GP_frame = parent_stack.pop()
    GP_pn    = GP_frame.page_no
    ph_GP    = decode_page_header(page_slice(bytes, GP_pn, page_size),
                                  is_page_one=(GP_pn == 1))
    GP_cells_old = decode_interior_cells(page_slice(bytes, GP_pn, page_size),
                                         ph_GP)
    return insert_divider_into_interior(bytes, header, parent_stack,
                                        GP_pn, ph_GP, GP_cells_old,
                                        grand_divider, Pnew_pn,  # Pnew becomes GP's new rightmost subtree
                                        assigned_rowid, new_db_size)
```

`insert_divider_into_interior` is the same space-check-then-append
path used inside non_root_leaf_split step 3, factored for reuse.

### Root interior split

When the root page is itself an interior page `P` and `P` is full:
mainline's schema records the ROOT PAGE NUMBER in sqlite_master; we
cannot renumber the root. Instead:

```
root_interior_split(bytes, header, root_pn, P_new_content,
                    Pnew_pn, divider_key, new_db_size, assigned_rowid):
    page_size = header.page_size
    reserved  = header.reserved_space

    # 1. Allocate a new page for the OLD P content; call it P_moved.
    old_db_size = new_db_size   # after Pnew was allocated
    P_moved_pn  = old_db_size + 1
    bytes.extend(zeros(page_size))
    new_db_size2 = old_db_size + 1

    splice_page(bytes, P_moved_pn, page_size, P_new_content)

    # 2. Rewrite root_pn as a fresh interior page:
    #      cells         = [ { child: P_moved_pn, key: divider_key } ]
    #      right_child   = Pnew_pn
    new_root = build_interior_table_page(
        page_size, reserved,
        is_page_one    = (root_pn == 1),
        right_child_pn = Pnew_pn,
        cells          = [InteriorCell { child: P_moved_pn, key: divider_key }])
    splice_page(bytes, root_pn, page_size, new_root)

    # 3. Bump DbHeader.
    new_counter = header.change_counter + 1
    write_u32_be(bytes, 24, new_counter)
    write_u32_be(bytes, 28, new_db_size2)
    write_u32_be(bytes, 96, new_counter)

    write_atomic(bytes)
    return Ok(WriteOk { new_change_counter: new_counter,
                        assigned_rowid:     assigned_rowid,
                        bytes_written:      len(bytes),
                        did_split:          true })
```

**Invariant** (root never renumbers): the original root page number
stored in sqlite_master remains the root. Every split either
extends the tree depth (root_interior_split) or leaves depth
unchanged (non-root splits).

### Correctness pins for non-root + recursive

**S11. Descent is deterministic for append-side.** Always follow
`right_child` on every interior hop, because the new rowid is
greater than every existing rowid. If the descent ever encounters a
non-leaf non-interior page type, surface a corruption error rather
than continuing.

**S12. Divider key after non-root leaf split** = max rowid on the
left leaf (the previously-rightmost leaf, which kept all its
existing cells). Mainline's b-tree invariant "rowid ≤ divider_key →
descend child; otherwise descend right_child" then routes the new
rowid to `right_child = Lnew_pn`. ✓

**S13. Parent right_child update** — after non-root leaf split,
parent's `right_child` points at `Lnew_pn` (the new rightmost
leaf). The OLD right_child becomes a regular divider cell.

**S14. Recursive split is append-side-only.** A new divider lands
at the END of the parent's cell array (keys are in ascending order
because we're inserting the largest rowid ever seen). If the
parent's cells don't appear sorted after insertion, we have violated
this invariant and must error.

**S15. Root page number preserved.** sqlite_master's
`rootpage` value for the table is never rewritten. root_split and
root_interior_split both keep the root at the same page number by
moving the OLD root content to a freshly-allocated tail page.

**S16. database_size bumps by** +1 per non-root leaf split, +2 per
recursive parent split (Pnew + P_moved when escalated through
root_interior_split), +2 per root_split (left + right leaves). The
file length always equals `database_size * page_size`.

### Usable size — the reserved-space byte

DbHeader at offset 20 holds `reserved_space: u8` (typically 0 for new
DBs but **12 for SQLite-CLI-created DBs by default**). Cells must NOT
extend into the trailing `reserved_space` bytes of any page. Define:

```
usable_size = page_size - reserved_space
```

Every place the spec says "page_size" as a cell-content boundary
should be read as `usable_size`. In particular: in `build_leaf_page`
and `build_interior_table_page`, the cell-packing cursor starts at
`usable_size`, not `page_size`. Failure mode if this is missed:
mainline `PRAGMA integrity_check` reports "free space corruption"
even though `SELECT *` returns correct data (read-side is forgiving;
integrity_check is not). Surfaced 2026-04-24 by Rust split agent.

### build_leaf_page

```
build_leaf_page(page_size, reserved_space, cells, is_page_one):
    usable = page_size - reserved_space
    # Leaf table page layout:
    #   [page-1 reserved 100 bytes for DbHeader if is_page_one]
    #   PageHeader (8 bytes for leaf):
    #     u8   page_type = 0x0D
    #     u16  first_freeblock = 0
    #     u16  cell_count
    #     u16  cell_content_offset (smallest pointer)
    #     u8   fragmented_free_bytes = 0
    #   cell pointer array: cell_count × u16_be
    #   ... free space (zero-filled) ...
    #   cells, packed from page_size downward
    page = zeros(page_size)
    header_off = 100 if is_page_one else 0
    # Place cells starting at page tail, lowest-rowid cell at lowest offset.
    cell_blobs = [encode_cell(c.rowid, c.values) for c in cells]
    cursor = usable           # NOT page_size — see §Usable size
    pointers = []
    for blob in cell_blobs:
        cursor -= len(blob)
        page[cursor : cursor + len(blob)] = blob
        pointers.append(cursor)
    # Header
    page[header_off + 0]  = 0x0D
    write_u16_be(page, header_off + 1, 0)               # first_freeblock
    write_u16_be(page, header_off + 3, len(cells))      # cell_count
    write_u16_be(page, header_off + 5, cursor)          # cell_content_offset
    page[header_off + 7]  = 0                           # fragmented_free_bytes
    # Pointer array
    ptr_off = header_off + 8
    for p in pointers:
        write_u16_be(page, ptr_off, p)
        ptr_off += 2
    return page
```

### build_interior_table_page

```
build_interior_table_page(page_size, reserved_space, is_page_one, right_child_pn, cells):
    usable = page_size - reserved_space
    # Interior table page layout:
    #   [page-1 reserved 100 bytes for DbHeader if is_page_one]
    #   PageHeader (12 bytes for interior; +4 for right_child):
    #     u8   page_type = 0x05
    #     u16  first_freeblock = 0
    #     u16  cell_count
    #     u16  cell_content_offset
    #     u8   fragmented_free_bytes = 0
    #     u32  right_child_page_no
    #   cell pointer array: cell_count × u16_be
    #   cells: each cell = u32_be child_page + varint rowid_key
    page = zeros(page_size)
    header_off = 100 if is_page_one else 0
    cell_blobs = [u32_be(c.child) + varint_be_encode(c.key) for c in cells]
    cursor = page_size
    pointers = []
    for blob in cell_blobs:
        cursor -= len(blob)
        page[cursor : cursor + len(blob)] = blob
        pointers.append(cursor)
    page[header_off + 0]  = 0x05
    write_u16_be(page, header_off + 1, 0)
    write_u16_be(page, header_off + 3, len(cells))
    write_u16_be(page, header_off + 5, cursor)
    page[header_off + 7]  = 0
    write_u32_be(page, header_off + 8, right_child_pn)  # right_child
    ptr_off = header_off + 12
    for p in pointers:
        write_u16_be(page, ptr_off, p)
        ptr_off += 2
    return page
```

### Split correctness pins

**S1. database_size bumps by exactly 2** for root-split (one new left
leaf + one new right leaf). The byte buffer grows by `2 * page_size`.

**S2. Old root page is converted to interior in-place** — same page
number (typically page 1 for the first user table after sqlite_master
bookkeeping, but may be a higher number; the probe reads root_page
from sqlite_master). is_page_one preserves the 100-byte DbHeader
reservation; if root_page == 1, the new interior page header lives at
offset 100, NOT 0.

**S3. Divider key = max rowid on left page.** With append-side split
this is `cells_old[-1].rowid`. Mainline's b-tree search uses
`key < divider` → descend right_child? No: SQLite's table b-tree uses
`rowid <= key` → descend the cell's child_page; otherwise descend
right_child. Append-side split: right page contains only `new_rowid >
max_left_rowid`, so `new_rowid > divider` → mainline descends
right_child = right_page_no, finds the new cell. ✓

**S4. Right-child of new interior root** points at the new right leaf.

**S5. Pointer-array order** — within a leaf or interior page, the
pointer array is stored in INSERTION-ASCENDING order in our build
helpers. Mainline doesn't require a specific order; cells must be
reachable through pointer indices. (The reader iterates pointers
left-to-right.)

**S6. mainline sqlite3 reads ALL rows** after split — `SELECT * FROM
t ORDER BY id` returns existing rows + new row, no corruption.

**S7. fileformat_read_runner reads ALL rows** — must descend the
interior root, visit both leaf children, return cells_old.len() + 1
rows total. (May require fileformat-read to support interior pages
beyond the existing tested scope; if not, this is a follow-up gap.)

**S8. Atomic write** — same discipline as single-page path. tmp +
fsync + rename. If the file is interrupted between steps 6 and 7, the
disk file is bit-identical to pre-write state.

**S9. Non-root + recursive paths are supported** — see §"Non-root
leaf split" and §"Recursive parent split". Every split path ends in
`write_atomic`; if any space check fails or the tree is malformed
mid-descent, return a `WriteError` without modifying the file.

**S10. did_split flag** — `WriteOk.did_split` is true iff this
insert called `split_and_insert`; false for the simple append branch.

## Probe expansion (v2 runner)

The single-page runner inserts one row into a fixture with one row.
The split runner pre-fills the fixture until the next INSERT would
trigger split, then issues that INSERT and verifies:
1. WriteOk.did_split == true
2. WriteOk.assigned_rowid == max_pre_rowid + 1
3. mainline `sqlite3 path "SELECT count(*) FROM t"` matches expected
4. mainline `sqlite3 path "SELECT * FROM t ORDER BY id LIMIT 5"` shows
   first 5 rows + last row; rowids increase monotonically
5. The on-disk file size grew by exactly 2 × page_size

The pre-fill helper is part of the runner harness (not the data path);
it issues a sequence of single-page-path inserts via insert_row until
the (N+1)th call would split.

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
