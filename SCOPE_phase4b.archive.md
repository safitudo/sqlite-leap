# ARCHIVED — Phase 4b is landed (2026-04-23)

This file originally deferred Phase 4b as out of scope for the
2026-04-20 autonomous run. Phase 4b is now landed:

- Spec: `spec/wal.spec.md` § "Phase 4b"
- Fixture: `tests/cross-build/phase4b.json` (6/6 green on both C and Rust)
- Harness: `src-{c,rust}/bin/phase4b-test` (built by `generators/{c,rust}/`)
- Bench harness update: `bench/lanes/04-insert-throughput/run.sh` now sets
  `LEAP_DB_PATH=<tmpdir>/db.sqlite` and `LEAP_WAL_APPEND=1` for leap
  targets, putting them in the same disk-backed WAL-mode pool as mainline
  and turso.
- Re-measurement: `bench/results/2026-04-23-lane4-phase4b.{csv,README.md}`
  — numbers are essentially unchanged vs the 2026-04-20 baseline because
  the workload is a single 100k-insert transaction (one commit → one
  frame batch), which doesn't exercise the Phase 4b-vs-Phase 3d cost
  differential. Lane 4 loss vs mainline is VDBE CPU, not WAL I/O.

See the README alongside the new CSV for the honest framing: Phase 4b is
an architectural milestone (correctness, compat, multi-commit recovery)
rather than a benchmark win on this particular workload. Sub-lane 4b
(many-commits workload) is the right place for Phase 4b's benchmark
story and is listed as open scope.

The three original blockers from this file are resolved:

1. **Lane 4 harness in-memory DB** — resolved by `LEAP_DB_PATH` env var
   support in the sqllogictest runner (spec: `spec/sqllogictest-runner.spec.md`
   § "Backend selection — LEAP_DB_PATH") and the lane 4 run.sh update.
2. **Phase 4a multi-frame WAL reader stub** — resolved by the multi-frame
   recovery implementation required by Phase 4b's reopen contract.
3. **Database single-bool `dirty`** — resolved by the snapshot-diff
   dirty-set approach documented in `spec/wal.spec.md` § "Pager dirty-set".

This file is kept for historical trail; do not use it as authoritative
scope going forward. Dashboards and publication materials should read
from `DASHBOARD.md`.
