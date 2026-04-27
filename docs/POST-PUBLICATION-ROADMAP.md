# Post-publication roadmap

Items deferred from the 2026-04-27 publication push, in priority order. None are blockers for publishing the honest version of PUBLICATION.md / README.md.

## P0 — close the methodology gap that the second BS check exposed

### 1. ~~Spec-promote the lib_bench.c PK-install lift~~ ✓ CLOSED 2026-04-27 evening (commit 770ceda)

`pk_from_create_stmt(stmt)` declared in `parts/parser/parts/create-table-stmt/` (pin 20); `database_install_table_with_pk` declared in `parts/storage/parts/mem-store/` (pin 16). lib_bench.c + lib_bench.rs hand-detection deleted, helper called instead. select1.test 1031/1031 holds. L3 perf preserved on Mac arm64.



**Where it leaks today:** `src-c/examples/lib_bench.c:240-273` hand-detects a single-column `INTEGER PRIMARY KEY` column, then calls `catalog_install_table(cat, tname, col_names, ncols, pk_col)` which forwards to `leap_storage_database_install_table_with_pk`. The file's header explicitly tags this `leaplint: target-local lift (pending spec promotion 2026-04-26)`.

**Why it matters:** the L3 SELECT 1.51× win on Linux native lib-mode depends on this PK-index path. Until the lift is in the spec, the publication's strongest honest framing is "spec-generated engine + hand-tuned C harness with PK lift beats mainline" — not "the spec-generated engine beats mainline." The distinction is real and a critic noticed.

**Two design options to choose between (Stan-call, not autonomous):**

A. **Helper-style:** add a leaf-level helper `detect_rowid_alias_pk(stmt: &CreateTableStmt) -> option<column_name>` to `parts/parser/parts/create-table-stmt/` or a new sibling leaf. The harness keeps explicit `install_table_with_pk` call but uses the spec-emitted helper instead of hand-written detection. Smaller scope; preserves explicit-install API.

B. **Auto-install:** make `compile_create_table` (or the storage `install_table` entrypoint) automatically detect rowid-alias PK and configure the index. lib_bench.c becomes `compile_and_run(stmt)` with no PK awareness. Cleaner methodology framing; bigger refactor; needs to not break the SLT corpus.

**Acceptance:**
- 5/5 targets emit the helper or auto-install path from `parts/`.
- `bash bench/run-linux-libmode.sh` reproduces the 1.51× L3 win without any `leaplint: target-local lift` tag remaining in `src-c/examples/lib_bench.c`.
- `select1.test` regression gate holds 1031/1031 across all 5 targets.

### 2. L4 INSERT — match mainline's transaction semantics

**Where it leaks today:** `src-c/examples/lib_bench.c:20` says "PRAGMA / BEGIN / COMMIT / ROLLBACK are no-ops." Mainline's bench path runs the begin/commit machinery; leap-c skips it. The L4 1.81× win is partly real (prepared-stmt cache, predicate pushdown) and partly because leap is doing less work.

**Acceptance:**
- Wire BEGIN/COMMIT/ROLLBACK through the leap lib_bench path (whether via the WAL backend or an in-memory transaction stub).
- Re-run L4 with both engines doing the same transactional dance.
- Publish whatever number that produces — including if the win shrinks to 1.2× or disappears.

## P1 — broader validation

### 3. Multi-distro Linux CI

Currently the publishable Linux numbers come from one Ubuntu 22.04 box (Stan's Linux host, 32 cores, rustc 1.89, gcc 11.4). A reviewer correctly flagged single-host validation. Wire bench to GHA matrix: ubuntu-22.04, ubuntu-24.04, debian-12, fedora-40. Compare numbers; document any drift.

### 4. Re-run the full upstream sqllogictest corpus, not the 186-file sample

The 99.93–99.99% excl-SKIP / 92–95% incl-SKIP rates are over a 186-file sample. The upstream corpus is much larger. A run on the full corpus will likely produce lower rates (especially for the long-tail random/* directory) and surface defer/fail buckets the sample missed. Publish honestly; the pass rate may drop.

### 5. Stratify the SLT sample against upstream corpus difficulty distribution

If we keep the sampled run as the publishable number for cost reasons, document the sampling strategy and demonstrate it tracks the full-corpus distribution.

## P2 — methodology completeness

### 6. 5-target propagation of FK / triggers / savepoints / WITHOUT-ROWID / etc.

Per README, JSON1 is the only module with full 5-target wire-in. The rest are Rust-first. ~24 person-days estimate; mostly mechanical (specs are in place, sibling regen via `leapgen.py`).

### 7. Spec-promote the lib_bench harness primitives more broadly

Beyond PK-install: `catalog_install_table`, `prepared-statement cache`, the parse-only mode entrypoint. All currently target-local. Promoting them removes the entire "harness is hand-written" caveat from the publication.

## P3 — publication mechanics

### 8. License decision

Currently TBD in README. Pre-publication decision needed.

### 9. Repo URL placeholder

`<link>` in PUBLICATION.md. Set when publication venue is known.

### 10. Independent corroboration of L3/L4 numbers on a second Linux box

Even one re-run on a different host (different CPU, different rustc minor, different glibc) substantially de-risks the "fragile 24-hour-old wins" critique.

---

**Order of attack** (recommended): #1 then #2 (the methodology-honesty fixes) ⇒ #4 + #10 (re-validate on broader scope) ⇒ #6 + #7 (close the multi-target and harness-spec gaps) ⇒ #3 + #5 + #8 + #9 (publication mechanics).
