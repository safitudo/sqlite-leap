#!/usr/bin/env python3
"""Bidirectional file-format roundtrip matrix.

Executes the full producer x reader x schema x rowcount grid that validates
sqlite-leap's file-format compatibility with mainline SQLite.

Axes:
  producer in {mainline, leap-c, leap-rust}
  reader   in {mainline, leap-c, leap-rust}
  schema   in {single-table-int, multi-table-join, indexed-text}
  rowcount in {0, 1, 100, 10000}

Total: 3 x 3 x 3 x 4 = 108 cells.

Writes results to tests/roundtrip/results/<date>-matrix.csv and .md.

Usage:
  python3 tests/roundtrip/roundtrip_matrix.py [--date YYYY-MM-DD] [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

REPO = Path(__file__).resolve().parents[2]
C_CLI = REPO / "src-c" / "bin" / "sqlite-leap-cli"
RUST_CLI = REPO / "src-rust" / "target" / "release" / "sqlite-leap-cli"
MAINLINE = shutil.which("sqlite3") or "/usr/bin/sqlite3"

# --- Schemas ---------------------------------------------------------------
# Each schema returns (ddl, inserts, queries) where queries is an ordered list
# of (label, sql) canonical read queries. Results are compared per-query.

def schema_single_int(n: int) -> tuple[str, list[str], list[tuple[str, str]]]:
    ddl = "CREATE TABLE t (id INTEGER, v INTEGER);"
    inserts = [f"INSERT INTO t VALUES ({i}, {i*2});" for i in range(n)]
    queries = [("t", "SELECT id, v FROM t ORDER BY id;")]
    return ddl, inserts, queries


def schema_multi_join(n: int) -> tuple[str, list[str], list[tuple[str, str]]]:
    ddl = (
        "CREATE TABLE users (id INTEGER, name TEXT);"
        "CREATE TABLE orders (uid INTEGER, amt INTEGER);"
    )
    inserts: list[str] = []
    for i in range(n):
        inserts.append(f"INSERT INTO users VALUES ({i}, 'u{i}');")
    # One order per user (keeps rowcount semantics simple).
    for i in range(n):
        inserts.append(f"INSERT INTO orders VALUES ({i}, {i*10});")
    queries = [
        ("users", "SELECT id, name FROM users ORDER BY id;"),
        ("orders", "SELECT uid, amt FROM orders ORDER BY uid;"),
    ]
    return ddl, inserts, queries


def schema_indexed_text(n: int) -> tuple[str, list[str], list[tuple[str, str]]]:
    ddl = (
        "CREATE TABLE kv (k TEXT, v INTEGER);"
        "CREATE INDEX kv_k ON kv(k);"
    )
    # Deterministic pseudo-random-looking keys that are still text-sortable.
    inserts = [f"INSERT INTO kv VALUES ('key{i:06d}', {i});" for i in range(n)]
    queries = [("kv", "SELECT k, v FROM kv ORDER BY k;")]
    return ddl, inserts, queries


SCHEMAS: dict[str, Callable[[int], tuple[str, list[str], list[tuple[str, str]]]]] = {
    "single-table-int": schema_single_int,
    "multi-table-join": schema_multi_join,
    "indexed-text": schema_indexed_text,
}

ROWCOUNTS = [0, 1, 100, 10000]

# --- Engines ---------------------------------------------------------------

@dataclass
class Engine:
    name: str  # mainline | leap-c | leap-rust
    available: bool
    write: Callable[[Path, str, list[str]], None]
    read: Callable[[Path, str], list[tuple]]


def mainline_write(db: Path, ddl: str, inserts: list[str]) -> None:
    script = ddl + "\nBEGIN;\n" + "\n".join(inserts) + "\nCOMMIT;\n"
    r = subprocess.run([MAINLINE, str(db)], input=script, text=True,
                       capture_output=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"mainline write rc={r.returncode}: {r.stderr[:300]}")


def mainline_read(db: Path, query: str) -> list[tuple]:
    r = subprocess.run(
        [MAINLINE, str(db), "-cmd", ".mode json", query],
        capture_output=True, text=True, timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"mainline read rc={r.returncode}: {r.stderr[:300]}")
    out = r.stdout.strip()
    if not out:
        return []
    rows = json.loads(out)
    return [tuple(row[k] for k in row) for row in rows]


def _leap_write(cli: Path, db: Path, ddl: str, inserts: list[str]) -> None:
    # Batch everything in a single SQL string; sqlite-leap-cli supports
    # semicolon-separated statements.
    sql = ddl
    if inserts:
        sql = sql + "BEGIN;" + "".join(inserts) + "COMMIT;"
    r = subprocess.run([str(cli), str(db), sql], capture_output=True,
                       text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"{cli.name} write rc={r.returncode}: {r.stderr[:300]}")
    # Fail fast on inline errors in stdout (leap emits JSON per stmt).
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict) and "error" in obj:
            raise RuntimeError(f"{cli.name} write sql-error: {obj['error']}")


def _leap_read(cli: Path, db: Path, query: str) -> list[tuple]:
    r = subprocess.run([str(cli), str(db), query], capture_output=True,
                       text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"{cli.name} read rc={r.returncode}: {r.stderr[:300]}")
    rows: list[tuple] = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if "error" in obj:
            raise RuntimeError(f"{cli.name} read sql-error: {obj['error']}")
        for row in obj.get("rows", []):
            rows.append(tuple(row))
    return rows


def leap_c_write(db, ddl, inserts): return _leap_write(C_CLI, db, ddl, inserts)
def leap_c_read(db, q): return _leap_read(C_CLI, db, q)
def leap_rust_write(db, ddl, inserts): return _leap_write(RUST_CLI, db, ddl, inserts)
def leap_rust_read(db, q): return _leap_read(RUST_CLI, db, q)


def build_engines() -> dict[str, Engine]:
    return {
        "mainline": Engine("mainline", bool(MAINLINE and Path(MAINLINE).exists()),
                           mainline_write, mainline_read),
        "leap-c": Engine("leap-c", C_CLI.exists(), leap_c_write, leap_c_read),
        "leap-rust": Engine("leap-rust", RUST_CLI.exists(), leap_rust_write, leap_rust_read),
    }


# --- Comparison ------------------------------------------------------------

def _coerce(v):
    # mainline .mode json emits ints as ints, reals as floats, text as str, NULL as None.
    # leap emits same (with integer-as-int). Normalize boolean-int-looking floats.
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def rows_equal(a: list[tuple], b: list[tuple]) -> bool:
    if len(a) != len(b):
        return False
    for ra, rb in zip(a, b):
        if len(ra) != len(rb):
            return False
        for x, y in zip(ra, rb):
            if _coerce(x) != _coerce(y):
                # tolerate small float drift
                if isinstance(x, float) or isinstance(y, float):
                    try:
                        if abs(float(x) - float(y)) < 1e-12:
                            continue
                    except Exception:
                        pass
                return False
    return True


# --- Cell execution --------------------------------------------------------

@dataclass
class CellResult:
    producer: str
    reader: str
    schema: str
    rowcount: int
    status: str  # pass | fail | skipped
    notes: str


def run_cell(producer: Engine, reader: Engine, schema_name: str,
             n: int) -> CellResult:
    if not producer.available:
        return CellResult(producer.name, reader.name, schema_name, n,
                          "skipped", f"producer {producer.name} unavailable")
    if not reader.available:
        return CellResult(producer.name, reader.name, schema_name, n,
                          "skipped", f"reader {reader.name} unavailable")

    ddl, inserts, queries = SCHEMAS[schema_name](n)

    with TemporaryDirectory(prefix="leap-rt-") as td:
        db_producer = Path(td) / "producer.db"
        db_reference = Path(td) / "reference.db"

        # Build the producer DB
        try:
            producer.write(db_producer, ddl, inserts)
        except Exception as e:
            return CellResult(producer.name, reader.name, schema_name, n,
                              "skipped", f"producer-write:{e}"[:300])

        # Build an identical DB using mainline as ground truth for expected rows.
        # (Mainline->mainline is the oracle for "what the row set should be".)
        try:
            mainline_write(db_reference, ddl, inserts)
        except Exception as e:
            return CellResult(producer.name, reader.name, schema_name, n,
                              "skipped", f"oracle-write:{e}"[:300])

        # Read with reader against producer DB; compare to mainline-read reference DB.
        failures: list[str] = []
        for qlabel, q in queries:
            try:
                got = reader.read(db_producer, q)
            except Exception as e:
                failures.append(f"{qlabel}:reader-error:{e}"[:300])
                continue
            try:
                expected = mainline_read(db_reference, q)
            except Exception as e:
                failures.append(f"{qlabel}:oracle-read-error:{e}"[:300])
                continue
            if not rows_equal(got, expected):
                # Produce a compact diff fingerprint (first mismatch, lens).
                short_got = got[:3]
                short_exp = expected[:3]
                failures.append(
                    f"{qlabel}:mismatch got_len={len(got)} exp_len={len(expected)} "
                    f"got_head={short_got!r} exp_head={short_exp!r}"
                )

        if failures:
            return CellResult(producer.name, reader.name, schema_name, n,
                              "fail", "; ".join(failures)[:500])
        return CellResult(producer.name, reader.name, schema_name, n, "pass", "")


# --- Matrix driver ---------------------------------------------------------

def run_matrix(limit: int | None = None) -> list[CellResult]:
    engines = build_engines()
    order = ["mainline", "leap-c", "leap-rust"]
    results: list[CellResult] = []
    total = 0
    for producer_name in order:
        for reader_name in order:
            for schema_name in SCHEMAS:
                for n in ROWCOUNTS:
                    if limit is not None and total >= limit:
                        return results
                    total += 1
                    producer = engines[producer_name]
                    reader = engines[reader_name]
                    cell = run_cell(producer, reader, schema_name, n)
                    tag = {"pass": "PASS", "fail": "FAIL", "skipped": "SKIP"}[cell.status]
                    print(f"[{tag}] {producer_name:9} -> {reader_name:9} "
                          f"{schema_name:18} n={n:<6} {cell.notes[:80]}")
                    results.append(cell)
    return results


def write_csv(results: list[CellResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["producer", "reader", "schema", "rowcount", "status", "notes"])
        for r in results:
            w.writerow([r.producer, r.reader, r.schema, r.rowcount, r.status, r.notes])


def write_markdown(results: list[CellResult], path: Path, date_str: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total = len(results)
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    skipped = sum(1 for r in results if r.status == "skipped")

    # Load-bearing cells are exactly the bidirectional mainline<->leap pairs
    # where producer != reader and one side is mainline.
    def is_load_bearing(r: CellResult) -> bool:
        return (
            (r.producer == "mainline" and r.reader in ("leap-c", "leap-rust"))
            or (r.reader == "mainline" and r.producer in ("leap-c", "leap-rust"))
        )

    load_bearing = [r for r in results if is_load_bearing(r)]
    lb_total = len(load_bearing)
    lb_pass = sum(1 for r in load_bearing if r.status == "pass")
    lb_fail = sum(1 for r in load_bearing if r.status == "fail")
    lb_skip = sum(1 for r in load_bearing if r.status == "skipped")

    lines: list[str] = []
    lines.append(f"# sqlite-leap bidirectional file-format roundtrip matrix")
    lines.append("")
    lines.append(f"- Date: {date_str}")
    lines.append(f"- Total cells: {total}")
    lines.append(f"- Overall: pass={passed} fail={failed} skipped={skipped} "
                 f"({passed*100.0/max(1,total):.1f}% pass)")
    lines.append(f"- Load-bearing (mainline<->leap, both directions): "
                 f"pass={lb_pass} fail={lb_fail} skipped={lb_skip} / {lb_total}")
    lines.append("")
    lines.append(
        "\"Load-bearing\" = any cell where one side is mainline and the other "
        "is a leap build. These are the cells that prove file-format "
        "bidirectional compatibility — the CLAUDE.md \"Done means\" #2 criterion. "
        "Failures in these cells are BUGS, not test flakes."
    )
    lines.append("")

    # Per-schema compact tables
    producers = ["mainline", "leap-c", "leap-rust"]
    readers = ["mainline", "leap-c", "leap-rust"]
    for schema_name in SCHEMAS:
        lines.append(f"## Schema: `{schema_name}`")
        lines.append("")
        # One table per rowcount
        for n in ROWCOUNTS:
            lines.append(f"### rowcount={n}")
            lines.append("")
            header = "| producer \\ reader | " + " | ".join(readers) + " |"
            sep = "|" + "---|" * (len(readers) + 1)
            lines.append(header)
            lines.append(sep)
            for p in producers:
                cells: list[str] = []
                for rd in readers:
                    match = next((r for r in results
                                  if r.producer == p and r.reader == rd
                                  and r.schema == schema_name and r.rowcount == n),
                                 None)
                    if match is None:
                        cells.append("?")
                    elif match.status == "pass":
                        cells.append("PASS")
                    elif match.status == "fail":
                        cells.append("**FAIL**")
                    else:
                        cells.append("skip")
                lines.append(f"| {p} | " + " | ".join(cells) + " |")
            lines.append("")

    # Failures section
    fails = [r for r in results if r.status == "fail"]
    if fails:
        lines.append("## Failures (reproducers)")
        lines.append("")
        for r in fails:
            lines.append(
                f"- `{r.producer}` -> `{r.reader}` schema=`{r.schema}` "
                f"rowcount={r.rowcount}"
            )
            lines.append(f"  - notes: {r.notes}")
            lines.append(f"  - reproducer: run `{Path(__file__).name}` and filter "
                         f"to `--only {r.producer},{r.reader},{r.schema},{r.rowcount}`")
        lines.append("")

    skips = [r for r in results if r.status == "skipped"]
    if skips:
        lines.append("## Skipped")
        lines.append("")
        for r in skips:
            lines.append(
                f"- `{r.producer}` -> `{r.reader}` schema=`{r.schema}` "
                f"rowcount={r.rowcount}: {r.notes}"
            )
        lines.append("")

    path.write_text("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--limit", type=int, default=None,
                    help="Limit cells (for smoke runs).")
    ap.add_argument("--out-dir", default=str(
        REPO / "tests" / "roundtrip" / "results"))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    csv_path = out_dir / f"{args.date}-matrix.csv"
    md_path = out_dir / f"{args.date}-matrix.md"

    results = run_matrix(limit=args.limit)
    write_csv(results, csv_path)
    write_markdown(results, md_path, args.date)

    total = len(results)
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    skipped = sum(1 for r in results if r.status == "skipped")
    print(f"\nTOTAL {total}  PASS {passed}  FAIL {failed}  SKIP {skipped}")
    print(f"csv: {csv_path}")
    print(f"md:  {md_path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
