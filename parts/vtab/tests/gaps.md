# vtab / rtree / fts5 — SQL-surface gap analysis

Three smoke SLTs exercise the SQL surface a user would type to drive the
`vtab.rs`, `rtree.rs`, `fts5_index.rs` + `fts5_tokenizer.rs` modules.
None of those modules are wired into the parser → compiler → runner →
VDBE path today. The smokes are the failing baseline.

Result table (from run_output.txt):

| module | pass | fail | defer | total | blocked-by                                                                       |
|--------|------|------|-------|-------|----------------------------------------------------------------------------------|
| vtab   |  5   |  0   |  9    | 14    | no CREATE VIRTUAL TABLE parser stmt                                              |
| rtree  |  2   |  7   |  6    | 15    | no CREATE VIRTUAL TABLE parser stmt                                              |
| fts5   |  3   |  6   |  8    | 17    | no CREATE VIRTUAL TABLE parser stmt + MATCH not infix-wired in expr              |

(Passes are all DROP TABLE on tables that were never created — a benign
artifact of the runner's "unknown table" fallthrough on DROP.)

The "DEFER" lines hand back the exact runner diagnostic; "FAIL" are
schema-resolution misses on subsequent INSERTs that follow a deferred
CREATE.

---

## Module 1: vtab.rs (1295 LOC, framework only)

### What exists
- `pub trait Module` with full xCreate / xConnect / xBestIndex / xOpen /
  xFilter / xNext / xEof / xColumn / xRowid / xUpdate / xBegin / xSync /
  xCommit / xRollback / xRename / xSavepoint / xRelease / xRollbackTo
  callback surface (Pins 1–26 from the spec).
- `pub struct VtabRegistry` with `register_module` / `unregister_module` /
  `create_vtab` / `connect_vtab` / `destroy_vtab` / `disconnect_vtab` /
  `close_registry`.
- Dispatch helpers: `best_index`, `open_cursor`, `filter_cursor`,
  `next_cursor`, `cursor_eof`, `cursor_column`, `cursor_rowid`,
  `close_cursor`, `update_vtab`, `begin_vtab`, `sync_vtab`, `commit_vtab`,
  `rollback_vtab`, `rename_vtab`, `savepoint_vtab`, `release_vtab`,
  `rollback_to_vtab`.
- 9 inline `#[cfg(test)]` Rust unit tests covering Pins 1, 2, 3, 4, 5,
  11, 14–17, 22.

### Unwired today (smoke blockers)
1. No `CREATE VIRTUAL TABLE` parser statement.
   - `KwVirtual` token exists in `parser/tokenizer.rs:150`, but it is
     only consumed inside `parser/create_table_stmt.rs:399, 420` for the
     column-level `GENERATED ALWAYS AS (...) VIRTUAL` modifier.
   - There is no `parts/parser/parts/create-virtual-table-stmt/` part,
     no `parser/create_virtual_table_stmt.rs` file, no entry in
     `parser/mod.rs` dispatch.
   - Needs: new spec part `parts/parser/parts/create-virtual-table-stmt/`
     with shape `CREATE VIRTUAL TABLE [IF NOT EXISTS] [schema-name.]name
     USING module-name [(module-args, ...)]` (per
     sqlite.org/lang_createvtab.html), AST node, parser dispatch in
     `parser::parse_statement`, top-level handler in slt_runner that
     calls `vtab::create_vtab(&mut reg, module, name, args)`.

2. No vtab name-resolution path in the compiler.
   - slt_runner says "compile: unknown table: series (schema is for )"
     — the compiler asks the storage `Database` for the table
     descriptor. Vtabs are in a side `VtabRegistry` (vtab.rs L307
     comment: "Wiring into Database is a follow-up integration step
     (compiler name resolution + VDBE cursor-kind discriminator).").
   - Needs: schema-resolution step that consults the VtabRegistry after
     the storage lookup misses; a `CursorKind::Vtab` discriminator in
     the VDBE so OpRewind/OpNext can route to `next_cursor` /
     `cursor_eof` instead of the b-tree path.

3. No eponymous-module registration at runner startup.
   - The runner does not register a `generate_series` module, or
     anything like `wholenumber`. Both must be registered before the
     create-vtab statement is parsed.
   - Needs: runner-level
     `vtab::register_module(&mut reg, "generate_series",
     Box::new(GenerateSeriesModule::new()))` calls during slt_runner
     boot. The modules themselves (`GenerateSeriesModule`,
     `WholeNumberModule`) need to be authored under
     `parts/vtab/parts/generate-series/` + `parts/vtab/parts/wholenumber/`.

4. No xUpdate→DML routing in the compiler.
   - `INSERT INTO series VALUES (...)` and friends would compile against
     the storage path even if name resolution succeeded. Pin 22's
     ReadOnly default needs to surface as a compile-time error or a
     runtime `RuntimeCondition`.
   - Needs: a compiler branch on `CursorKind::Vtab` that emits the
     argv-shape from Pins 14–17 (Delete/Insert/UpdateInPlace/RenameRowid)
     and a VDBE OpVUpdate that calls `vtab::update_vtab`.

---

## Module 2: rtree.rs (1289 LOC)

### What exists
- `RtreeVtab<S: ShadowStore>` with `insert_row`, `delete_row`, `query`
  driven by `RtreeConstraint { side, dim, value }`.
- BLOB-encoded `Node`/`Entry` page layout (encode/decode with
  configurable dimension `d`).
- `quadratic_split` for node overflow.
- `RtreeModule` + `RtreeCursor` + `RtreeStub` + `MemShadowStore`.
- `RtreeCondition` closed-set error variants (`RtError`).

### Unwired today (smoke blockers)
1. All vtab gaps from §1 above — same parser + name-resolution miss.
2. No CREATE-args → dimension inference.
   - `CREATE VIRTUAL TABLE bbox USING rtree(id, x0, x1, y0, y1)` must
     set `d = 2` (two pairs after the rowid column). Today the args
     never reach `RtreeVtab::new`.
   - Needs: an `RtreeModule::x_create` body that parses the comma-list,
     validates *(rowid + 2k coords)* shape, and constructs the vtab
     with `d = (args.len() - 1) / 2`.
3. No spatial-constraint extraction in xBestIndex.
   - `parts/rtree/master.md` describes routing `op` ∈ {Ge, Le, Eq}
     against coord-suffixed columns to `RtreeConstraint`. The module's
     xBestIndex body that consumes `IndexInfo.constraints` and emits a
     packed `idx_str` (e.g. `"x0:Ge,x1:Le"`) is not present in
     `rtree.rs`'s public surface and not invoked by the smoke path.
   - Needs: xBestIndex impl on `RtreeModule`; xFilter impl that decodes
     `idx_str` + `argv[]` back into `RtreeConstraint[]` and calls
     `RtreeVtab::query`.
4. No shadow-table provisioning at xCreate.
   - The R-tree's BLOB-key shadow table (`bbox_node`, `bbox_rowid`,
     `bbox_parent` in mainline parlance) needs to be CREATE TABLE'd
     against the storage layer when the vtab is created. `MemShadowStore`
     covers in-memory tests but the wiring into a real Database is not
     done.
5. No DELETE / xUpdate(Delete) routing. Same as vtab §1.4.

---

## Module 3: fts5_index.rs (853 LOC) + fts5_tokenizer.rs (579 LOC)

### What exists
- `Fts5IndexHandle` with structure-record + segment + posting-list
  encoding (varint-be, doclist-full, leaf-term records).
- `WriteSegment` builder with `append`, `append_tombstone`, `flush_leaf`.
- `Fts5Tokenizer` with `Unicode61Config`, `AsciiConfig` parser via
  `parse_tokenize_args`. `tokenize()` returns an `Fts5TokenStream`.
- `Fts5TableConfig` with shadow-table name helpers (`shadow_data`,
  `shadow_idx`, `shadow_content`, `shadow_docsize`, `shadow_config`).
- `DetailMode`, `ContentMode` enums.

### Unwired today (smoke blockers)
1. All vtab gaps from §1 above.
2. No `MATCH` operator wiring at the SQL level.
   - `KwMatch` token exists (`parser/tokenizer.rs:294`); `expr.rs:188`
     maps it to operator string `"MATCH"` in the precedence table.
   - But the slt_runner emits `query parse: 1:35 unexpected token after
     SELECT statement` on `WHERE docs MATCH 'quick'` — meaning the
     tokenizer / Pratt path is not actually consuming MATCH as an infix
     operator at the call site. (The `expr.rs:188` site is in a mapping
     table; the precedence row is likely absent or the operator is
     parsed but immediately rejected by the SELECT-stmt validator.)
   - Needs: confirm `parse_expr` accepts `<col-or-tbl-ref> MATCH
     <string-literal>` and emits an `Expr::Binary { op: "MATCH", … }`
     node; ensure the compiler routes `MATCH` to a `ConstraintOp::Match`
     for xBestIndex on the corresponding vtab cursor.
3. No fts5 module registration.
   - There is no `Fts5Module` impl of `vtab::Module`. `fts5_index.rs`
     gives the on-disk codec; the callback set that adapts it to the
     vtab framework is missing.
   - Needs: new file `fts5_module.rs` with `Fts5Module` implementing
     `Module`, parsing the create-args comma-list (column names +
     `tokenize='unicode61'` + `content='external'` options), provisioning
     the five shadow tables (data/idx/content/docsize/config) on
     xCreate, routing `xFilter(idx_num=MATCH, argv=[query_string])` to a
     `Fts5IndexHandle::search(query)` reader walk.
4. No BM25 ranking / `rank` virtual column.
   - `ORDER BY rank` is a sentinel column the fts5 vtab is supposed to
     declare; today there's no `rank` column emission in any
     `declare_sql`, no BM25 weight computation in `fts5_index.rs`'s
     public surface (the `Fts5PostingIter` produces unranked rowids).
   - Needs: BM25 doclist scorer (`bm25(idf_array, weights[],
     doc_len)`), `rank` synthesised as the cursor's last-emitted score,
     ORDER BY rank handled by xBestIndex consuming the order_by vector.
5. No `snippet()` / `highlight()` / `bm25()` auxiliary scalars.
   - These are SQLite-side scalars that take the vtab cursor + a column
     index. None are in `parts/scalar-builtins/`. The smoke deliberately
     calls `snippet(docs, 0, '<', '>', '...', 8)` — DEFER on parse.
   - Needs: spec for the three scalars under
     `parts/scalar-builtins/parts/fts5-aux/`, plus a callback path that
     lets a scalar reach into the active fts5 cursor's posting state.
6. No fts5-query-language tokenizer.
   - The MATCH RHS is a mini-language: `term`, `term1 AND term2`,
     `"phrase term"`, `col:term`, `^prefix*`, `NEAR(a b, 5)`, etc. The
     tokenizer in `fts5_tokenizer.rs` tokenizes *document* text, not
     the *query* expression.
   - Needs: a separate query-grammar parser part producing a parse tree
     the index reader walks (And/Or/Not/Phrase/Near/Prefix nodes).

---

## Common-cause summary

A single missing surface — `CREATE VIRTUAL TABLE … USING <module>` at
the parser level, plus the compiler-side name-resolution into
`VtabRegistry` — would unblock the first 1–2 records of every smoke
above. After that:

- vtab smoke would need `generate_series` + `wholenumber` modules
  authored as parts and registered at runner boot.
- rtree smoke would need `RtreeModule` to implement `Module` with
  CREATE-args parsing + xBestIndex/xFilter spatial routing.
- fts5 smoke would need `Fts5Module` + MATCH-operator wiring +
  shadow-table provisioning + BM25 + the three auxiliary scalars.

Roughly four new spec parts
(`parts/parser/parts/create-virtual-table-stmt/`,
`parts/vtab/parts/{generate-series,wholenumber}/`,
`parts/rtree/parts/module/`, `parts/fts5/parts/module/` +
`parts/fts5/parts/query-grammar/` +
`parts/scalar-builtins/parts/fts5-aux/`) to drive the smokes from
red → green via spec-first emission.
