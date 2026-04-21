#!/usr/bin/env bash
# Generate a deterministic corpus for lane 3 (in-memory SELECT throughput).
# Emits workload.sql: schema + 10 000 INSERTs + 100 000 SELECTs
# (each SELECT hits one of 10 000 IDs in a deterministic rotation).
# Total: 110 000 statements, reusable across every target.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUT="$SCRIPT_DIR/workload.sql"

ROWS=10000
QUERIES=100000

python3 - "$OUT" "$ROWS" "$QUERIES" <<'PY'
import random, sys
out_path, rows, queries = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
rng = random.Random(0xFACEFEED)
with open(out_path, "w") as f:
    f.write("PRAGMA journal_mode=MEMORY;\n")
    f.write("CREATE TABLE t (id INTEGER PRIMARY KEY, value INTEGER);\n")
    f.write("BEGIN;\n")
    for i in range(rows):
        f.write(f"INSERT INTO t (id, value) VALUES ({i}, {rng.randint(0, 1_000_000)});\n")
    f.write("COMMIT;\n")
    ids = [rng.randrange(rows) for _ in range(queries)]
    for i in ids:
        f.write(f"SELECT value FROM t WHERE id = {i};\n")
print(f"wrote {out_path}: {rows} inserts + {queries} selects", file=sys.stderr)
PY
