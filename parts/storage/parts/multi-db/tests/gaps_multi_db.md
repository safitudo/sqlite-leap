# multi-db — gaps

## Surface today
- `src-rust/multi_db.rs` (724 LOC) ships parser (`parse_attach_stmt`, `parse_detach_stmt`), registry (`MultiDbRegistry` with open_main / attach / detach / resolve / walk_unqualified), qualified-name resolver (`resolve_qualified_name`), and catalog-mutation opcodes (`MultiDbOp::Attach` / `Detach`). All pieces compile and have spec pin coverage.
- Spec dirs exist: `parts/parser/parts/attach-stmt`, `parts/parser/parts/detach-stmt`, `parts/storage/parts/multi-db`, `parts/compiler/parts/qualified-names`.

## SLT-visible blocker
`src-rust/examples/slt_runner.rs` `run_statement` dispatch only matches `CREATE / DROP / PRAGMA / BEGIN / COMMIT / END / ROLLBACK / SAVEPOINT / RELEASE / INSERT / REPLACE / UPDATE / DELETE`. There is no arm for `ATTACH` or `DETACH`, and no path to call `MultiDbOp::Attach`/`Detach` from a `.slt` record. ATTACH/DETACH from SLT today produce `statement: unsupported leading kw "ATTACH"` (an Err), so `statement error` PASSes — that's the honest pin.

## What the smoke pins
- baseline single-DB CREATE/INSERT/SELECT (3 records),
- ATTACH `:memory:` / file-path / `KEY <expr>` all error out,
- cross-DB CREATE TABLE `aux.t` and JOIN across `main.t1` / `aux.t2` error out (no schema resolution because `aux` was never bound),
- DETACH (existing / repeat / reserved `main`) error out.

11 / 11 PASS today.

## Wiring needed to flip these to richer tests
1. Add `("ATTACH", _)` and `("DETACH", _)` arms in `run_statement` that:
   - tokenize, call `parse_attach_stmt` / `parse_detach_stmt`,
   - drive `MultiDbRegistry::attach` / `detach` against a per-`Catalog` registry,
   - on ATTACH, `open_database_at(<eval(db_expr)>)` (or `:memory:` → `database_new`) to acquire a pager handle, store under the slot.
2. Extend `Catalog` (in slt_runner) with a `MultiDbRegistry` and per-slot `Database` table-stores so `database_install_table` / `compile_select_with_db` can be steered to a non-main slot.
3. Compiler arm for qualified-names already exists (`resolve_qualified_name`); the compiler entry points (`compile_select_with_db` etc.) need to accept a registry view so `aux.t` resolves.
4. KEY clause: the parser admits it; runner should map it to `AttachError::EncryptionNotSupported` until the encryption surface is wired (cross-references the encryption module — same blocker class).

## Spec-cleanliness note
Nothing in the SLT smoke leaks a Rust idiom — it's pure SQLite-CLI-style ATTACH/DETACH. Same `.slt` will run unchanged against the C / Zig / Go / Python runners once they grow the same dispatch arms.
