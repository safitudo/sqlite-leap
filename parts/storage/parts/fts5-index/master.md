---
name: storage/fts5-index
kind: leaf
emits:
  rust:   { path: src-rust/storage_fts5_index.rs }
  c:      { path: src-c/storage/fts5_index.c }
  zig:    { path: src-zig/storage_fts5_index.zig }
  go:     { path: src-go/storage/fts5_index.go }
  python: { path: src-python/leap_sqlite/storage_fts5_index.py }
---

# Part: storage/fts5-index — on-disk inverted index

Owns the FTS5 index as a set of mainline-compatible *shadow tables*
that ride on top of the regular b-tree storage layer. No new file
format, no new pages — every byte FTS5 emits is an INSERT into a
normal SQLite table managed by `parts/storage/parts/btree`. This
keeps file-format compatibility automatic: a database that contains
an FTS5 table opens cleanly in mainline SQLite and vice versa.

This part owns:

- The shadow-table schema (`t_data`, `t_idx`, `t_content`,
  `t_docsize`, `t_config`).
- The segment file format embedded inside `t_data` blob rows
  (b-tree of doclists, prefix indexes, structure record).
- The doclist encoding (varint deltas, position lists,
  `detail=full | column | none` variants).
- The structure record (segment list, levels, write-cursor).
- INSERT / DELETE of (rowid, column-tokens) into the index.
- Iterator surface consumed by `scalar-builtins/fts5`:
  `posting_iter_term(term)`, `posting_iter_prefix(prefix)`,
  `posting_iter_phrase(tokens)`.

It does NOT own tokenization (sibling part) or query parsing
(`scalar-builtins/fts5`).

## Shadow-table layout

For an FTS5 table named `t`:

```
CREATE TABLE t_data    (id INTEGER PRIMARY KEY, block BLOB);
CREATE TABLE t_idx     (segid INTEGER, term BLOB, pgno INTEGER,
                        PRIMARY KEY(segid, term)) WITHOUT ROWID;
CREATE TABLE t_content (id INTEGER PRIMARY KEY, c0, c1, …);   -- internal
CREATE TABLE t_docsize (id INTEGER PRIMARY KEY, sz BLOB);     -- columnsize=1
CREATE TABLE t_config  (k TEXT PRIMARY KEY, v) WITHOUT ROWID;
```

`t_content` is omitted when `content=` is non-empty (external) or
empty-string (contentless). `t_docsize` is omitted when
`columnsize=0`.

## Correctness pins

1. **Shadow-table naming.** Concatenate the FTS5 table name with the
   literal suffixes `_data`, `_idx`, `_content`, `_docsize`,
   `_config`. Quoting and case follow the FTS5 table's
   case-preserving form. A user table that happens to share a
   shadow name is a CREATE-time error (`Fts5ShadowCollision`).

2. **Structure record.** `t_data` row with `id = 10` holds the
   *structure record* for the index: a sequence describing every
   level of the LSM, every segment within a level, and the
   write-cursor. Encoding (all varints, big-endian byte order):

   ```
   structure := nlevels:varint, write_counter:varint, level*
   level     := segs_in_level:varint, merge:varint, seg*
   seg       := segid:varint, leaves_end_pgno:varint,
                pgno_first:varint, pgno_last:varint
   ```

   The structure record is rewritten on every transactional commit
   that mutates the index. Other `t_data` rows are segment leaves
   keyed by `id = (segid << 32) | local_pgno`.

3. **Segment leaf encoding.** A segment-leaf blob in `t_data` is a
   sequence of `(term, doclist)` records:

   ```
   leaf := (term_record)+
   term_record := term_len:varint, term_bytes,
                  doclist_len:varint, doclist_bytes
   ```

   Within a leaf, terms appear in lexicographic byte order. Across
   the leaves of a segment, terms are partitioned but still
   globally ordered. The leading varint of every leaf gives the
   length of that page's *header* — used for prefix-restart marks
   when leaves are large; v1 may emit zero (no internal restarts).

4. **Doclist encoding (detail=full).**

   ```
   doclist     := first_doc, (next_doc)*
   first_doc   := rowid:varint, poslist
   next_doc    := delta_rowid:varint, poslist          -- delta from previous doc
   poslist     := byte 0x01? column_pos_list (byte 0x01 column_pos_list)* byte 0x00
   column_pos_list := col_no:varint, position_list
   position_list := first_pos:varint, (delta_pos:varint)*, terminator:byte 0x00
   ```

   - First column in a row is implied to be column 0 if the leading
     `0x01` byte is absent.
   - `delta_rowid` is `rowid - prev_rowid` (always positive within a
     segment because rowids are inserted in ascending order; merges
     preserve this).
   - `delta_pos` is `pos - prev_pos + 2` (the `+2` reserves 0 for
     terminator and 1 for column-switch, matching mainline FTS5).
   - The poslist for a doc ends with a single `0x00` byte.

5. **Doclist encoding (detail=column).** As above but the
   `position_list` is replaced by a single `0x00` terminator after
   each `col_no` — only column membership is recorded.

6. **Doclist encoding (detail=none).** Doclist is a sequence of
   `delta_rowid` varints with no per-doc poslist. Phrase queries
   degenerate to single-term queries; NEAR is rejected at query
   time as `Fts5DetailNoneNear`.

7. **Prefix indexes.** When the `prefix='2 4'` table option is in
   force, the index maintains parallel "prefix segments" alongside
   the term segments. Each prefix segment of length N keys on the
   first N bytes of the term. Prefix segments live in their own
   `segid` namespace inside `t_idx` and are written as separate
   structure-record levels. Query-time, `posting_iter_prefix(p)`
   consults the matching-length prefix index when present;
   otherwise it scans the term index for a `[p, p++)` range.

8. **`t_idx` role.** Every segment leaf gets one `t_idx` row keyed
   by `(segid, first_term_in_leaf)` mapping to the `pgno` (the
   `id` of the matching `t_data` row). This is the per-segment
   sparse term-to-page map and is the entry point for term lookup.
   Leaves within a segment are linked by `pgno` ordering.

9. **`t_config` role.** Stores all module options as `(k, v)` text
   pairs: `version`, `tokenize`, `prefix`, `content`,
   `content_rowid`, `columnsize`, `detail`, `rank`. `version`
   is the literal string `'4'` for the v1 layout (matches mainline
   FTS5). On open, this part reads `t_config` to rebuild
   `Fts5TableConfig`.

10. **`t_docsize` encoding.** One row per indexed FTS5 row.
    `sz` is a blob holding `column_count` varints, each the token
    count for that column on that row. Used by BM25 normalization.
    Suppressed when `columnsize=0`.

11. **`t_content` role.** Internal-content mode only. One row per
    FTS5 row with `id = rowid` and one untyped column per FTS5
    column in declaration order. UNINDEXED columns are stored
    here just like indexed ones; the difference is they never
    enter postings.

12. **External-content mode.** When `content='external_tbl'` and
    `content_rowid='id'`, the FTS5 table reads row content from
    `external_tbl` joined on `external_tbl.id = rowid`. The
    contract is one-way: writes to `external_tbl` do not auto-sync
    into the index; the application must call the `'rebuild'`
    or `'delete-all' / 'insert'` magic-column protocol. v1 spec
    matches mainline behavior here.

13. **Contentless mode.** `content=''`. No `t_content`. Phrases
    can still be looked up because postings are kept, but
    `SELECT col FROM t WHERE …` returns SQL `NULL` for every
    column. `DELETE FROM t WHERE rowid=…` is supported only with
    `contentless_delete=1` (deferred — v1 errors with
    `Fts5ContentlessDelete`).

14. **INSERT path.** On INSERT into the FTS5 table:
    1. Tokenize each indexed column.
    2. Append `(rowid, col, pos, term)` quadruples into the
       in-memory hash for the active *write segment* (segid =
       `write_counter + 1`).
    3. When the write segment exceeds the page-size budget
       (default 1024 entries; `pgsz` option overrides), emit it
       as a level-0 segment: write leaves to `t_data`, term-page
       map to `t_idx`, append a level-0 entry to the structure
       record.
    4. Write the row into `t_content` (internal mode) or skip
       (external/contentless).
    5. Write the column sizes into `t_docsize` (when enabled).

15. **DELETE path.** Per-rowid deletes are recorded as *tombstone*
    postings: a doclist entry with the special poslist marker byte
    `0x02`. Merges drop tombstoned rowids. Until merged, the
    iterator masks them out of the result stream.

16. **Merge policy.** Background merges combine all level-N
    segments into a single level-(N+1) segment when the level
    contains ≥ `crisismerge` segments (default 16) or
    ≥ `usermerge` segments and a write transaction asks. v1 mandate
    is correctness only; merges may run synchronously inside the
    INSERT path. Triggered merges step the structure-record
    `merge` field while running so that aborted merges leave no
    half-state.

17. **Term iterator API (consumed by sibling).** The
    `Fts5IndexHandle` exposes:
    - `posting_iter_term(term) -> Fts5PostingIter` — yields
      `(rowid, col, pos)` tuples ascending by rowid.
    - `posting_iter_prefix(prefix) -> Fts5PostingIter` — same,
      but for terms with the byte-prefix.
    - `posting_iter_phrase(tokens) -> Fts5PostingIter` — yields
      `(rowid, col, first_pos)` tuples for adjacent runs.
    - `row_dl(rowid) -> token_count` — for BM25.
    - `total_rows() -> u64`, `n_rows_with(term) -> u64` — for IDF.

18. **Iterator merge invariant.** All concrete iterators yield
    rowids in ascending order. Multi-segment iterators k-way merge
    and dedupe by rowid (later segments win on conflict, then
    tombstones drop the row entirely). This invariant is what lets
    the boolean operators (AND/OR/NOT) be linear-time.

19. **Term ordering.** Terms inside `t_idx` and inside segment
    leaves are byte-ordered (memcmp on the UTF-8 bytes). The
    tokenizer is responsible for case-folding before bytes hit
    this part — this part does NOT case-fold.

20. **Big-endian integer encoding.** All multi-byte integers in
    blob payloads are big-endian to match mainline. Varints are
    SQLite's huffman varint (1–9 bytes), shared with the rest of
    the file format via the `varint_be` codec in
    `parts/storage/parts/file-format`.

21. **Transactional integration.** All writes route through the
    standard btree+pager layer; the index is transactional with
    the surrounding statement. Crashes mid-INSERT roll back via
    the WAL like any other table.

22. **Integrity check.** The `'integrity-check'` magic-column
    command walks every segment, verifies term ordering, doclist
    parses, structure-record consistency, and rowid uniqueness
    across non-tombstoned postings; reports `Fts5IntegrityError`
    on the first deviation.

23. **Mainline-compat invariant.** A database written by this
    leaf must open without error in mainline SQLite linked with
    FTS5. Mainline `PRAGMA integrity_check` must report `ok`.
    This is the load-bearing benchmark for the on-disk layout —
    same standard as the rest of `parts/storage/`.

## Generation scope

Leaf. Each target `mapping.md` describes how it walks `t_data`
blobs (Rust: `&[u8]` slice; C: `unsigned char *` + length; etc.)
and how it implements the structure-record reader. The varint
codec and big-endian primitives are reused from
`parts/storage/parts/file-format`.

## Out of scope (v1)

- `contentless_delete=1` — deferred; v1 raises
  `Fts5ContentlessDelete` on DELETE in contentless mode.
- Background-thread merges — v1 merges synchronously inside the
  writing statement.
- The `'optimize'` magic-column command — accepted by the parser
  but parse-and-no-op in v1.
