#!/usr/bin/env python3
"""Runner for tests/cross-build/phase6bt-index-persistence.json.

Validates that leap-c's INSERT-into-indexed-table code path produces
well-formed populated 0x0a index-leaf pages on disk (per
spec/file-format.spec.md § Phase 9be), readable both by mainline SQLite
(via PRAGMA integrity_check + index-ordered SELECT) and by leap-c itself
after a close+reopen cycle.

Driven from the JSON fixture so schema/rows are shared with a future
leap-rust runner if needed. This runner only exercises leap-c per the
2026-04-20 task scope — leap-rust's equivalent (bug #113) is handled
by a separate agent on its own fixture.

Usage:
  python3 tests/cross-build/run_phase6bt.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "cross-build" / "phase6bt-index-persistence.json"
C_CLI = REPO / "src-c" / "bin" / "sqlite-leap-cli"
MAINLINE = shutil.which("sqlite3") or "/usr/bin/sqlite3"


def gen_inserts(gen: dict) -> list[str]:
    n = int(gen["n"])
    fmt = gen["key_format"]
    if gen.get("value_kind") == "integer":
        return [f"INSERT INTO kv VALUES ('{fmt.format(i)}', {i});" for i in range(n)]
    return [f"INSERT INTO kv VALUES ('{fmt.format(i)}');" for i in range(n)]


def gen_expected_rows(gen: dict) -> list[list]:
    n = int(gen["n"])
    fmt = gen["key_format"]
    if gen.get("value_kind") == "integer":
        return [[fmt.format(i), i] for i in range(n)]
    return [[fmt.format(i)] for i in range(n)]


def leap_c_write(db: Path, ddl: str, inserts: list[str]) -> None:
    sql = ddl
    if inserts:
        sql += "BEGIN;" + "".join(inserts) + "COMMIT;"
    r = subprocess.run([str(C_CLI), str(db), sql], capture_output=True,
                       text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"leap-c write rc={r.returncode}: stderr={r.stderr[:300]}")
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict) and "error" in obj:
            raise RuntimeError(f"leap-c write sql-error: {obj['error']}")


def leap_c_read(db: Path, query: str) -> list[list]:
    r = subprocess.run([str(C_CLI), str(db), query], capture_output=True,
                       text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"leap-c read rc={r.returncode}: {r.stderr[:300]}")
    rows: list[list] = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if "error" in obj:
            raise RuntimeError(f"leap-c read sql-error: {obj['error']}")
        for row in obj.get("rows", []):
            rows.append(list(row))
    return rows


def mainline_integrity_ok(db: Path) -> tuple[bool, str]:
    r = subprocess.run([MAINLINE, str(db), "PRAGMA integrity_check;"],
                       capture_output=True, text=True, timeout=60)
    out = (r.stdout or "").strip()
    return out == "ok", out


def mainline_select(db: Path, query: str) -> list[list]:
    r = subprocess.run([MAINLINE, str(db), "-cmd", ".mode json", query],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"mainline select rc={r.returncode}: {r.stderr[:200]}")
    out = r.stdout.strip()
    if not out:
        return []
    rows = json.loads(out)
    return [list(row[k] for k in row) for row in rows]


def run_case(case: dict) -> tuple[bool, str]:
    ddl = case["ddl"]
    inserts = case.get("inserts")
    if inserts is None and "inserts_generator" in case:
        inserts = gen_inserts(case["inserts_generator"])
    if inserts is None:
        return False, "no inserts or inserts_generator"

    with TemporaryDirectory(prefix="phase6bt-") as td:
        db = Path(td) / "leapc.db"
        try:
            leap_c_write(db, ddl, inserts)
        except Exception as e:
            return False, f"leap-c write failed: {e}"

        if case.get("expect_integrity_ok"):
            ok, detail = mainline_integrity_ok(db)
            if not ok:
                return False, f"mainline integrity_check != ok: {detail[:200]}"

        # Row-set assertions via mainline (load-bearing cross-engine check).
        if "select_index_ordered" in case:
            q = case["select_index_ordered"]
            try:
                got = mainline_select(db, q)
            except Exception as e:
                return False, f"mainline SELECT failed: {e}"
            if "expect_rows_ordered" in case:
                expected = case["expect_rows_ordered"]
            elif "expect_rows_ordered_generator" in case:
                expected = gen_expected_rows(case["expect_rows_ordered_generator"])
            else:
                expected = None
            if expected is not None and got != expected:
                return False, (f"mainline SELECT row-set mismatch: "
                               f"got={got[:3]!r} expected={expected[:3]!r} "
                               f"lens got/exp={len(got)}/{len(expected)}")

        if "select_index_ordered_limit" in case:
            lim = int(case["select_index_ordered_limit"])
            q = f"SELECT k, v FROM kv ORDER BY k LIMIT {lim};"
            try:
                got = mainline_select(db, q)
            except Exception as e:
                return False, f"mainline SELECT LIMIT failed: {e}"
            expected = case["expect_head_rows"]
            if got != expected:
                return False, (f"mainline SELECT head mismatch: "
                               f"got={got!r} expected={expected!r}")

        if case.get("reopen_between"):
            # leap-c closed after write; now reopen via a fresh CLI
            # invocation and read index-ordered. The 2nd process proves the
            # populated 0x0a page round-trips through db_open's reader.
            q = case["select_index_ordered"]
            try:
                got = leap_c_read(db, q)
            except Exception as e:
                return False, f"leap-c reopen read failed: {e}"
            if "expect_rows_ordered_generator" in case:
                expected = gen_expected_rows(case["expect_rows_ordered_generator"])
            else:
                expected = case["expect_rows_ordered"]
            if got != expected:
                return False, (f"leap-c reopen row-set mismatch: "
                               f"got={got[:3]!r} expected={expected[:3]!r} "
                               f"lens got/exp={len(got)}/{len(expected)}")

    return True, ""


def main() -> int:
    if not C_CLI.exists():
        print(f"FAIL: leap-c CLI not found at {C_CLI}", file=sys.stderr)
        return 2
    with FIXTURE.open() as f:
        fixture = json.load(f)
    passed = failed = 0
    for case in fixture["cases"]:
        name = case["name"]
        ok, reason = run_case(case)
        if ok:
            print(f"PASS {name}")
            passed += 1
        else:
            print(f"FAIL {name}: {reason}")
            failed += 1
    print(f"SUMMARY phase=6bt target=c passed={passed} failed={failed} "
          f"total={passed+failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
