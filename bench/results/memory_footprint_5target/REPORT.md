# Lane 6 — 5-target memory footprint

Generated 2026-04-28T05:34:18Z on Darwin arm64.

Peak resident set size (`maximum resident set size` from
`/usr/bin/time -lp`) over the lifetime of a process running a
fixed workload: `CREATE TABLE` + 1000 `INSERT`s + 1 `SELECT`.

Median of 5 samples per target.

| target | peak RSS (bytes) | KB | vs mainline | notes |
|---|---:|---:|---:|---|
| c | 3145728 | 3072.0 | 0.97x | slt_runner(c) on memory_footprint.test |
| rust | 3670016 | 3584.0 | 0.83x | slt_runner(rust) on memory_footprint.test |
| zig | 3440640 | 3360.0 | 0.89x | slt_runner(zig) on memory_footprint.test |
| go | 10174464 | 9936.0 | 0.30x | slt_runner(go) on memory_footprint.test |
| python | 30490624 | 29776.0 | 0.10x | slt_runner(python) on memory_footprint.test |
| sqlite3 (mainline) | 3063808 | 2992.0 | 1.00x | system `3.51.0` |

Ratio convention: mainline-RSS / leap-RSS. >1.0x means leap is
**lighter** (uses less memory).

## Caveats
- Peak RSS over a short-lived process — NOT "idle RSS holding the
  db open". Adding a stay-open mode would require modifying parts/,
  which is out of scope here.
- The Python row includes the CPython runtime; the leap engine code
  contributes a small fraction of that total.
- macOS arm64 `maximum resident set size` is in **bytes**; on Linux
  the same field is in KB. This script is macOS-only.

Fixtures: `bench/fixtures/memory_footprint.{test,sql}`.
