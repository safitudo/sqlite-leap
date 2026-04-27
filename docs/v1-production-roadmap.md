# sqlite-leap v1 — production roadmap & decisions

**Status:** decision document.
**Audience:** Stan + me (the AI executor).
**Purpose:** answer once, I run autonomously to v1.0 with minimal check-ins.

---

## Where we are

- 5 implementations (Rust, C, Zig, Go, Python) from one spec
- ~50% of mainline SQLite feature surface
- ~99.9% pass on sqllogictest excl-SKIP, all 5 targets, both macOS arm64 + Linux x86_64
- 3 publishable architectural wins (cold-start 4×, size 2.6×, memory 1.6× vs mainline)
- 1.94-2.86× faster than mainline on Lane 4 prepared INSERT (3 of 5 targets)
- Predicate-pushdown rule, prepared statements, real param binding, all 5-target

## Goal

**Beat Turso decisively, match mainline on practical use cases, ship as production-ready compatibility implementation with one published packaged release per target.**

Not a goal: feature-parity with mainline on extension surface (FTS5, R-tree, virtual tables, encryption — defer or omit, like Turso).

Estimated work: **8-12 weeks** at LEAP pace, autonomous-runnable.

---

## Section 1 — Decisions I need from you

Each decision below has options and a recommendation. **Mark your choice for each one** in this file (commit your edits) and I have everything I need to run.

### 1.1 Feature scope — what's IN v1.0?

For each, mark `[YES]`, `[NO]`, or `[DEFER to v1.x]`.

| Feature | Effort | Recommendation |
|---|---|---|
| Triggers (BEFORE/AFTER, FOR EACH ROW) | 3-5 days | YES — unblocks ORM users |
| Triggers (INSTEAD OF on views) | +1-2 days | YES — small marginal cost |
| FOREIGN KEY enforcement (CASCADE/SET NULL/RESTRICT) | 2-3 days | YES — credibility blocker |
| Savepoints (SAVEPOINT/RELEASE/ROLLBACK TO) | 2 days | YES — frameworks need this |
| ATTACH/DETACH DATABASE | 3-4 days | YES — wide use |
| WITHOUT ROWID tables | 3-4 days | DEFER — niche |
| JSON1 real impl (json_extract/array/object/type/valid/array_length/insert/replace/set/remove/patch) | 2-3 days | YES — used everywhere |
| Virtual tables (CREATE VIRTUAL TABLE + xBestIndex/xFilter API) | 5-7 days | DEFER — big surface, low practical demand at v1 |
| FTS5 | 2 weeks | DEFER (Turso also defers) |
| R-tree | 1 week | DEFER (niche) |
| Encryption (SEE-compat or our own) | 3-5 days | DEFER (security claim hard to validate at v1) |
| Authorizer hooks | 1-2 days | YES — small, useful for sandboxing |
| update_hook / commit_hook / rollback_hook | 1 day | YES — observability primitives |
| Loadable extensions (.load) | 3-5 days | DEFER — security risk, low demand |
| Backup API (sqlite3_backup_*) | 2-3 days | YES — common ops need |
| Online VACUUM | 2 days | YES — small, useful |
| INCREMENTAL VACUUM | 1 day | DEFER |
| Full PRAGMA surface (~80 pragmas; we have ~15) | 1 week | YES — most are quick |
| Window functions full surface (LAG/LEAD/NTILE/PERCENT_RANK/CUME_DIST) | 2-3 days | YES — common analytic |
| Generated columns STORED variant (we have VIRTUAL) | 1 day | YES |

**My picks for the YES list (default if no answer):** Triggers + FK + Savepoints + ATTACH + JSON1 + Authorizer + hooks + Backup API + Online VACUUM + Full PRAGMA + Window full surface + Generated STORED. **Defer:** Virtual tables, FTS5, R-tree, Encryption, Loadable extensions, WITHOUT ROWID, INCREMENTAL VACUUM.

**Your decision (mark below):**

```
[ ] Accept my picks above
[ ] Custom — list overrides:
```

### 1.2 Engine infrastructure — what's required for "production"?

| Item | Effort | Required? |
|---|---|---|
| Real page cache (LRU, configurable size) | 3-4 days | YES |
| Multi-process WAL (Phase 4c — shm + wal-index) | 4-5 days | YES |
| Crash recovery wired into open_database_at (Phase 4a multi-frame walk) | 1 day | YES (kills data-loss caveat) |
| Real PRAGMA synchronous semantics (FULL/NORMAL/OFF actually do what they say) | 1-2 days | YES |
| Real journal_mode (DELETE/TRUNCATE/PERSIST/WAL/MEMORY) | 2-3 days | YES |
| Lock escalation (DEFERRED/IMMEDIATE/EXCLUSIVE) | 2 days | YES |
| Shared cache mode | 2-3 days | DEFER |
| Connection pooling | 1 day | YES (small) |

**Defaults to set:**
- Default journal_mode: **WAL** (matches mainline best-practice default since 3.7)
- Default synchronous: **NORMAL** (matches mainline WAL default; FULL is paranoid)
- Default page_size: **4096** (matches mainline)
- Default cache_size: **2000 pages = 8MB** (matches mainline)

```
[ ] Accept defaults
[ ] Override:
```

### 1.3 Concurrency model

```
[ ] Multi-thread model: one connection per thread, no shared cache (Turso's default; safest)
[ ] Multi-thread model: shared cache mode opt-in (mainline-compat)
[ ] Other:
```

```
[ ] Multi-process: full WAL with shm/wal-index (mainline-compat)
[ ] Multi-process: defer to v1.1
[ ] Other:
```

### 1.4 Test bar — what does "done" mean?

| Test surface | "Done" threshold |
|---|---|
| sqllogictest excl-SKIP | ≥99.9% all 5 targets, both platforms |
| sqllogictest incl-SKIP | publish the number; aim ≥75% |
| Mainline TCL test suite (subset of ~30 most-relevant test files) | ≥95% all 5 targets |
| Fuzz corpus (parser + file-format) | 7 days continuous, zero panics |
| TPC-C subset (1, 10, 100 warehouses) | within 50% of mainline throughput |
| sysbench OLTP read-only | within 50% of mainline |
| sysbench OLTP read-write | within 50% of mainline |
| Multi-reader stress (4 readers + 1 writer × 60s) | zero corruption, zero deadlock |
| mptest equivalent (multi-process stress) | passes |
| Fault injection (kill -9 mid-write × 1000 trials) | recovery in 100% of cases |
| Cross-target byte-identity (file-format writes) | 100% across 5 targets |
| Linux + macOS reproduction | all numbers reproduce ±5% |

```
[ ] Accept these thresholds
[ ] Override:
```

**Note:** the perf thresholds (TPC-C, sysbench within 50%) are conservative. We may beat them; that's fine. Setting them as "done" so we don't chase phantom perf indefinitely.

### 1.5 Distribution surface

What do we ship at v1.0?

| Target | Package | Recommendation |
|---|---|---|
| Rust | crates.io as `sqlite-leap` | YES |
| C | static lib + shared lib + pkg-config | YES |
| C | sqlite3_*-compatible ABI shim (drop-in) | YES — biggest credibility move |
| Python | PyPI as `sqliteleap` (or via stdlib `sqlite3`-compat shim) | YES |
| Go | Go module under `github.com/safitudo/sqlite-leap-go` | YES |
| Zig | Zig package | YES |
| WASM | npm as `@safitudo/sqlite-leap-wasm` | YES |
| Mobile (iOS/Android) | XCFramework + AAR | DEFER to v1.1 |
| Windows x86_64 binaries | yes/no? | YES if Rust+C cross-compile clean; we can validate |

```
[ ] Accept distribution surface above
[ ] Override:
```

### 1.6 sqlite3_* C ABI shim — scope

If YES on the shim above, what's the scope?

| API surface | Scope decision |
|---|---|
| `sqlite3_open/close/prepare/step/finalize/bind_*/column_*/exec/errmsg` (core 30 funcs) | YES — minimum for drop-in |
| `sqlite3_value_*`, `sqlite3_result_*` (custom function API) | YES |
| `sqlite3_create_function*` | YES |
| `sqlite3_backup_*` | YES if Backup API in scope |
| `sqlite3_blob_*` (incremental BLOB I/O) | YES |
| `sqlite3_mutex_*` | YES (no-op acceptable for v1) |
| `sqlite3_stmt_status`, `sqlite3_db_status` | YES |
| `sqlite3_trace*`, `sqlite3_profile*` | YES |
| `sqlite3_unlock_notify` | DEFER |
| `sqlite3_create_module*` (vtab) | DEFER (vtab itself deferred) |
| `sqlite3_load_extension` | DEFER |

```
[ ] Accept ABI scope above
[ ] Override:
```

### 1.7 License

- Mainline SQLite: public domain
- Turso: Apache 2.0
- Our options:

```
[ ] Apache 2.0 (matches Turso, permissive, patent grant)
[ ] MIT (simpler, no patent grant)
[ ] Public domain (Unlicense / CC0) — matches mainline ethos
[ ] Dual MIT/Apache (Rust ecosystem norm)
[ ] Other:
```

**My pick:** Apache 2.0 — patent grant is genuinely useful and the LEAP methodology may itself have patentable angles you want to protect later.

### 1.8 Versioning

```
[ ] v1.0.0 SemVer, our own version line; file format claims 3.x compat (mainline)
[ ] v3.45.0 (mirror mainline's version stream, signal compat)
[ ] Other:
```

**My pick:** v1.0.0 SemVer. Mirroring mainline's version is confusing and implies we're a fork (we're not).

### 1.9 Naming / branding

```
Project name (currently "sqlite-leap"):
[ ] sqlite-leap (current, descriptive)
[ ] leap-sql
[ ] alephdb
[ ] safitudo-sql
[ ] Other:

Tagline (one sentence positioning):
[ ] "SQLite-compatible SQL engine, in your language."
[ ] "Five SQL engines from one specification."
[ ] "The LEAP-built SQLite alternative."
[ ] Custom:
```

```
LEAP positioning on the homepage:
[ ] Lead with "LEAP project" — methodology is the headline
[ ] Lead with the SQL engine, mention LEAP as differentiator
[ ] Custom:
```

### 1.10 Platforms

```
Required at v1.0 (mark all):
[ ] macOS arm64
[ ] macOS x86_64
[ ] Linux x86_64
[ ] Linux arm64
[ ] Windows x86_64
[ ] WASM (browser + node + bun + deno)
[ ] iOS (XCFramework)
[ ] Android (AAR)

Defaults: macOS arm64, Linux x86_64, WASM. Linux arm64 + Windows x86_64 if cross-compile is clean (no per-platform engineering).
```

### 1.11 Reporting / check-in cadence

```
[ ] Weekly written progress report from me (every Friday)
[ ] After each phase milestone (no calendar)
[ ] Slack me on big wins / big blockers only
[ ] Other:
```

**My pick:** weekly written progress report + immediate ping on blockers requiring decision.

### 1.12 Escape conditions — when do I stop and ask?

These are the conditions where I will halt and surface a decision rather than proceed. Add/remove/edit:

- Spec gap that requires a substantive design decision (not "is X allowed", but "should X work this way or that way")
- Phase slips by more than 50% beyond estimate
- Cross-target divergence I can't resolve via spec promotion within 2 attempts
- Any decision touching: licensing, distribution surface, naming, public API shape
- Any hardware/cloud spend over $X (set X — recommendation: $50/month total for CI)
- Discovery of a critical correctness bug class (e.g., crashes on a common workload)
- External communications (any tweet/post/PR comment going public)

```
$ X (cloud/CI budget per month):
[ ] $0  [ ] $50  [ ] $200  [ ] Other:

Add:
Remove:
```

---

## Section 2 — Test/benchmark plan

Once decisions above are mine, the plan becomes deterministic. Outline:

### 2.1 Correctness suite

| Test | Source | Frequency |
|---|---|---|
| sqllogictest full corpus | already vendored | every spec change |
| Mainline TCL subset (~30 files) | port from mainline tcl/ | every spec change |
| 5-target cross-equivalence | parts/eq-harness/ | every spec change |
| File-format roundtrip (mainline writes / leap reads + reverse) | every spec change |
| Fuzz corpus (parser + file-format) | continuous on Linux CI |
| Property-based tests (SQL queries → consistent results) | weekly |

### 2.2 Performance suite

| Lane | Workload | Pass bar |
|---|---|---|
| 1 | cold start | within 80% of mainline |
| 2 | parse speed (lib mode) | within 50% of mainline |
| 3 | SELECT in-memory (incl. predicate-pushdown variants) | within 50% of mainline |
| 4 | INSERT throughput (file + prepared) | within 50% of mainline |
| 5 | binary size | beat mainline (matching feature surface) |
| 6 | memory footprint | within 110% of mainline |
| 7 | prepared-statement reuse | beat mainline (we already do) |
| 8 | rollback / savepoint cost | within 100% of mainline |
| 9 | BLOB read/write throughput | within 100% of mainline |
| 10 | TPC-C subset (10 warehouses, 60s) | within 50% of mainline |
| 11 | sysbench OLTP read-only (10 tables × 100k rows) | within 50% of mainline |
| 12 | sysbench OLTP read-write | within 50% of mainline |
| 13 | Multi-reader stress (4 readers + 1 writer × 60s) | zero corruption |
| 14 | Fault injection (kill -9 mid-write × 1000) | 100% recovery |

All run on macOS arm64 + Linux x86_64. Both report.

### 2.3 Reporting format

For each release candidate, a `bench/results/<date>-RC<N>.md` containing:
- Headline 5-target perf matrix (Lanes 1-9)
- Real-workload table (Lanes 10-14)
- Correctness pass rates (file-level + record-level, both incl/excl SKIP)
- Regen-debt count + trend
- Cross-target divergences (should be zero)
- Comparison vs Turso (where measurable) and vs previous RC

---

## Section 3 — Execution roadmap

Phased plan. Each phase is autonomous-runnable with weekly progress report.

### Phase A — Engine infrastructure (Weeks 1-2)

- A.1: Page cache (LRU, configurable, dirty-list)
- A.2: Phase 4c multi-process WAL (shm + wal-index)
- A.3: Phase 4a multi-frame recovery wired into open
- A.4: Real PRAGMA synchronous + journal_mode semantics
- A.5: Lock escalation (DEFERRED/IMMEDIATE/EXCLUSIVE)
- A.6: Connection pooling

Deliverable: durability claim defensible. Crash recovery works. Multi-process safe.

### Phase B — Triggers + FK enforcement (Week 3)

- B.1: Trigger spec (BEFORE/AFTER, FOR EACH ROW, INSTEAD OF on views)
- B.2: FK enforcement using trigger machinery (CASCADE/SET NULL/RESTRICT)
- B.3: 5-target emission

Deliverable: ORM-compatible.

### Phase C — Other features (Week 4)

- C.1: Savepoints
- C.2: ATTACH/DETACH DATABASE
- C.3: JSON1 real implementation (~12 functions)
- C.4: Authorizer + hooks
- C.5: Backup API
- C.6: Online VACUUM
- C.7: PRAGMA expansion (~80 pragmas)
- C.8: Window functions full surface
- C.9: Generated STORED columns

Deliverable: feature surface ~80% of mainline by weighted count.

### Phase D — sqlite3_* C ABI shim (Week 5)

- D.1: Core 30 functions (open/close/prepare/step/finalize/bind_*/column_*)
- D.2: sqlite3_value_*, sqlite3_result_*, custom functions
- D.3: Backup API entry points
- D.4: BLOB incremental I/O
- D.5: Mutex / status / trace stubs

Deliverable: drop-in C ABI replacement (with documented exceptions for vtab/loadable-ext).

### Phase E — Test bar (Week 6)

- E.1: Mainline TCL subset port + run
- E.2: TPC-C subset harness
- E.3: sysbench OLTP harness
- E.4: Fault injection harness
- E.5: Multi-process stress harness
- E.6: Continuous fuzzing setup
- E.7: Linux x86_64 + arm64 + Windows cross-build validation

Deliverable: all test-bar thresholds met or known-and-explained.

### Phase F — Regen-debt sweep (Week 7)

- F.1: Probe 50-80 leaves systematically
- F.2: Promote target-local fixes that should be spec-borne
- F.3: Verify cross-target regen produces identical behavior
- F.4: Publish regen-debt count (target: ≤5 documented exceptions)

Deliverable: spec-faithfulness guarantee strong enough to claim "anyone can regen this from spec."

### Phase G — Packaging + docs (Week 8)

- G.1: Rust crate publish
- G.2: C lib + sqlite3_*-compat shim
- G.3: Python wheel
- G.4: Go module
- G.5: Zig package
- G.6: WASM npm package
- G.7: Documentation site (one site, multi-language quick-starts)
- G.8: Migration-from-mainline guide
- G.9: LEAP methodology white paper

Deliverable: every target installable in one command.

### Phase H — Polish + soft launch (Weeks 9-10)

- H.1: Public preview release (RC)
- H.2: Issue tracker open, accepting bug reports
- H.3: Two weeks of polish based on early feedback
- H.4: v1.0 launch

Deliverable: production-ready release.

### Buffer (Weeks 11-12)

Slack for the unexpected — discovery of complexity, slipping phases, design pivots. If used: pushes v1.0 to week 12 instead of week 10. If not used: faster launch.

---

## Section 4 — What I won't do without you

(See §1.12 — escape conditions.) Restated for clarity:

- Touch licensing, distribution surface, naming, public API shape — escalate
- Spend money on infrastructure beyond your set budget — escalate
- Communicate publicly (tweet, blog, GitHub announcement, PR comment to upstream) — escalate
- Make a substantive design decision that significantly changes the product (e.g., "let's add FTS5 after all") — escalate
- Slip a phase by more than 50% without flagging — escalate

Everything else: I run autonomously, report weekly.

---

## Section 5 — One open question I need you to think about

**Are we trying to be Turso-replacing, or Turso-coexisting?**

Two postures:

- **Replace Turso.** Aim for every workload Turso targets, beat them on the differentiator (5 idiomatic implementations vs their one Rust). Marketing: "Turso, but for any language."
- **Coexist with Turso.** Different angle (multi-language) targeting different users. Marketing: "If you're a Rust shop, use Turso. If you're a Go/Python/C shop or a polyglot org, use sqlite-leap."

The work is similar; the framing is different and affects later decisions (do we pursue parity on async/io_uring, which is Turso's headline? Do we benchmark against them aggressively or treat them as sister project?).

```
[ ] Replace Turso
[ ] Coexist with Turso
[ ] Don't decide yet — circle back at Phase H
```

---

## Sign-off

```
Date answered: ____________
Signed (Stan): ____________
```

Once this is filled in, I have everything I need. Phase A starts the next session.

---

## Sign-off — autonomous execution authorized 2026-04-26

**Decision:** maximum scope — every YES, every DEFER also YES. "Blow everything out of the water."

- All features in scope: triggers (incl. INSTEAD OF), FK enforcement, savepoints, ATTACH/DETACH, JSON1, **virtual tables**, **FTS5**, **R-tree**, **encryption**, authorizer/hooks, **loadable extensions**, backup API, online + **incremental VACUUM**, full PRAGMA, window full surface, generated STORED, **WITHOUT ROWID**.
- All engine infra: page cache, multi-process WAL (4c), crash recovery wired, real PRAGMA semantics, lock escalation, **shared cache mode**.
- All platforms: macOS arm64+x86_64, Linux x86_64+arm64, **Windows x86_64**, WASM (browser/node/bun/deno), **iOS XCFramework**, **Android AAR**.
- Full sqlite3_* C ABI shim including vtab + loadable extensions surface (since features are in).
- License: Apache 2.0. Versioning: v1.0.0 SemVer.
- Test bar as specified.
- Reporting: weekly + immediate on blockers.
- CI/cloud budget: $50/month.
- Held for non-autonomous decision: project name, tagline, LEAP positioning (surface at Phase G).

Estimated total: ~14-20 weeks at LEAP pace.
