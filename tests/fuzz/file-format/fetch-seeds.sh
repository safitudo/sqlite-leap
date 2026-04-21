#!/usr/bin/env bash
# Generate a small but varied set of SQLite database files to seed the
# file-format fuzz corpus. Uses the pinned mainline sqlite binary from
# bench/baselines/bin/sqlite-mainline as the producer (so seeds have the
# "known good" format we want to verify LEAP-SQLite roundtrips against).
#
# Outputs go into tests/fuzz/file-format/seeds/. Each DB is small
# (~1-100KB) and covers a distinct format axis:
#
#   empty.db          — no schema, default page size
#   simple.db         — one table with a few rows
#   with-index.db     — table + secondary index
#   with-view.db      — table + view over it
#   wal-mode.db       — same schema, WAL journal mode
#   page-4096.db      — pragma page_size=4096
#   page-8192.db      — pragma page_size=8192
#   multi-table.db    — multiple tables, FK reference
#   text-heavy.db     — larger TEXT columns, UTF-8 content
#   blob-small.db     — BLOB values, binary-safe roundtrip
#
# Not a fuzzer — a deterministic seed generator. Re-runs are idempotent:
# pre-existing seeds are removed first so output is always fresh.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
SEEDS_DIR="$SCRIPT_DIR/seeds"
SQLITE_BIN="$REPO_ROOT/bench/baselines/bin/sqlite-mainline"

if [[ ! -x "$SQLITE_BIN" ]]; then
    cat >&2 <<EOF
[fetch-seeds] ERROR: mainline SQLite binary not found at:
    $SQLITE_BIN

Run bench/baselines/fetch-baselines.sh first:

    bash "$REPO_ROOT/bench/baselines/fetch-baselines.sh"

That will download + build the pinned mainline amalgamation and install
the binary into bench/baselines/bin/. Then re-run this script.
EOF
    exit 2
fi

mkdir -p "$SEEDS_DIR"

# Clear previous seeds (but leave .gitkeep / README if any).
find "$SEEDS_DIR" -maxdepth 1 -type f \( -name '*.db' -o -name '*.db-wal' -o -name '*.db-shm' -o -name '*.db-journal' \) -delete

run_sqlite () {
    local db_path="$1"
    local sql="$2"
    # shell.c exits non-zero on error, so set -e catches any producer failure.
    printf '%s\n' "$sql" | "$SQLITE_BIN" "$db_path"
}

echo "[fetch-seeds] producing seeds in $SEEDS_DIR" >&2

# 1. Completely empty DB — just the header + single root page.
run_sqlite "$SEEDS_DIR/empty.db" "VACUUM;"

# 2. Simple schema with rows.
run_sqlite "$SEEDS_DIR/simple.db" "
CREATE TABLE greet (id INTEGER PRIMARY KEY, msg TEXT NOT NULL);
INSERT INTO greet (msg) VALUES ('hello'), ('world'), ('from-seed');
"

# 3. Table + secondary index.
run_sqlite "$SEEDS_DIR/with-index.db" "
CREATE TABLE person (id INTEGER PRIMARY KEY, email TEXT, age INTEGER);
CREATE INDEX idx_person_email ON person(email);
INSERT INTO person (email, age) VALUES
    ('a@ex.com', 30), ('b@ex.com', 25), ('c@ex.com', 40);
"

# 4. Table + view.
run_sqlite "$SEEDS_DIR/with-view.db" "
CREATE TABLE sales (region TEXT, amount INTEGER);
INSERT INTO sales VALUES ('east', 100), ('east', 200), ('west', 50);
CREATE VIEW sales_by_region AS
    SELECT region, SUM(amount) AS total FROM sales GROUP BY region;
"

# 5. WAL journal mode. Note: pragma journal_mode is persistent per DB.
run_sqlite "$SEEDS_DIR/wal-mode.db" "
PRAGMA journal_mode=WAL;
CREATE TABLE log (seq INTEGER PRIMARY KEY, ts TEXT, line TEXT);
INSERT INTO log (ts, line) VALUES
    ('2026-04-20T10:00:00Z', 'startup'),
    ('2026-04-20T10:00:01Z', 'ready');
"
# Checkpoint so the WAL file is merged back (makes the seed more self-contained).
run_sqlite "$SEEDS_DIR/wal-mode.db" "PRAGMA wal_checkpoint(TRUNCATE);"

# 6. Page size 4096.
run_sqlite "$SEEDS_DIR/page-4096.db" "
PRAGMA page_size=4096;
VACUUM;
CREATE TABLE small (id INTEGER PRIMARY KEY, v INTEGER);
INSERT INTO small VALUES (1, 100), (2, 200), (3, 300);
"

# 7. Page size 8192.
run_sqlite "$SEEDS_DIR/page-8192.db" "
PRAGMA page_size=8192;
VACUUM;
CREATE TABLE small (id INTEGER PRIMARY KEY, v INTEGER);
INSERT INTO small VALUES (1, 100), (2, 200), (3, 300);
"

# 8. Multiple tables with a foreign-key style reference (no FK enforcement
#    pragma — we want the schema shape, not the runtime check).
run_sqlite "$SEEDS_DIR/multi-table.db" "
CREATE TABLE author (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE book (
    id INTEGER PRIMARY KEY,
    author_id INTEGER REFERENCES author(id),
    title TEXT NOT NULL
);
INSERT INTO author (name) VALUES ('ann'), ('ben');
INSERT INTO book (author_id, title) VALUES
    (1, 'first'), (1, 'second'), (2, 'third');
"

# 9. Text-heavy payload including multi-byte UTF-8.
run_sqlite "$SEEDS_DIR/text-heavy.db" "
CREATE TABLE doc (id INTEGER PRIMARY KEY, body TEXT);
INSERT INTO doc (body) VALUES
    ('The quick brown fox jumps over the lazy dog.'),
    ('Zażółć gęślą jaźń'),
    ('いろはにほへと ちりぬるを'),
    ('Съешь же ещё этих мягких французских булок');
"

# 10. Small BLOB values.
run_sqlite "$SEEDS_DIR/blob-small.db" "
CREATE TABLE bin (id INTEGER PRIMARY KEY, payload BLOB);
INSERT INTO bin (payload) VALUES
    (x'00010203040506070809'),
    (x'deadbeefcafebabe'),
    (x'ffffffffffffffff');
"

echo "[fetch-seeds] produced:" >&2
ls -1 "$SEEDS_DIR"/*.db 2>/dev/null | while read -r f; do
    size=$(stat -f "%z" "$f" 2>/dev/null || stat -c "%s" "$f")
    printf "  %8s  %s\n" "$size" "$(basename "$f")" >&2
done

echo "[fetch-seeds] done" >&2
