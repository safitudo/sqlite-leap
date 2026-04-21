# Phase 3d test harness — language-neutral spec

Identical to `phase3b-harness.md` except for one additional disk-case field.

## Invocation

```
<harness-binary> <path-to-phase3d.json>
```

Generated into `src-{lang}/bin/phase3d-test` (or the target's equivalent).

## New field: `preload_staging_hex`

Disk-only. If present on a case, the harness:

1. Decodes the hex to bytes (no separators, no `0x` prefix, case-insensitive).
2. Writes them at offset 0 of `<path>.leap-stage` (same directory as `<path>`, `<path>` being the per-case temp DB path).
3. Zero-pads `<path>.leap-stage` to at least 4096 bytes on disk (matching Phase 3a's preload_hex convention).
4. Proceeds with the normal open protocol: `open_database(<path>)`. The on-disk backend's commit protocol (per `spec/durability.spec.md` § "Open protocol") is expected to unlink `<path>.leap-stage` as its first step. The harness does NOT pre-unlink.

At case end, the harness cleans up `<path>` AND `<path>.leap-stage` if still present.

## Step kinds

All Phase 3a/3b step kinds are supported: `sql`, `reopen`, `bulk_insert_int_range`, `rows_int_range`, `row_count`. No new step kinds.

## Well-formedness invariants

Unchanged from Phase 2c-3: the 13 invariants. Phase 3d introduces no opcodes.

## Equality rules

Unchanged from Phase 3b.

## Output

Per case: `PASS <case.name>` or `FAIL <case.name> at step <idx>: <reason>`. Final line:

```
SUMMARY phase=3d target=<c|rust|wasm> passed=<int> failed=<int> total=<int>
```

Exit 0 iff `failed == 0`, else 1.

## Non-goals

- Explicit crash-injection between commit protocol steps (would require fault-injection, process-kill, or filesystem mocking — Phase 3d validates the PROTOCOL, not the filesystem's behaviour). Crash-correctness is ensured by the step-by-step state table in `spec/durability.spec.md`.
- Concurrent-writer tests — Phase 3d is single-writer only.
