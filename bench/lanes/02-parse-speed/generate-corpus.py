#!/usr/bin/env python3
"""
Generate a deterministic ~10 MiB SQL corpus for lane 2 (parse speed).

Why this file exists (history)
-------------------------------
The first lane-2 corpus (see generate-corpus.sh, retained for audit) emitted
CREATE TABLE statements inline in the random-template stream. That made 83.4 %
of subsequent statements reference a table that had not yet been CREATEd at
that point in the stream (verified against the committed `corpus.slt` on
2026-04-21: 148678/178212 leap-rust FAILs, ~83 %). Those failures short-circuited
planning in the leap runner via a cheap STORAGE_TABLE_NOT_FOUND /
COMPILE_UNKNOWN_TABLE error, so leap was only doing ~17 % of the parse+plan
work mainline was doing. Lane-2 throughput therefore measured "how fast do you
reject an undefined-table reference," not parse speed. leap-rust posted 4.9×
mainline (31 MB/s vs 6.4 MB/s), which tripped the `bench/README.md` 2×
priors-violation rule.

Fix (Option A from the bench-integrity rework):
  - Pre-seed the schema: emit CREATE TABLE for all 64 tables once at the top
    of the corpus, each with 5 named columns (c1..c5) that the templates
    reference. The leap runner opens a fresh :memory: DB per file per
    `spec/sqllogictest-runner.spec.md § Isolation`, so "pre-seed" means
    "first 64 records of the corpus file," not "separate schema file."
  - Remove CREATE TABLE and CREATE INDEX from the random template pool
    (duplicate CREATE TABLE hit PARSE_UNEXPECTED_TOKEN in leap; CREATE INDEX
    is fine but not representative of a parse-heavy workload and we want
    most of the bytes to be SELECT/INSERT/UPDATE/DELETE parse work).
  - Use `INTEGER` instead of `INT` in column types — the leap SQL grammar
    spec accepts `INTEGER` but does not list bare `INT` as a type keyword.
    This is a spec-compliance fix for the corpus, not a spec change.

The generator is deterministic (seeded PRNG) and same-bytes on every host.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

OUT_DEFAULT = Path(__file__).parent / "corpus.sql"
TARGET_BYTES_DEFAULT = 10 * 1024 * 1024  # 10 MiB
NUM_TABLES = 64

# Pre-seed schema. Each table has the same shape so templates can reference
# any table by index without tracking per-table columns. The column names
# c1..c5 match the template bodies below.
PRESEED_TEMPLATE = (
    "CREATE TABLE t{i} ("
    "id INTEGER PRIMARY KEY, "
    "c1 INTEGER, "
    "c2 INTEGER, "
    "c3 TEXT, "
    "c4 REAL, "
    "c5 TEXT"
    ");"
)

# All templates reference tables that are CREATEd in the preseed block and
# only use columns defined there. These templates were probed individually
# against both leap-c and leap-rust sqllogictest runners on 2026-04-21 and
# all PASS (no PARSE_UNEXPECTED_TOKEN, no COMPILE_UNKNOWN_TABLE,
# no STORAGE_TABLE_NOT_FOUND).
TEMPLATES = [
    # Plain INSERT
    "INSERT INTO t{i} (id, c1, c2, c3, c4, c5) VALUES "
    "({n1}, {n2}, {n3}, 'row_{n4}', {f}, 'tag_{n5}');",

    # SELECT with WHERE, LIKE, ORDER BY, LIMIT
    "SELECT c1, c3, c4 FROM t{i} "
    "WHERE c1 > {n1} AND c3 LIKE 'row_%' ORDER BY id LIMIT {n2};",

    # SELECT with JOIN
    "SELECT t{i}.id, t{j}.c1 FROM t{i} JOIN t{j} "
    "ON t{i}.c1 = t{j}.id WHERE t{j}.c4 < {f};",

    # UPDATE with WHERE
    "UPDATE t{i} SET c3 = 'r_{n1}', c4 = c4 + {f} WHERE id = {n2};",

    # DELETE with WHERE
    "DELETE FROM t{i} WHERE c1 = {n1} AND c3 = 'row_{n2}';",

    # Transaction-wrapped INSERT (parser work: 3 statements instead of 1)
    "BEGIN; INSERT INTO t{i} (c1, c3, c4) VALUES ({n1}, 'x', {f}); COMMIT;",

    # Aggregation with GROUP BY HAVING
    "SELECT COUNT(*), AVG(c4), MAX(c1) FROM t{i} "
    "GROUP BY c3 HAVING COUNT(*) > {n1};",

    # CTE / WITH
    "WITH r AS (SELECT id, c1 FROM t{i} WHERE c1 > {n1}) "
    "SELECT * FROM r WHERE id < {n2};",

    # Subquery in WHERE
    "SELECT id, c1 FROM t{i} "
    "WHERE c1 IN (SELECT c1 FROM t{j} WHERE c4 > {f});",

    # Multi-column ORDER BY
    "SELECT id, c1, c3 FROM t{i} ORDER BY c1 DESC, c3 ASC LIMIT {n1};",
]


def generate(out_path: Path, target_bytes: int, seed: int = 0xDEADBEEF) -> tuple[int, int, int]:
    """Write corpus.sql; return (bytes_written, preseed_stmts, random_stmts)."""
    rng = random.Random(seed)

    with out_path.open("w") as f:
        # Pre-seed: one CREATE TABLE per table, in index order, at the top.
        written = 0
        preseed_stmts = 0
        for i in range(NUM_TABLES):
            line = PRESEED_TEMPLATE.format(i=i) + "\n"
            f.write(line)
            written += len(line)
            preseed_stmts += 1

        # Fill with random statements that only reference preseeded tables.
        random_stmts = 0
        while written < target_bytes:
            tpl = rng.choice(TEMPLATES)
            line = tpl.format(
                i=rng.randint(0, NUM_TABLES - 1),
                j=rng.randint(0, NUM_TABLES - 1),
                n1=rng.randint(0, 1_000_000),
                n2=rng.randint(0, 1_000_000),
                n3=rng.randint(0, 1_000_000),
                n4=rng.randint(0, 1_000_000),
                n5=rng.randint(0, 1_000_000),
                f=round(rng.uniform(-1000, 1000), 4),
            ) + "\n"
            f.write(line)
            written += len(line)
            random_stmts += 1

    return written, preseed_stmts, random_stmts


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else OUT_DEFAULT
    target = int(argv[2]) if len(argv) > 2 else TARGET_BYTES_DEFAULT
    written, preseed, rnd = generate(out, target)
    print(
        f"wrote {written} bytes to {out} "
        f"(preseed={preseed} CREATE TABLEs, random={rnd} statements)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
