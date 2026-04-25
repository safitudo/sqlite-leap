#!/bin/bash
# Build tests/fixtures/tiny_split.db: a deterministic mainline-SQLite fixture
# pre-filled with rows so that the NEXT insert via fileformat_split_runner
# triggers root-split.
#
# Page size = 4096 (mainline default). With reserved=12 bytes/page (mainline
# default), usable=4084. Rows of shape (id INTEGER PRIMARY KEY, name TEXT, age
# INTEGER) where name='row<i>' (4..6 chars), age in [20,79], cell size ~14-16
# bytes. Empirically the leaf root holds 269 such rows; the 270th triggers
# split. We pre-fill with 269.
#
# Usage: bash tests/fixtures/build_split_fixture.sh [output_path]
# Default output: tests/fixtures/tiny_split.db

set -euo pipefail

OUT="${1:-tests/fixtures/tiny_split.db}"
PREFILL=269

rm -f "$OUT"
sqlite3 "$OUT" "CREATE TABLE t(id INTEGER PRIMARY KEY, name TEXT, age INTEGER);"

SQL="BEGIN;"
for i in $(seq 1 $PREFILL); do
    AGE=$((20 + i % 60))
    SQL="$SQL INSERT INTO t VALUES (NULL, 'row${i}', $AGE);"
done
SQL="$SQL COMMIT;"
sqlite3 "$OUT" "$SQL"

PAGES=$(sqlite3 "$OUT" "PRAGMA page_count;")
ROWS=$(sqlite3 "$OUT" "SELECT count(*) FROM t;")
SIZE=$(stat -f%z "$OUT" 2>/dev/null || stat -c%s "$OUT")

echo "built $OUT: rows=$ROWS pages=$PAGES size=$SIZE"
if [ "$PAGES" -ne 2 ]; then
    echo "ERROR: expected page_count=2 (one sqlite_master + one leaf root for t), got $PAGES" >&2
    echo "       fixture would not exercise root-split on next insert" >&2
    exit 1
fi
