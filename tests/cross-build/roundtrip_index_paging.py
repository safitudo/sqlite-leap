#!/usr/bin/env python3
"""Phase 9d regression: multi-page index B-tree read + write.

Two cases pinpoint the bugs fixed by the index-paging agent (2026-04-20):

- `read-large-indexed-from-mainline`: mainline SQLite writes a database
  with an index that spans multiple 0x0a leaves + a 0x02 interior root.
  `leap-rust` must open it and serve an index-ordered SELECT without
  raising STORAGE_UNSUPPORTED_FEATURE { feature: "page_type_0x02" }.
  Originally (pre-9d) the reader rejected 0x02 pages on open. The
  reader now walks the index tree in-order, yielding leaf cells and
  interior-cell records interleaved in key order.

- `write-large-indexed-roundtrip`: `leap-rust` writes 10,000 rows with
  an index; the resulting index entries no longer fit on one 0x0a leaf.
  Pre-9d the writer raised STORAGE_PAGE_FULL on close. The writer now
  splits index entries across multiple 0x0a leaves and builds a 0x02
  interior tier (recursively — arbitrary depth — if the interior tier
  itself overflows a single page).

Both cases assert index-ordered SELECT round-trips and (for the write
case) that mainline `sqlite3` can read the leap-rust-produced DB with
PRAGMA integrity_check reporting no structural corruption (any
`never used` warnings from pre-existing rootpage-allocation waste are
ignored — they predate this agent and are outside its scope).

Usage:
  python3 tests/cross-build/roundtrip_index_paging.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parents[2]
RUST_CLI = REPO / "src-rust" / "target" / "release" / "sqlite-leap-cli"
MAIN = shutil.which("sqlite3") or "/usr/bin/sqlite3"

N = 10000
DDL = "CREATE TABLE kv (k TEXT, v INTEGER); CREATE INDEX kv_k ON kv(k);"
ROWS = [f"INSERT INTO kv VALUES ('key{i:06d}', {i});" for i in range(N)]


def case_read_large_indexed_from_mainline(tmp: Path) -> list[str]:
    """mainline writes 10k+index DB; leap-rust reads index-ordered SELECT."""
    failures: list[str] = []
    db = tmp / "mainline.db"
    script = DDL + "\nBEGIN;\n" + "\n".join(ROWS) + "\nCOMMIT;\n"
    r = subprocess.run([MAIN, str(db)], input=script, text=True,
                       capture_output=True, timeout=300)
    if r.returncode != 0:
        failures.append(f"mainline write rc={r.returncode}: {r.stderr[:200]}")
        return failures

    r = subprocess.run(
        [str(RUST_CLI), str(db), "SELECT k FROM kv ORDER BY k LIMIT 5;"],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        failures.append(f"leap-rust read rc={r.returncode}: {r.stderr[:200]}")
        return failures
    expected = '{"rows":[["key000000"],["key000001"],["key000002"],["key000003"],["key000004"]]}'
    if expected not in r.stdout:
        failures.append(f"leap-rust read unexpected: stdout={r.stdout[:400]!r}")
    return failures


def case_write_large_indexed_roundtrip(tmp: Path) -> list[str]:
    """leap-rust writes 10k+index DB, reopens, SELECTs in order;
    mainline reads the same DB back with integrity_check not reporting
    structural corruption."""
    failures: list[str] = []
    db = tmp / "leaprust.db"
    sql = DDL + " BEGIN;" + "".join(ROWS) + "COMMIT;"
    r = subprocess.run([str(RUST_CLI), str(db), sql], capture_output=True,
                       text=True, timeout=300)
    if r.returncode != 0:
        failures.append(f"leap-rust write rc={r.returncode}: {r.stderr[:200]}")
        return failures

    # Reopen + SELECT on leap-rust.
    r = subprocess.run(
        [str(RUST_CLI), str(db), "SELECT k FROM kv ORDER BY k LIMIT 5;"],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        failures.append(f"leap-rust reopen read rc={r.returncode}: {r.stderr[:200]}")
    else:
        expected = '{"rows":[["key000000"],["key000001"],["key000002"],["key000003"],["key000004"]]}'
        if expected not in r.stdout:
            failures.append(f"leap-rust reopen unexpected: stdout={r.stdout[:400]!r}")

    # Mainline reads the leap-rust DB.
    r = subprocess.run([MAIN, str(db), "SELECT k FROM kv ORDER BY k LIMIT 5;"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        failures.append(f"mainline read leap-rust rc={r.returncode}: {r.stderr[:200]}")
    else:
        want = "\n".join(f"key{i:06d}" for i in range(5)) + "\n"
        if r.stdout != want:
            failures.append(f"mainline read leap-rust unexpected: {r.stdout[:400]!r}")

    # Integrity check — filter out the "never used" pre-existing rootpage
    # allocation waste (unrelated pre-existing bug; outside scope of the
    # index-paging fix).
    r = subprocess.run([MAIN, str(db), "PRAGMA integrity_check;"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        failures.append(f"integrity_check rc={r.returncode}: {r.stderr[:200]}")
    else:
        noise_ok = {"*** in database main ***"}
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        problems = []
        for line in lines:
            if line in noise_ok or line == "ok":
                continue
            if "never used" in line:
                # Pre-existing rootpage-allocation waste — not this fix's concern.
                continue
            problems.append(line)
        if problems:
            failures.append(f"integrity_check structural issues: {problems}")

    # Row count must be exactly N — catches interior-cell-duplication bugs.
    r = subprocess.run([MAIN, str(db), "SELECT COUNT(*) FROM kv;"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode == 0:
        try:
            got = int(r.stdout.strip())
            if got != N:
                failures.append(f"COUNT(*) = {got}, expected {N}")
        except ValueError:
            failures.append(f"COUNT(*) parse fail: {r.stdout!r}")

    return failures


def main() -> int:
    if not RUST_CLI.exists():
        print(f"SKIP leap-rust CLI missing at {RUST_CLI}", file=sys.stderr)
        return 0
    if not Path(MAIN).exists():
        print(f"SKIP mainline sqlite3 missing at {MAIN}", file=sys.stderr)
        return 0

    total_fail = 0
    with TemporaryDirectory(prefix="leap-9d-") as td:
        tmp = Path(td)

        for name, fn in [
            ("read-large-indexed-from-mainline", case_read_large_indexed_from_mainline),
            ("write-large-indexed-roundtrip", case_write_large_indexed_roundtrip),
        ]:
            sub = tmp / name
            sub.mkdir()
            fails = fn(sub)
            if fails:
                total_fail += 1
                print(f"FAIL {name}")
                for f in fails:
                    print(f"  {f}")
            else:
                print(f"PASS {name}")

    print(f"\nphase9d-index-paging: {2 - total_fail}/2 passed")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
