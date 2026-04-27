---
name: storage/rtree-index
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /parts/core/master.md
  - /parts/storage/master.md
  - /parts/storage/parts/btree/master.md
  - /parts/storage/parts/file-format/master.md
  - /parts/storage/parts/index/master.md
  - /parts/lib-api/parts/vtab/master.md
status: deferred-stunt
phase: post-v1
---

# Part: storage/rtree-index

R-tree spatial index, exposed as a virtual-table module named
`rtree`. Bidirectionally compatible with mainline SQLite's published
R-tree extension at the on-disk-shadow-table level: a database written
by LEAP-SQLite must be queryable by mainline, and vice versa, with
identical results on the deterministic operations defined in `/tests/`.

The unit of indexing is an N-dimensional **minimum bounding rectangle
(MBR)** keyed by a 64-bit rowid. Spatial predicates are expressed as
range constraints on the per-dimension min/max columns and answered
by a tree traversal that prunes whole subtrees by MBR overlap.

This spec is **language-neutral**. Errors are named conditions. Data
shapes are abstract records. Both the C and Rust generators must
implement the contract below without forcing either language.

## SQL surface

```
CREATE VIRTUAL TABLE <t> USING rtree(
    <id>,
    <minD1>, <maxD1>,
    [ <minD2>, <maxD2>, ]
    ...
);
```

- The first column is the integer rowid alias.
- The remaining columns appear in **(min, max) pairs**, one pair per
  spatial dimension. Dimension count `D` is at least 1 and at most 5.
- All min/max values are coerced to a numeric coordinate type
  (see Pin 6). MIN must be `<=` MAX or `RTREE_INVALID_BOUNDS` is
  raised.

`DROP TABLE <t>` removes the vtab and its three shadow tables atomically
under the surrounding transaction.

## Shadow tables

Each `CREATE VIRTUAL TABLE t USING rtree(...)` materializes three
ordinary B-tree tables in the host database, with these names and
roles:

| Shadow       | Role                                                 |
|--------------|------------------------------------------------------|
| `t_node`    | Tree pages keyed by `nodeno` (INTEGER PRIMARY KEY).  |
| `t_rowid`   | Row → leaf-node map, keyed by user `rowid`.          |
| `t_parent`  | Child → parent-node map, keyed by `nodeno`.          |

Names are chosen to match the published mainline R-tree shadow-table
names so that bidirectional file-format compatibility holds. The
schema rows describing these shadow tables live in `sqlite_schema`
just like any other ordinary table; they are not virtual.

Shadow-table schemas (logical, not as DDL strings):

- `t_node(nodeno INTEGER PRIMARY KEY, data BLOB)`
- `t_rowid(rowid INTEGER PRIMARY KEY, nodeno INTEGER)`
- `t_parent(nodeno INTEGER PRIMARY KEY, parentnode INTEGER)`

The root node always has `nodeno = 1`.

## Node BLOB layout (`t_node.data`)

Big-endian, mainline-compatible. Field widths are bytes.

```
+----+----+----+----+--------------------------------------+
| 2  | 2  |              entries[N]                        |
+----+----+
 depth  N

depth   uint16  : 0 == leaf node; >=1 == internal node.
N       uint16  : entry count, in [0, NODE_CAPACITY].
entries : N entries, each:
            rowid_or_child  int64
            coords[2*D]     coord    -- minD1,maxD1,minD2,maxD2,...
```

Where `coord` is the dimension's coordinate type (Pin 6). For leaves,
`rowid_or_child` is the user rowid; for internals, it is the child
`nodeno`.

`NODE_CAPACITY` is derived from page size and dimension count
(Pin 7). All entries in a node share the same width, so a node holds
exactly `N` fixed-size records — no per-entry length prefix.

## Operations (vtab module dispatch)

The `rtree` vtab module implements the standard vtab method surface
defined in `/parts/lib-api/parts/vtab/master.md`. Method names below
are abstract (each generator maps them to its target's vtab API):

- `module_create`  : on `CREATE VIRTUAL TABLE` — install the three
  shadow tables; insert root node with `depth=0, N=0`.
- `module_connect` : on subsequent connects — re-bind to existing
  shadow tables; validate column-spec parity.
- `module_destroy` : on `DROP TABLE` — drop all three shadow tables.
- `module_best_index` : produce a query plan from a set of
  per-column constraints (see Pin 9).
- `module_open` / `module_close` : cursor lifecycle.
- `module_filter` : begin a scan with the constraints chosen by
  best-index.
- `module_next` / `module_eof` / `module_column` / `module_rowid` :
  cursor traversal surface.
- `module_update` : INSERT / UPDATE / DELETE of MBR rows.

All methods route I/O through the host pager and participate in the
surrounding transaction; a failed split rolls back via the standard
WAL/journal path (Pin 14).

## State machine: insert

```
insert(rowid, mbr):
  if rowid already mapped via t_rowid: raise RTREE_DUPLICATE_ROWID
  leaf := choose_leaf(root, mbr)         # see Pin 10
  add_entry(leaf, rowid, mbr)
  if overflow(leaf):
    (a, b) := quadratic_split(leaf)      # see Pin 11
    propagate_split_up(a, b)
  adjust_mbrs_up(leaf)
  t_rowid[rowid] := leaf.nodeno
```

## State machine: query

```
filter(constraints):
  push(root)
  while stack non-empty:
    node := pop()
    if node.depth == 0:                  # leaf
      for entry in node:
        if mbr_satisfies(entry, constraints):
          yield (rowid = entry.rowid_or_child)
    else:
      for entry in node:
        if mbr_overlaps(entry, constraints):
          push(child(entry.rowid_or_child))
```

Yield order is **unspecified**; callers that need ordering must wrap
the vtab in `ORDER BY`. (Pin 13.)

## Pins

1. **rtree-as-vtab.** R-tree is implemented strictly through the
   vtab module surface from `/parts/lib-api/parts/vtab/master.md`.
   No new opcodes are added to the VDBE for spatial work; spatial
   work is driven entirely through generic vtab opcodes.

2. **Shadow names are wire-visible.** The shadow-table names
   `<t>_node`, `<t>_rowid`, `<t>_parent` are part of the on-disk
   contract. Renaming them breaks bidirectional compatibility with
   mainline-written databases.

3. **Three shadow tables, no more.** v1 of this part does not emit
   the optional 4th `<t>_rowid_n` auxiliary table; auxiliary columns
   are deferred. A spec change is required to add a fourth shadow.

4. **Big-endian node BLOBs.** All multi-byte integers and coordinate
   values inside `t_node.data` are stored big-endian.

5. **Root nodeno is 1.** The root always lives at `nodeno = 1`. The
   root is rewritten in place on splits — its `nodeno` never changes.

6. **Coordinate type is per-table, fixed at create.** Each rtree
   table uses one of two coordinate types for all dimensions:
   - `RTREE_COORD_F32` — IEEE-754 single-precision (default).
   - `RTREE_COORD_I32` — 32-bit signed integer (selected by the
     module argument `format=integer`; deferred — v1 emits F32 only).
   Mixed coordinate types within a table are forbidden.

7. **Node capacity is page-size-derived.**
   `NODE_CAPACITY = floor((usable_page_size - 4) / (8 + 4 * 2 * D))`
   where `usable_page_size = page_size - reserved_space`. Minimum
   capacity is 4; if the formula yields less, raise
   `RTREE_PAGE_TOO_SMALL` at `module_create`.

8. **Min-fill is one third.** A node split must produce two nodes
   each with at least `ceil(NODE_CAPACITY / 3)` entries. The split
   algorithm distributes leftover entries to maintain this.

9. **best-index is constraint-driven.** `module_best_index` accepts
   constraints of the form `<column> <op> ?` where `<column>` is one
   of the per-dimension min/max columns and `<op>` is one of
   `=, <, <=, >, >=, MATCH`. Equality on the rowid column is
   reported as a separate, cheaper plan that resolves through
   `<t>_rowid` directly.

10. **choose_leaf minimizes enlargement.** At each internal node,
    descend into the child whose MBR requires the **smallest area
    enlargement** to contain the new MBR. Ties are broken by
    smallest existing area, then by smallest `nodeno`. This rule is
    deterministic and must match across C and Rust builds.

11. **Quadratic split, deterministic seeds.** On overflow, pick the
    seed pair `(i, j)` that maximizes
    `area(MBR(i, j)) - area(i) - area(j)`. Then repeatedly pick the
    entry whose preference difference between the two groups is
    largest, assigning to the group it prefers. On ties, pick the
    entry with the smallest index, assigning to the smaller group.

12. **MBR adjust propagates upward only when bounds change.**
    After insert/delete, walk parents via `t_parent`. Stop as soon
    as a parent's MBR for the affected child does not change.

13. **Result order is unspecified.** A spatial scan yields rowids
    in tree-traversal order. Tests must use `ORDER BY` if they
    depend on order; otherwise harness uses set-equality.

14. **Atomicity through the host transaction.** Every mutation goes
    through the same pager/WAL path as ordinary B-tree writes; a
    crash mid-split must leave a consistent tree on recovery
    (root reachable, every leaf reachable from root, every rowid in
    `t_rowid` referencing an existing leaf entry).

15. **Integrity invariants for `PRAGMA integrity_check`.** A clean
    rtree must satisfy:
    - exactly one node with `nodeno = 1`;
    - every non-root node has exactly one entry in `t_parent`;
    - every leaf entry's rowid is present in `t_rowid` and maps
      back to that leaf's `nodeno`;
    - every internal entry's child MBR is contained in the parent
      entry's MBR;
    - every node has `1 <= N <= NODE_CAPACITY` (the root is
      allowed `N = 0` only when the table is empty).

16. **MATCH operator is the dispatch hook for custom predicates.**
    `<col> MATCH ?` in `WHERE` is reported by best-index as a
    `RTREE_MATCH` constraint. v1 of this part defines no built-in
    match functions; the slot is reserved so the wire surface does
    not change when generic-geometry predicates land later.

17. **Dimension count is immutable.** Once `module_create` succeeds
    with `D` dimensions, the table's dimensionality is fixed.
    `ALTER TABLE` against an rtree vtab is rejected with
    `RTREE_NOT_ALTERABLE`.

18. **Empty tree is well-formed.** A freshly created rtree has one
    leaf node at `nodeno = 1`, `depth = 0`, `N = 0`, no `t_rowid`
    rows, no `t_parent` rows. This is the canonical empty state and
    must round-trip through close/reopen unchanged.

19. **Coordinate equality uses raw bit pattern.** For `RTREE_COORD_F32`,
    NaN is rejected at insert with `RTREE_INVALID_BOUNDS`. Equality
    in best-index constraints uses bitwise comparison; this avoids
    cross-target divergence on `-0.0` / `+0.0` and signaling NaN.

20. **Named conditions raised by this part.**
    - `RTREE_INVALID_BOUNDS`     : MIN > MAX or coord is NaN.
    - `RTREE_DUPLICATE_ROWID`    : insert hit existing rowid.
    - `RTREE_PAGE_TOO_SMALL`     : derived capacity < 4.
    - `RTREE_NOT_ALTERABLE`      : ALTER TABLE on rtree vtab.
    - `RTREE_CORRUPT_NODE`       : node BLOB shorter than header,
      depth/N inconsistent, or child reference dangling.
    Each generator maps these to its target's idiomatic error
    surface; they MUST surface to the caller through the standard
    `RuntimeCondition` envelope, not as panics or aborts.

21. **No reads outside the published surface.** This part consumes
    only the vtab framework, the pager, the B-tree cursor surface,
    and the standard table cursor surface from `/parts/storage/`.
    It does not reach into other indexes, into the parser, or into
    the WAL frame layer directly.

22. **Test parity bar.** A test corpus item using
    `CREATE VIRTUAL TABLE ... USING rtree(...)` must produce
    byte-identical shadow-table contents on the C and Rust builds
    after the same insert/delete sequence, and a mainline-written
    rtree database must yield identical query results on both
    builds. This is the same bar as the rest of the storage layer
    (cf. `/parts/storage/parts/file-format/master.md`).

## Phase pins

- **Phase R1** — vtab module install, empty tree, single-row insert.
- **Phase R2** — multi-row insert without split.
- **Phase R3** — leaf split (quadratic, Pin 11).
- **Phase R4** — internal-node propagation on root split.
- **Phase R5** — delete + condense (reinsert orphans).
- **Phase R6** — best-index for all six constraint operators.
- **Phase R7** — bidirectional read of mainline-written rtrees.
- **Phase R8** — bidirectional write read by mainline.
- **Phase R9** — `PRAGMA integrity_check` covers Pin 15.

## Regeneration envelope

- Spec target size: ~250 lines (this file).
- Target leaf size: 600–900 lines per language target.
- This part is **deferred** per `/CLAUDE.md` § Scope — v1
  ("Deferred to follow-up stunts: ... R-tree ..."). It lands as
  part of the post-v1 spatial-extension stunt; v1 builds must not
  link this part into the default `rtree=enabled` configuration.
