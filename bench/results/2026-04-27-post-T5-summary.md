# Bench summary — 2026-04-27 post-T5 (post JSON1+enc+fts5+savepoint+vtab)

Mac arm64 (StanislacStudio). leap-c built release-small profile. Mainline = system sqlite3.

| Lane | leap-c | leap-rust | mainline | verdict (leap-c vs mainline) |
|------|--------|-----------|----------|------------------------------|
| 1 cold-start | 3.19 ms | 3.68 ms | 8.59 ms | **WIN 2.7×** |
| 2 parse-speed | 11.88 MB/s | 0.67 MB/s | 2.88 MB/s | **WIN 4.1×** (rust LOSES 4.3×) |
| 3 select | 1,113,657/s | 749,901/s | 506,740/s | **WIN 2.2×** (rust **WIN 1.5×**) |
| 4 insert | 180,050/s | 80,494/s | 702,985/s | LOSE 3.9× (down from 34× in 04-20) |
| 5 binary-size | 369 KB | 1.91 MB | 1.22 MB | **WIN 3.3×** (rust LOSES 1.6×) |
| 6 memory | 2.10 MB | 1.95 MB | 2.72 MB | **WIN 1.3×** (rust **WIN 1.4×**) |

leap-c wins 5 of 6 lanes vs mainline. leap-rust wins 3 of 6.

vs 2026-04-20 publication: lane 3 was LOSE 80× → now WIN 2.2× (Lane 3 attack worked: PK index, predicate-pushdown).
Lane 4 was LOSE 34× → now LOSE 3.9× (Lane 4 attack worked: prepared-statement cache).
Other lanes unchanged.

Turso comparison NA (binaries not available in this run).

Raw CSV: `bench/results/2026-04-27-StanislacStudio.csv`.
