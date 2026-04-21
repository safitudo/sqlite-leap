#!/usr/bin/env python3
"""
Phase 3e — formal round-trip test suite against mainline sqlite3.

Runs a set of schema + data fixtures through both directions:

  direction A  (leap-wrote, mainline-reads):
    sqlite-leap-cli (C | Rust) creates a .db and fills it
      → mainline sqlite3 reads it, SELECT output must match expectation

  direction B  (mainline-wrote, leap-reads):
    mainline sqlite3 creates a .db
      → sqlite-leap-cli (C | Rust) reads it, SELECT output must match expectation

Each direction × target × fixture = one test. Reports PASS / FAIL per test and
a summary at the end. Exits 0 iff every test passed.

Depends on:
  - src-c/bin/sqlite-leap-cli  (Phase 3d output, C)
  - src-rust/src/bin/sqlite_leap_cli.rs, built via `cargo build --release`
  - mainline `sqlite3` on PATH
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
C_CLI = REPO / "src-c" / "bin" / "sqlite-leap-cli"
RUST_CARGO_DIR = REPO / "src-rust"
RUST_CLI_BIN = "sqlite-leap-cli"


@dataclass
class Fixture:
    name: str
    setup_sql: str            # executed to populate the DB (ends statements with ';')
    select_sql: str           # a single SELECT
    expected_rows: list[list] # expected SELECT result as list of rows; each row is list of Python values (int/str/None)


FIXTURES: list[Fixture] = [
    Fixture(
        "single-int",
        "CREATE TABLE t (x INTEGER); INSERT INTO t VALUES (1); INSERT INTO t VALUES (2); INSERT INTO t VALUES (3);",
        "SELECT x FROM t;",
        [[1], [2], [3]],
    ),
    Fixture(
        "text-and-null",
        "CREATE TABLE t (a INTEGER, b TEXT); INSERT INTO t VALUES (1, 'hello'); INSERT INTO t VALUES (2, NULL); INSERT INTO t VALUES (NULL, 'world');",
        "SELECT a, b FROM t;",
        [[1, "hello"], [2, None], [None, "world"]],
    ),
    Fixture(
        "multi-table",
        "CREATE TABLE a (x INTEGER); CREATE TABLE b (y TEXT); INSERT INTO a VALUES (42); INSERT INTO b VALUES ('hi');",
        "SELECT x FROM a;",
        [[42]],
    ),
    Fixture(
        "multi-page",
        # 1500 rows → forces multi-leaf tree on either engine.
        "CREATE TABLE nums (x INTEGER);" + "".join(f"INSERT INTO nums VALUES ({i});" for i in range(1, 1501)),
        "SELECT x FROM nums;",
        [[i] for i in range(1, 1501)],
    ),
]


def run_mainline_sqlite3(db: Path, sql: str) -> str:
    """Run mainline sqlite3 and return stdout on success, or raise."""
    proc = subprocess.run(
        ["sqlite3", str(db)], input=sql, text=True, capture_output=True
    )
    if proc.returncode != 0:
        raise RuntimeError(f"mainline sqlite3 exit {proc.returncode}: {proc.stderr}")
    return proc.stdout


def mainline_reads_select(db: Path, select_sql: str) -> list[list]:
    """Run SELECT via mainline and return rows as Python values (int/str/None)."""
    # Use .mode list + .headers off + .nullvalue NULL for predictable output.
    script = (
        ".mode list\n"
        ".headers off\n"
        ".separator |\n"
        ".nullvalue __NULL__\n"
        + select_sql
        + "\n"
    )
    raw = run_mainline_sqlite3(db, script)
    rows: list[list] = []
    for line in raw.splitlines():
        if line == "":
            continue
        parts = line.split("|")
        row = []
        for p in parts:
            if p == "__NULL__":
                row.append(None)
            else:
                # integer?
                try:
                    row.append(int(p))
                except ValueError:
                    row.append(p)
        rows.append(row)
    return rows


def leap_cli(binary_desc: str, db: Path, sql: str) -> list[dict]:
    """Run sqlite-leap-cli (C or Rust). Returns parsed JSON-per-statement list."""
    if binary_desc == "c":
        cmd = [str(C_CLI), str(db), sql]
        cwd = None
    elif binary_desc == "rust":
        cmd = ["cargo", "run", "--release", "--quiet", "--bin", RUST_CLI_BIN, "--", str(db), sql]
        cwd = str(RUST_CARGO_DIR)
    else:
        raise ValueError(binary_desc)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    # exit 0 = all-good, 1 = statement error with a valid error line emitted
    if proc.returncode not in (0, 1):
        raise RuntimeError(
            f"sqlite-leap-cli ({binary_desc}) exit {proc.returncode}: {proc.stderr}"
        )
    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    return [json.loads(l) for l in lines]


def leap_reads_select(binary_desc: str, db: Path, select_sql: str) -> list[list]:
    results = leap_cli(binary_desc, db, select_sql)
    if not results:
        raise RuntimeError(f"no JSON output from leap-cli for SELECT")
    last = results[-1]
    if "error" in last:
        raise RuntimeError(f"leap-cli emitted error: {last['error']}")
    return last["rows"]


def rows_equal(a: list[list], b: list[list]) -> bool:
    if len(a) != len(b):
        return False
    for ra, rb in zip(a, b):
        if len(ra) != len(rb):
            return False
        for va, vb in zip(ra, rb):
            if va is None and vb is None:
                continue
            if type(va) is not type(vb):
                return False
            if va != vb:
                return False
    return True


def test_leap_writes_mainline_reads(fx: Fixture, target: str, tmp: Path) -> tuple[str, bool, str]:
    name = f"{fx.name} [leap-{target} writes → mainline reads]"
    db = tmp / f"{fx.name}-leap-{target}.db"
    if db.exists():
        db.unlink()
    try:
        leap_cli(target, db, fx.setup_sql)
        actual = mainline_reads_select(db, fx.select_sql)
        if rows_equal(actual, fx.expected_rows):
            return (name, True, "")
        return (name, False, f"expected {fx.expected_rows[:3]}... got {actual[:3]}... lens={len(fx.expected_rows)},{len(actual)}")
    except Exception as e:
        return (name, False, f"exception: {e}")


def test_mainline_writes_leap_reads(fx: Fixture, target: str, tmp: Path) -> tuple[str, bool, str]:
    name = f"{fx.name} [mainline writes → leap-{target} reads]"
    db = tmp / f"{fx.name}-main.db"
    if db.exists():
        db.unlink()
    try:
        run_mainline_sqlite3(db, "BEGIN;" + fx.setup_sql + "COMMIT;")
        actual = leap_reads_select(target, db, fx.select_sql)
        if rows_equal(actual, fx.expected_rows):
            return (name, True, "")
        return (name, False, f"expected {fx.expected_rows[:3]}... got {actual[:3]}... lens={len(fx.expected_rows)},{len(actual)}")
    except Exception as e:
        return (name, False, f"exception: {e}")


def main() -> int:
    assert C_CLI.exists(), f"build src-c/ first — no CLI at {C_CLI}"
    results = []
    with tempfile.TemporaryDirectory(prefix="sqlite-leap-phase3e-") as tmp:
        tmp = Path(tmp)
        for fx in FIXTURES:
            for tgt in ("c", "rust"):
                results.append(test_leap_writes_mainline_reads(fx, tgt, tmp))
                results.append(test_mainline_writes_leap_reads(fx, tgt, tmp))

    passed = sum(1 for _, ok, _ in results if ok)
    failed = [r for r in results if not r[1]]
    for name, ok, why in results:
        status = "PASS" if ok else "FAIL"
        suffix = "" if ok else f"  — {why}"
        print(f"{status} {name}{suffix}")
    print(f"SUMMARY phase=3e passed={passed} failed={len(failed)} total={len(results)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
