# Lane 5 — 5-target binary size

Generated 2026-04-27T19:10:48Z on Darwin arm64.
Mainline sqlite3 baseline: `/Users/stanislav/miniconda3/bin/sqlite3` = 1809536 bytes (1767.1 KB).

Each row builds the same SELECT behavioral smoke (parser + compiler + VDBE + storage)
with the smallest-binary flags available in that toolchain.

| target | bytes | KB | vs sqlite3 mainline | notes |
|---|---:|---:|---:|---|
| c | 207912 | 203.0 | 0.11x | gcc -Os -ffunction-sections + dead-strip + strip |
| rust | 586112 | 572.4 | 0.32x | cargo --profile release-small |
| zig | 2879192 | 2811.7 | 1.59x | zig build -Doptimize=ReleaseSmall + strip |
| go | 2681042 | 2618.2 | 1.48x | go build -trimpath -ldflags '-s -w' |
| python | 968674 | 946.0 | 0.54x | .py source only; interpreter python3.10 = 33816 bytes (excluded) |
| sqlite3 (mainline) | 1809536 | 1767.1 | 1.00x | system `3.41.2` |

**Smallest binary target:** c at 207912 bytes (203.0 KB).
**C target beats mainline sqlite3:** YES (0.11x of mainline).

Notes:
- Python is reported as engine-package `.py` source bytes; the CPython interpreter
  (python3.10, 33816 bytes) is NOT bundled and not counted.
- Mainline sqlite3 includes the CLI shell, readline, ICU shim — apples-to-oranges
  vs leap-sqlite which only embeds the engine; we report it as published.
- All builds invoked from this script are reproducible: see source for flags.
