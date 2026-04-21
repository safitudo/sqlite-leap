#!/usr/bin/env bash
# Generate a tiny (~64 KiB) on-disk corpus used by lane 6 (memory footprint).
# Two artifacts:
#   * small-db.sql — schema + 500 small rows; used to *materialize* small-db.sqlite
#   * workload.sql — open small-db.sqlite, run SELECT count(*), sleep 50ms
#
# The small DB is produced once by running `sqlite-mainline` against
# small-db.sql; the resulting file is checked into the corpus so every
# target reads the same bytes.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

cat > "$SCRIPT_DIR/small-db.sql" <<'SQL'
CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);
BEGIN;
SQL

python3 - "$SCRIPT_DIR/small-db.sql" <<'PY'
import sys
p = sys.argv[1]
with open(p, "a") as f:
    for i in range(500):
        f.write(f"INSERT INTO t (id, v) VALUES ({i}, 'small_row_{i:04d}');\n")
    f.write("COMMIT;\n")
PY

# Materialize small-db.sqlite if the mainline baseline is available. Users
# who haven't run fetch-baselines.sh yet will get a warning; the lane will
# skip gracefully at measurement time.
BASELINE="$SCRIPT_DIR/../../baselines/bin/sqlite-mainline"
DB="$SCRIPT_DIR/small-db.sqlite"
if [[ -x "$BASELINE" ]]; then
    rm -f "$DB"
    "$BASELINE" "$DB" < "$SCRIPT_DIR/small-db.sql"
    echo "materialized $DB ($(wc -c <"$DB") bytes)" >&2
else
    echo "skipped materializing $DB — run bench/baselines/fetch-baselines.sh first" >&2
fi

cat > "$SCRIPT_DIR/workload.sql" <<'SQL'
SELECT count(*) FROM t;
SQL
