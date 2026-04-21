#!/usr/bin/env python3
"""
Phase 3b round-trip smoke test.

Uses mainline `sqlite3` to create a .db file with known schema + rows.
Feeds the raw bytes through the sqlite-leap test harness (via preload_hex)
on both C and Rust targets, and verifies that both can read the file back
and emit the expected rows.

This is a *smoke* test, not the full Phase 3e round-trip suite — it exercises
one direction (mainline writes → sqlite-leap reads) for one concrete schema.
The other direction (sqlite-leap writes → mainline reads) is deferred to the
real Phase 3e work (which needs a no-cleanup mode in the harness; the current
phase3*-test binaries unlink temp files on exit).

Exits 0 on success, 1 on any mismatch.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
C_BIN_3A  = REPO / "src-c" / "bin" / "phase3a-test"
C_BIN_3B  = REPO / "src-c" / "bin" / "phase3b-test"
RUST_CARGO_DIR = REPO / "src-rust"
RUST_BIN_3A = "phase3a-test"
RUST_BIN_3B = "phase3b-test"


def build_small_mainline_db(tmpdir: Path) -> Path:
    """Create a small (single-leaf users table) .db via mainline sqlite3."""
    db = tmpdir / "mainline-small.db"
    sql = "\n".join([
        "CREATE TABLE users (id INTEGER, name TEXT);",
        "INSERT INTO users VALUES (1, 'alice');",
        "INSERT INTO users VALUES (2, 'bob');",
        "INSERT INTO users VALUES (3, 'carol');",
        "INSERT INTO users VALUES (NULL, 'nobody');",
    ])
    subprocess.run(["sqlite3", str(db)], input=sql, text=True, check=True)
    assert db.exists() and db.stat().st_size >= 4096, f"small db too small: {db.stat().st_size}"
    return db


def build_large_mainline_db(tmpdir: Path, n_rows: int = 1500) -> Path:
    """Create a .db with enough rows to force an interior (0x05) page in the users tree."""
    db = tmpdir / "mainline-large.db"
    stmts = ["CREATE TABLE nums (x INTEGER);", "BEGIN;"]
    stmts += [f"INSERT INTO nums VALUES ({i});" for i in range(1, n_rows + 1)]
    stmts.append("COMMIT;")
    subprocess.run(["sqlite3", str(db)], input="\n".join(stmts), text=True, check=True)
    size = db.stat().st_size
    pages = size // 4096
    assert pages >= 3, f"expected multi-page db, got {pages} pages ({size} bytes)"
    print(f"[smoke] mainline large DB: {pages} pages ({size} bytes) — tree depth ≥ 2")
    return db


def build_fixture_small(db_bytes: bytes) -> dict:
    return {
        "phase": "3e-smoke",
        "description": "Reads a small single-leaf .db file produced by mainline sqlite3 3.x.",
        "cases": [
            {
                "name": "mainline-small-to-leap-read",
                "backend": "disk",
                "preload_hex": db_bytes.hex(),
                "program": [
                    {
                        "sql": "SELECT id, name FROM users;",
                        "expect": {"rows": [[1, "alice"], [2, "bob"], [3, "carol"], [None, "nobody"]]},
                    }
                ],
            }
        ],
    }


def build_fixture_large(db_bytes: bytes, n_rows: int) -> dict:
    """Fixture uses row_count to avoid enumerating thousands of rows inline."""
    return {
        "phase": "3e-smoke-large",
        "description": "Reads a mainline-written multi-page .db (interior tree).",
        "cases": [
            {
                "name": "mainline-large-to-leap-read",
                "backend": "disk",
                "preload_hex": db_bytes.hex(),
                "program": [
                    {"sql": "SELECT x FROM nums;", "expect": {"row_count": n_rows}}
                ],
            }
        ],
    }


def run_c(binary: Path, fixture_path: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [str(binary), str(fixture_path)],
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def run_rust(bin_name: str, fixture_path: Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["cargo", "run", "--release", "--quiet", "--bin", bin_name, "--",
         str(fixture_path)],
        cwd=str(RUST_CARGO_DIR),
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def run_one(name: str, fixture_path: Path, phase3b: bool) -> list[str]:
    """Run fixture on both C and Rust. Returns list of failing target names."""
    failures = []
    runners = [
        ("C",    lambda p: run_c(C_BIN_3B if phase3b else C_BIN_3A, p)),
        ("Rust", lambda p: run_rust(RUST_BIN_3B if phase3b else RUST_BIN_3A, p)),
    ]
    for target, runner in runners:
        rc, out = runner(fixture_path)
        ok_line = any(f"PASS {name}" in line for line in out.splitlines())
        summary_line = next((l for l in out.splitlines() if l.startswith("SUMMARY")), "(no summary)")
        print(f"[smoke] {name} / {target}: rc={rc}, {summary_line}")
        if rc != 0 or not ok_line:
            print(f"[smoke] {target} full output:\n{out}")
            failures.append(f"{name}/{target}")
    return failures


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sqlite-leap-roundtrip-") as tmp:
        tmp = Path(tmp)
        all_failures: list[str] = []

        # Direction: mainline writes → sqlite-leap reads, single-leaf case.
        small = build_small_mainline_db(tmp)
        print(f"[smoke] mainline small DB: {small.stat().st_size} bytes")
        fx1 = tmp / "small.json"
        fx1.write_text(json.dumps(build_fixture_small(small.read_bytes())))
        all_failures += run_one("mainline-small-to-leap-read", fx1, phase3b=False)

        # Direction: mainline writes → sqlite-leap reads, multi-page (interior) case.
        n_rows = 1500
        large = build_large_mainline_db(tmp, n_rows)
        fx2 = tmp / "large.json"
        fx2.write_text(json.dumps(build_fixture_large(large.read_bytes(), n_rows)))
        # phase3b-test understands the row_count expectation; phase3a-test does not.
        all_failures += run_one("mainline-large-to-leap-read", fx2, phase3b=True)

        if all_failures:
            print(f"[smoke] FAIL — {all_failures}")
            return 1
        print("[smoke] PASS — both C and Rust read mainline-produced small + multi-page DBs.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
