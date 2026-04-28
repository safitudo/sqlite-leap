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

### 2. ~~L4 INSERT — match mainline's transaction semantics~~ ✓ CLOSED 2026-04-27 evening (commit 677ff68 + Linux re-run)

mem-store v7-tx adds real BEGIN/COMMIT/ROLLBACK with snapshot frames (pin 17). lib_bench.rs/.c route the SQL keywords to the new API instead of treating them as no-ops.

**Linux x86_64 post-fix (Ubuntu 22.04, gcc 11.4, rustc 1.89, native bench `bash bench/run-linux-libmode.sh`):**
- L3 SELECT: leap-c 949 K q/s vs mainline 580 K = **1.64× (held; up from pre-fix 1.51×)**
- L4 INSERT: leap-c 1.21 M ips vs mainline 669 K = **1.81× (held)**

Both lanes survive symmetric harness work. Mac arm64 post-fix L4 0.84× is a platform-local result (likely allocator/locking on darwin) and does not block the Linux claim. Raw CSV at `bench/results/2026-04-27-linux-postfix/raw.csv`. Publication has been re-headlined to claim both L3 and L4.



**Where it leaks today:** `src-c/examples/lib_bench.c:20` says "PRAGMA / BEGIN / COMMIT / ROLLBACK are no-ops." Mainline's bench path runs the begin/commit machinery; leap-c skips it. The L4 1.81× win is partly real (prepared-stmt cache, predicate pushdown) and partly because leap is doing less work.

**Acceptance:**
- Wire BEGIN/COMMIT/ROLLBACK through the leap lib_bench path (whether via the WAL backend or an in-memory transaction stub).
- Re-run L4 with both engines doing the same transactional dance.
- Publish whatever number that produces — including if the win shrinks to 1.2× or disappears.

### 2.5. Pin 18.1e — WAL frame fsync wire-in for C/Zig/Go/Python

**Status:** open as of 2026-04-28. Surfaced by 5-target lib-mode bench rerun (`bench/results/2026-04-28-linux-native-libmode/raw.csv`).

**The gap:** Pin 18.1d (path-backed Pager + per-COMMIT WAL frame fsync + crash recovery on open) landed on leap-rust only. Wave G2 emitted the wal-bridge spec to all 4 sibling targets so the *types* and *byte-layout helpers* exist, but the call site that should invoke `wal_bridge.append_commit_frames()` from `Pager.commit_transaction()` is Rust-only. So:

- **leap-c** writes a 32-byte WAL header on open, no committed frames. `build_lib_bench.sh` links `wal_bridge.c` but the call from Pager.commit isn't there.
- **leap-zig / leap-go / leap-python** have no path-backed Pager at all. `closeDatabaseAt()` / `close_database_at()` serialize the whole DB and atomic-rename at process exit. That's "durable on close" but it's not WAL — there is no `-wal` sidecar in steady state.
- **leap-rust** is the only target whose L4 number (`bench/results/2026-04-28-linux-native-libmode/raw.csv`, 0.57× vs mainline) is a true engine-vs-engine apples-to-apples claim. The leap-c / leap-zig L4 wins (1.87× / 1.52×) reflect strictly less durability work being done.

**Why it can't ship as a single agent dispatch:** the spec doesn't currently specify the cross-leaf imperative `Pager.commit_transaction must call wal_bridge.append_commit_frames(dirty_pages) and fsync the wal sidecar before returning`. That linkage is implicit in Rust's existing implementation but hasn't been promoted to `parts/storage/parts/pager/master.md` as a target-neutral pin. Sibling agents need the spec to tell them this; otherwise they invent and diverge.

**Suggested ordering when this is picked up:**
1. **Spec extension first.** Add Pin 18.1e to `parts/storage/parts/pager/master.md`: a numbered Correctness pin specifying that `Pager.commit_transaction` (or the equivalent ConcreteCommit op) must (a) collect dirty pages, (b) call `wal_bridge.append_commit_frames`, (c) fsync the `-wal` sidecar before returning. Map it through `parts/storage/parts/wal-bridge/master.md` and `parts/storage/parts/wal/master.md` so the cross-leaf imports are explicit.
2. **leap-c first.** Smallest scope: bridge code already linked, just the wire-in. This validates the spec extension survives one sibling regen.
3. **leap-zig/go/python** in parallel only after leap-c lands. These three need a path-backed Pager (track DB path + WAL sidecar path) and an incremental WAL frame writer — substantial new infrastructure on each, not a wire-in. Each will be ~2–4K LOC of new emission and likely surface convergent spec gaps that have to be closed before the regen sticks.
4. **Re-run** `bench/run-linux-libmode.sh` after each sibling lands; the L4 column should converge across the 4 siblings (all should produce a real `-wal` sidecar with synced frames).

**Acceptance:**
- All 5 leap targets produce a real `-wal` sidecar after `lib_bench --db ... --time-setup` with content beyond a 32-byte header (containing committed frames matching the inserts).
- `sqlite3 /tmp/test.<target>.db 'PRAGMA integrity_check'` returns `ok` for all 5 targets after a kill-mid-COMMIT scenario (true crash safety, not just clean-shutdown durability).
- `bench/results/<date>-linux-native-libmode/raw.csv` L4 column reads as a true engine-vs-engine comparison; PUBLISHED.md §B.3's WAL-tier-asymmetry caveat is removed.

**Until this lands**, every L4 lib-mode number for C/Zig/Go/Python ships with the WAL-tier caveat in PUBLISHED.md §B.3. Removing the caveat is the gating condition.

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
