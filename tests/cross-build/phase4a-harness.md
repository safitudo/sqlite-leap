# Phase 4a test harness — language-neutral spec

Phase 4a adds the WAL read-side open protocol: detection of `<path>-wal`, validation of the 32-byte header, error raising for corrupt / wrong-page-size / wrong-format / truncated headers, absorption + unlink of an empty (zero-frame) WAL. Frame-overlay with real committed frames is covered out-of-band by `tests/roundtrip_wal_readside.py` (Python, uses mainline sqlite3 as oracle; deferred).

**`max_invariant = 42` unchanged.** No new VDBE opcodes.

## Invocation

```
<harness-binary> <path-to-phase4a.json>
```

Generated into `src-{lang}/bin/phase4a-test`.

## Additions vs phase3d-harness.md

Two new case-level fields:

- `preload_wal_hex` (optional, disk-only): hex bytes written to `<path>-wal` BEFORE the first open. No padding — EXACTLY these bytes. If absent, no WAL sidecar is created.
- `wal_absent_after_open` (optional, bool): when present on an expect-block, the harness additionally checks that `<path>-wal` does NOT exist at that point. Pins the unlink-after-checkpoint contract.

## Output

```
SUMMARY phase=4a target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.

## Gate

All 6 phase4a cases green on both C and Rust builds. Plus: every prior phase (1 through 9g) remains green as a regression check. Byte-identical output where the harness emits result bytes.

## Errors (new)

The implementation must emit, by NAME, these conditions with the exact spellings:

- `STORAGE_WAL_CORRUPT_HEADER` (raised on bad magic, bad format version, bad page size, or truncated header).
- `STORAGE_WAL_ORPHANED` (WAL sidecar exists but main DB absent / invalid; not covered by a fixture in phase4a.json because it conflicts with the fresh-create codepath — covered in the Python roundtrip harness).
- `STORAGE_WAL_CHECKSUM_MISMATCH` — spec section defines it but per spec it is NOT a hard error ("treated as 'truncated WAL', not as error"); NO fixture in phase4a.json raises it.

## Scope cuts (Phase 4a MVP)

Fixture-level coverage is intentionally scoped to what is byte-accurate without computing Fibonacci checksums:
- Empty-WAL + error paths.

NOT in phase4a.json:
- Real frame overlay (requires valid Fibonacci-checksummed frame bodies matching the DB's existing page images).
- Multi-frame / commit-marker-on-last tests.
- Salt-mismatch-rejects-frame.
- Checksum-mismatch-truncation behaviour.
- Orphan-WAL (WAL without main DB).

All of the above are tested by `tests/roundtrip_wal_readside.py` (Python-driven, mainline sqlite3 as oracle). That harness is deferred to a follow-up session.

## Implementation contract

1. On open, after the Phase 3d `<path>.leap-stage` cleanup step, BEFORE reading `<path>`, check for `<path>-wal`.
2. If `<path>-wal` exists:
   a. Read the first 32 bytes. If fewer than 32 bytes exist, raise `STORAGE_WAL_CORRUPT_HEADER`.
   b. Validate magic (`0x377f0682` or `0x377f0683`). If neither, raise `STORAGE_WAL_CORRUPT_HEADER`.
   c. Validate format version (must equal `3007000` = `0x002de098`). If not, raise `STORAGE_WAL_CORRUPT_HEADER`.
   d. Validate page size (must equal the main DB's page size, 4096 in v1). If not, raise `STORAGE_WAL_CORRUPT_HEADER`.
   e. If the file is exactly 32 bytes (zero frames), proceed to step 4 below with an empty page-index map. If longer, frame-walking per spec § "Committed-frame recovery rule" — deferred in the MVP to future implementation work (current fixture doesn't exercise this path; engine MAY choose to read-and-ignore frames or raise a NOT_IMPLEMENTED error that's mapped by the harness to skip).
3. Read `<path>` per Phase 3d open protocol.
4. Overlay any committed frames onto the in-memory image (no-op for zero-frame WAL).
5. Checkpoint: write merged in-memory image back to `<path>` via Phase 3d atomic-rename. On success, unlink `<path>-wal`.

The MVP implementation may refuse (raise an internal not-implemented condition) any WAL with more than 0 frames; the phase4a fixture doesn't exercise multi-frame paths. The full implementation ships in the next session alongside the Python roundtrip harness.
