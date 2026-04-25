# Lane 5 — 5-target binary size

Generated 2026-04-25T09:16:56Z on Darwin arm64.
Mainline sqlite3 baseline: `/usr/bin/sqlite3` = 4690560 bytes (4580.6 KB).

Each row builds the same SELECT behavioral smoke (parser + compiler + VDBE + storage)
with the smallest-binary flags available in that toolchain.

| target | bytes | KB | vs sqlite3 mainline | notes |
|---|---:|---:|---:|---|
| c | 157752 | 154.1 | 0.03x | gcc -Os -ffunction-sections + dead-strip + strip |
| rust | 536032 | 523.5 | 0.11x | cargo --profile release-small |
| zig | 2449864 | 2392.4 | 0.52x | zig build -Doptimize=ReleaseSmall + strip |
| go | 2344898 | 2289.9 | 0.50x | go build -trimpath -ldflags '-s -w' |
| python | 553975 | 541.0 | 0.12x | .py source only; interpreter python3.10 = 33816 bytes (excluded) |
| sqlite3 (mainline) | 4690560 | 4580.6 | 1.00x | system `3.51.0` |

**Smallest binary target:** c at 157752 bytes (154.1 KB).
**C target beats mainline sqlite3:** YES (0.03x of mainline).

Notes:
- Python is reported as engine-package `.py` source bytes; the CPython interpreter
  (python3.10, 33816 bytes) is NOT bundled and not counted.
- Mainline sqlite3 includes the CLI shell, readline, ICU shim — apples-to-oranges
  vs leap-sqlite which only embeds the engine; we report it as published.
- All builds invoked from this script are reproducible: see source for flags.
