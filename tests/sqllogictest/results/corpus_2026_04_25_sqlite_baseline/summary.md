# Mainline-sqlite corpus baseline

Driver: /usr/bin/sqlite3 via Python sqlite3 module (system version)
Files sampled: 186
Per-file timeout: 60s

## Aggregate (record-level)

| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP rate | excl-SKIP rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| sqlite (mainline) | 1655199 | 19 | 0 | 134851 | 1790069 | 92.47% | 100.00% |

Timeouts: 0
Crashes: 0

## Top FAIL reasons

- 13	OperationalError: no such table: t1
- 3	got(<n>)=['<s>'] expected(<n>)=['<s>']
- 1	OperationalError: integer overflow
- 1	expected error, got success
- 1	OperationalError: no such trigger: t1r1