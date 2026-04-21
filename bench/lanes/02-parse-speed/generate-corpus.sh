#!/usr/bin/env bash
# Generate a deterministic ~10 MiB SQL file used by lane 2 (parse speed).
#
# Contents are a mix of statement types (CREATE, INSERT, SELECT with joins,
# UPDATE, DELETE) so parse cost isn't dominated by one hot path. Same seed
# => same bytes on every host => every target parses the same input.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUT="$SCRIPT_DIR/corpus.sql"
TARGET_BYTES=$((10 * 1024 * 1024))   # 10 MiB

python3 - "$OUT" "$TARGET_BYTES" <<'PY'
import random, sys, os
out_path, target = sys.argv[1], int(sys.argv[2])
rng = random.Random(0xDEADBEEF)

TEMPLATES = [
    "CREATE TABLE t{i} (id INTEGER PRIMARY KEY, a INT, b TEXT, c REAL);",
    "INSERT INTO t{i} (id, a, b, c) VALUES ({n1}, {n2}, 'row_{n3}', {f});",
    "SELECT a, b, c FROM t{i} WHERE a > {n1} AND b LIKE 'row_%' ORDER BY id LIMIT {n2};",
    "SELECT t{i}.id, t{j}.a FROM t{i} JOIN t{j} ON t{i}.a = t{j}.id WHERE t{j}.c < {f};",
    "UPDATE t{i} SET b = 'r_{n1}', c = c + {f} WHERE id = {n2};",
    "DELETE FROM t{i} WHERE a = {n1} AND b = 'row_{n2}';",
    "BEGIN; INSERT INTO t{i} (a, b, c) VALUES ({n1}, 'x', {f}); COMMIT;",
    "CREATE INDEX idx_t{i}_a ON t{i}(a, b);",
    "SELECT COUNT(*), AVG(c), MAX(a) FROM t{i} GROUP BY b HAVING COUNT(*) > {n1};",
    "WITH r AS (SELECT id, a FROM t{i} WHERE a > {n1}) SELECT * FROM r WHERE id < {n2};",
]

with open(out_path, "w") as f:
    written = 0
    while written < target:
        tpl = rng.choice(TEMPLATES)
        line = tpl.format(
            i=rng.randint(0, 63),
            j=rng.randint(0, 63),
            n1=rng.randint(0, 1_000_000),
            n2=rng.randint(0, 1_000_000),
            n3=rng.randint(0, 1_000_000),
            f=round(rng.uniform(-1000, 1000), 4),
        ) + "\n"
        f.write(line)
        written += len(line)

print(f"wrote {written} bytes to {out_path}", file=sys.stderr)
PY
