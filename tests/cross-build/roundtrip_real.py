#!/usr/bin/env python3
"""Phase 6g round-trip: REAL columns between leap-c / leap-rust / mainline sqlite3.

Each fixture is a small REAL-column schema populated in one engine and read in
another. Tests bidirectional on-disk compatibility (SQLite serial type 7,
8-byte big-endian IEEE 754 double).

Usage:
  python3 tests/cross-build/roundtrip_real.py
"""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parents[2]
C_CLI    = REPO / "src-c" / "bin" / "sqlite-leap-cli"
RUST_CLI = REPO / "src-rust" / "target" / "release" / "sqlite-leap-cli"
MAIN     = shutil.which("sqlite3")

FIXTURES = [
    (
        "single-real",
        "CREATE TABLE t (x REAL);",
        ["INSERT INTO t VALUES (1.5);", "INSERT INTO t VALUES (2.5);", "INSERT INTO t VALUES (3.75);"],
        "SELECT x FROM t;",
        [(1.5,), (2.5,), (3.75,)],
    ),
    (
        "int-in-real-column",
        "CREATE TABLE t (x REAL);",
        ["INSERT INTO t VALUES (5);", "INSERT INTO t VALUES (10);"],
        "SELECT x FROM t;",
        [(5.0,), (10.0,)],
    ),
    (
        "real-with-nulls",
        "CREATE TABLE t (x REAL);",
        ["INSERT INTO t VALUES (1.5);", "INSERT INTO t VALUES (NULL);", "INSERT INTO t VALUES (2.5);"],
        "SELECT x FROM t;",
        [(1.5,), (None,), (2.5,)],
    ),
    (
        "multi-column-mixed",
        "CREATE TABLE t (id INTEGER, ratio REAL, label TEXT);",
        [
            "INSERT INTO t VALUES (1, 0.5, 'half');",
            "INSERT INTO t VALUES (2, 1.25, 'quarter-past-one');",
            "INSERT INTO t VALUES (3, 3.14159, 'pi');",
        ],
        "SELECT id, ratio, label FROM t;",
        [(1, 0.5, "half"), (2, 1.25, "quarter-past-one"), (3, 3.14159, "pi")],
    ),
]


def leap_exec(cli: Path, db: Path, sql: str) -> list[str]:
    proc = subprocess.run([str(cli), str(db), sql], capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"{cli.name} exit {proc.returncode}: {proc.stderr}")
    return [line for line in proc.stdout.splitlines() if line]


def mainline_populate(db: Path, ddl: str, inserts: list[str]) -> None:
    proc = subprocess.run([MAIN, str(db)], input=ddl + "\nBEGIN;\n" + "\n".join(inserts) + "\nCOMMIT;\n",
                          text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"sqlite3 populate: {proc.stderr}")


def mainline_read(db: Path, query: str) -> list[tuple]:
    # Use .mode tcl for clean tokenization; we'll fall back to sqlite3 -cmd .mode json
    proc = subprocess.run(
        [MAIN, str(db), "-cmd", ".mode json", query],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"sqlite3 read: {proc.stderr}")
    out = proc.stdout.strip()
    if not out:
        return []
    # output is a JSON array of objects; we want the values in fixed column order
    rows = json.loads(out)
    # preserve insertion-order keys (Python dict); mainline's .mode json uses
    # schema-declared order which matches our CREATE TABLE.
    return [tuple(r[k] for k in r) for r in rows]


def leap_read_rows(cli: Path, db: Path, query: str) -> list[tuple]:
    lines = leap_exec(cli, db, query)
    # Expected: one JSON line per statement. The last (only, here) statement's
    # output is {"rows": [[...], ...]} or {"error":...}.
    out_rows = []
    for ln in lines:
        obj = json.loads(ln)
        if "error" in obj:
            raise RuntimeError(f"leap error: {obj}")
        for row in obj["rows"]:
            out_rows.append(tuple(row))
    return out_rows


def float_eq(a, b, tol: float = 1e-12) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, float) or isinstance(b, float):
        return abs(float(a) - float(b)) <= tol
    return a == b


def tuple_eq(a: tuple, b: tuple) -> bool:
    if len(a) != len(b):
        return False
    return all(float_eq(x, y) for x, y in zip(a, b))


def rows_eq(a: list[tuple], b: list[tuple]) -> bool:
    if len(a) != len(b):
        return False
    return all(tuple_eq(x, y) for x, y in zip(a, b))


def run_case(name: str, ddl: str, inserts: list[str], query: str, expected: list[tuple]) -> list[tuple[str, bool, str]]:
    results = []
    targets = []
    if C_CLI.exists():
        targets.append(("leap-c", C_CLI))
    if RUST_CLI.exists():
        targets.append(("leap-rust", RUST_CLI))
    if not MAIN:
        return [(name, False, "mainline sqlite3 not available")]

    # Direction A: leap writes, mainline reads
    for label, cli in targets:
        with TemporaryDirectory() as td:
            db = Path(td) / f"{label}-a.db"
            sql = ddl + "".join(inserts)
            leap_exec(cli, db, sql)
            try:
                actual = mainline_read(db, query)
            except Exception as e:
                results.append((f"{name}[{label} writes -> mainline reads]", False, str(e)))
                continue
            ok = rows_eq(actual, expected)
            msg = "" if ok else f"expected {expected!r}, got {actual!r}"
            results.append((f"{name}[{label} writes -> mainline reads]", ok, msg))

    # Direction B: mainline writes, leap reads
    for label, cli in targets:
        with TemporaryDirectory() as td:
            db = Path(td) / f"{label}-b.db"
            mainline_populate(db, ddl, inserts)
            try:
                actual = leap_read_rows(cli, db, query)
            except Exception as e:
                results.append((f"{name}[mainline writes -> {label} reads]", False, str(e)))
                continue
            ok = rows_eq(actual, expected)
            msg = "" if ok else f"expected {expected!r}, got {actual!r}"
            results.append((f"{name}[mainline writes -> {label} reads]", ok, msg))

    return results


def main() -> int:
    if not MAIN:
        print("mainline sqlite3 not found in PATH", file=sys.stderr)
        return 2
    if not C_CLI.exists() and not RUST_CLI.exists():
        print("no leap CLIs built", file=sys.stderr)
        return 2

    total = 0
    passed = 0
    for name, ddl, inserts, query, expected in FIXTURES:
        for case, ok, msg in run_case(name, ddl, inserts, query, expected):
            total += 1
            if ok:
                passed += 1
                print(f"PASS {case}")
            else:
                print(f"FAIL {case}  {msg}")
    failed = total - passed
    print(f"SUMMARY phase=6g-roundtrip passed={passed} failed={failed} total={total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
