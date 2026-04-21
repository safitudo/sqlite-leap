#!/usr/bin/env bash
# Placeholder: verify that a given SQLite DB file yields identical query
# results under both the C and Rust builds of sqlite-leap (and ideally
# also matches mainline sqlite's output on a deterministic workload).
#
# Intended contract (to be implemented in Phase 8):
#   roundtrip.sh <path-to-db>
#     1. Run a fixed workload (schema introspection + SELECT * ORDER BY
#        rowid on every user table) against the DB using
#        src-c/bin/sqlite-leap.
#     2. Run the same workload using src-rust target's sqlite-leap binary.
#     3. Run the same workload against mainline sqlite3 as the oracle.
#     4. Diff the three outputs. Exit 0 only if all three match.
#
# Not wired up this session. Left as a stub so the directory layout is
# complete and the campaign driver has a call site.

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <path-to-db>" >&2
    exit 2
fi

DB_PATH="$1"

if [[ ! -f "$DB_PATH" ]]; then
    echo "roundtrip: $DB_PATH does not exist" >&2
    exit 2
fi

echo "TODO: implement three-way roundtrip (C, Rust, mainline oracle) for: $DB_PATH" >&2
echo "See tests/fuzz/README.md and tests/fuzz/file-format/fetch-seeds.sh" >&2
exit 1
