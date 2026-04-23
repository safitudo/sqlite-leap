# Phase 4b test harness — language-neutral spec

Phase 4b adds WAL write-side + incremental commit. This harness extends the Phase 4a harness conventions to:

1. Set `LEAP_WAL_APPEND=1` and `LEAP_WAL_SALT_OVERRIDE=<16-hex>` for the case so that produced WAL bytes are deterministic across runs and targets.
2. Inspect the produced `<path>-wal` file after write steps and compare its full byte contents to a case-declared `expected_wal_hex`.
3. Inspect the main DB file (`<path>`) after close and verify the checkpoint absorbed the WAL (main DB contains the merged bytes; `<path>-wal` is unlinked).
4. Inject deliberately-malformed WAL bytes to exercise the recovery / discard paths.

The harness is generated into `src-{lang}/bin/phase4b-test`. Prior phase suites (1 through 9g, 4a) MUST remain green as a regression check.

## Invocation

```
<harness-binary> <path-to-phase4b.json>
```

The harness itself sets the environment for each case; callers do NOT set `LEAP_WAL_APPEND` or `LEAP_WAL_SALT_OVERRIDE` from outside.

## New case-level fields

All Phase 4a fields remain valid. Phase 4b adds:

- `wal_append` (bool, default true) — if true, the harness sets `LEAP_WAL_APPEND=1` for the duration of this case. If false, Phase 3d slurp-commit behaviour is expected (for regression cases that must keep working alongside Phase 4b).
- `wal_salt_hex` (string, required when `wal_append=true`) — 16 hex characters. The first 8 decode as salt-1 (big-endian u32); the last 8 decode as salt-2. Passed to the engine via `LEAP_WAL_SALT_OVERRIDE`.
- `inspect_after_close` (object, optional) — pins post-close artifact state.
  - `wal_absent` (bool) — assert `<path>-wal` does not exist.
  - `main_db_has_page_count` (int) — assert the main DB file, on disk, has exactly `page_count * 4096` bytes. Guards against over/under-truncation after checkpoint.
- `inspect_wal_after_commit` (array of strings) — names of commits whose full WAL contents should be recorded for later comparison. The harness matches each entry against case-steps that carry an explicit `commit_label` annotation (see "New step kinds" below). Each matching commit produces one hex snapshot; the snapshots are compared to the case's `expected_wal_hex_by_commit` map.
- `expected_wal_hex_by_commit` (object, optional) — map `commit_label -> expected_hex`. If missing, WAL bytes are not byte-compared.

## New step kinds

- `{"commit_label": "<label>"}` — a synthetic step that does not execute SQL. Instead it:
  1. Closes the DB (triggering all accumulated WAL commits to flush — see note on commit-unit below).
  2. Reads `<path>-wal` into memory.
  3. Records the bytes under `<label>`.
  4. Reopens the DB and continues. The reopen runs the Phase 4a + 4b recovery walk against the just-written WAL, checkpoints into the main DB, and unlinks the WAL. So subsequent steps start with a clean WAL — then any new mutations produce a fresh WAL against the new salts (the harness re-sets `LEAP_WAL_SALT_OVERRIDE` to the same value, so fresh salts are still deterministic).

Note on commit-unit: Phase 4b v1's unit of commit is `close_database`; a single `close_database` call emits one "commit" spanning all in-session mutations. Therefore `commit_label` = "a labelled close+snapshot". A case with two `commit_label` steps exercises the two-commit recovery path.

- `{"preload_wal_hex": "<hex>"}` (step-level, disk-only) — overrides `<path>-wal` with the given bytes mid-program (without reopening). Used for the crash-recovery simulation cases.

## New expectations (on existing steps)

Any SQL step's `expect` block may add:

- `wal_frame_count` (int) — after this step runs, `<path>-wal` exists and contains exactly this many 4120-byte frames (24-byte header + 4096-byte body) past its 32-byte header. Equivalent expression: `filesize(<path>-wal) == 32 + 4120 * wal_frame_count`.
- `wal_last_commit_page_count` (int) — the last frame present in `<path>-wal` has `db_size_after_commit == wal_last_commit_page_count`.

Both fields are introspective — the harness reads the WAL bytes and inspects them; the engine does not need to surface anything new via its public API.

## Output

Per case: `PASS <case.name>` or `FAIL <case.name> at step <idx>: <reason>`. Final line:

```
SUMMARY phase=4b target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.

## Cross-build equivalence gate

Both targets' `phase4b-test` binaries MUST:

- Emit identical PASS/FAIL verdicts per case.
- Produce WAL bytes that match `expected_wal_hex_by_commit` byte-for-byte. (Byte-identity is the core Phase 4b cross-build gate.)
- Produce identical main DB bytes after checkpoint (implicitly verified by the phase3d/3b regression suite run against the post-checkpoint file).

## Non-goals

- Mainline-cooperative roundtrip. That is covered by `tests/roundtrip_wal_writeside.py` (Python, out-of-band, uses mainline `sqlite3` as the oracle; deferred to a follow-up session).
- Crash-injection between frame-writes and fsync. v1 exercises the "WAL contains an uncommittable tail" path via `preload_wal_hex` with hand-truncated bytes, which is equivalent to the unflushed-frames crash state from the recovery walker's point of view.
