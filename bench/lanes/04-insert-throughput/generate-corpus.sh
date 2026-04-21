#!/usr/bin/env bash
# Generate a deterministic corpus for lane 4 (INSERT throughput).
# Emits workload.sql: WAL pragmas + schema + 100 000 INSERTs in one txn.
# Rows are (id, payload TEXT) with 32-byte payloads — small enough that
# throughput isn't dominated by memcpy, large enough to exercise the page
# writer.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUT="$SCRIPT_DIR/workload.sql"
ROWS=100000

python3 - "$OUT" "$ROWS" <<'PY'
import random, sys, string
out_path, rows = sys.argv[1], int(sys.argv[2])
rng = random.Random(0xBEEFCAFE)
alpha = string.ascii_letters + string.digits
with open(out_path, "w") as f:
    f.write("PRAGMA journal_mode=WAL;\n")
    f.write("PRAGMA synchronous=NORMAL;\n")
    f.write("CREATE TABLE t (id INTEGER PRIMARY KEY, payload TEXT);\n")
    f.write("BEGIN;\n")
    for i in range(rows):
        pad = "".join(rng.choices(alpha, k=32))
        f.write(f"INSERT INTO t (id, payload) VALUES ({i}, '{pad}');\n")
    f.write("COMMIT;\n")
print(f"wrote {out_path}: {rows} inserts, WAL mode", file=sys.stderr)
PY
