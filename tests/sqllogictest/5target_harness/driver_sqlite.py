#!/usr/bin/env python3
# Mainline-sqlite driver for the 5target_harness — runs the same .test
# corpus against system /usr/bin/sqlite3 (via Python's sqlite3 module).
#
# Output format matches driver_python.py: one verdict line per record,
# trailing SUMMARY line. Used to establish a baseline for incl-SKIP /
# excl-SKIP corpus-rate metrics.

from __future__ import annotations

import hashlib
import math
import os
import sqlite3
import sys
from dataclasses import dataclass
from typing import Optional


# ----- Canonical row rendering (mirrors driver_python.py) -----------

def _format_real_g15(x: float) -> str:
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Inf" if x > 0 else "-Inf"
    if x == 0.0:
        return "-0.0" if math.copysign(1.0, x) < 0 else "0.0"
    s = f"{x:.14e}"
    mant, _, exp_s = s.partition("e")
    try:
        exp = int(exp_s)
    except ValueError:
        exp = 0
    if mant.startswith("-"):
        sign = "-"
        mant = mant[1:]
    else:
        sign = ""
    int_part, _, frac_part = mant.partition(".")
    frac_trim = frac_part.rstrip("0")
    if exp < -4 or exp >= 15:
        out = sign + int_part
        if frac_trim:
            out += "." + frac_trim
        if exp >= 0:
            out += f"e+{exp:02d}"
        else:
            out += f"e-{(-exp):02d}"
        return out
    all_digits = int_part + frac_part
    point_at = 1 + exp
    out = sign
    if point_at <= 0:
        out += "0." + ("0" * (-point_at)) + all_digits
    elif point_at >= len(all_digits):
        out += all_digits + ("0" * (point_at - len(all_digits))) + ".0"
    else:
        out += all_digits[:point_at] + "." + all_digits[point_at:]
    if "." in out:
        pre, _, post = out.partition(".")
        trimmed = post.rstrip("0")
        if not trimmed:
            trimmed = "0"
        out = pre + "." + trimmed
    return out


def render_typed(v, tchar: str) -> str:
    if tchar == "I":
        if v is None:
            return "NULL"
        if isinstance(v, int) and not isinstance(v, bool):
            return str(v)
        if isinstance(v, float):
            return str(int(v))
        if isinstance(v, str):
            try:
                return str(int(v))
            except (ValueError, TypeError):
                return "0"
        return "0"
    if tchar == "R":
        if v is None:
            return "0.000"
        if isinstance(v, (int, float)):
            return f"{float(v):.3f}"
        if isinstance(v, str):
            try:
                return f"{float(v):.3f}"
            except (ValueError, TypeError):
                return "0.000"
        return "0.000"
    # 'T' / fallback
    if v is None:
        return "NULL"
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:.3f}"
    if isinstance(v, str):
        if not v:
            return "(empty)"
        return "".join(c if (0x20 <= ord(c) < 0x7f) else "@" for c in v)
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    return "NULL"


def project_cells(rows, typestring: str, sort_mode: str) -> list[str]:
    if not typestring:
        out: list[str] = []
        for row in rows:
            for v in row:
                out.append(render_typed(v, "T"))
        return out
    tchars = list(typestring)
    rendered_rows: list[list[str]] = []
    for row in rows:
        r: list[str] = []
        for i, t in enumerate(tchars):
            if i < len(row):
                r.append(render_typed(row[i], t))
            else:
                r.append(render_typed(None, t))
        rendered_rows.append(r)
    if sort_mode == "rowsort":
        rendered_rows.sort()
    elif sort_mode == "valuesort":
        flat = [c for r in rendered_rows for c in r]
        flat.sort()
        return flat
    return [c for r in rendered_rows for c in r]


def _render_canonical(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return _format_real_g15(v)
    if isinstance(v, str):
        return "(empty)" if not v else v
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    return "NULL"


def project_cells_canonical(rows, sort_mode: str) -> list[str]:
    rendered_rows = [[_render_canonical(v) for v in row] for row in rows]
    if sort_mode == "rowsort":
        rendered_rows.sort()
    elif sort_mode == "valuesort":
        flat = [c for r in rendered_rows for c in r]
        flat.sort()
        return flat
    return [c for r in rendered_rows for c in r]


def md5_hex_of_cells(cells: list[str]) -> str:
    h = hashlib.md5()
    for c in cells:
        h.update(c.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def parse_hash_line(line: str):
    parts = line.split()
    if len(parts) != 5:
        return None
    if parts[1] != "values" or parts[2] != "hashing" or parts[3] != "to":
        return None
    try:
        n = int(parts[0])
    except ValueError:
        return None
    hex_s = parts[4]
    if len(hex_s) != 32:
        return None
    return (n, hex_s)


# ----- .test file parser (same skip semantics as driver_python.py) ---

@dataclass
class Record:
    kind: str
    line: int
    sql: str
    expected_kind: Optional[str]
    expected_lines: Optional[list[str]]
    typestring: Optional[str]
    sort_mode: Optional[str] = None
    label: Optional[str] = None
    skip: bool = False


_SELF_ENGINES = ("sqlite",)


def _directive_skips(onlyif, skipif):
    if onlyif and not any(e in _SELF_ENGINES for e in onlyif):
        return True
    if any(e in _SELF_ENGINES for e in skipif):
        return True
    return False


def parse_test_file(path: str) -> list[Record]:
    with open(path) as f:
        lines = f.read().splitlines()
    out: list[Record] = []
    i = 0
    n = len(lines)
    pending_onlyif: list[str] = []
    pending_skipif: list[str] = []
    while i < n:
        ln = lines[i]
        s = ln.strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        if s.startswith("onlyif "):
            parts = s.split()
            if len(parts) >= 2:
                pending_onlyif.append(parts[1].lower())
            i += 1
            continue
        if s.startswith("skipif "):
            parts = s.split()
            if len(parts) >= 2:
                pending_skipif.append(parts[1].lower())
            i += 1
            continue
        skip = _directive_skips(pending_onlyif, pending_skipif)
        line_no = i + 1
        if s.startswith("statement "):
            parts = s.split(None, 2)
            expected = parts[1]
            i += 1
            sql_parts: list[str] = []
            while i < n and lines[i].strip() and not lines[i].lstrip().startswith("#"):
                sql_parts.append(lines[i])
                i += 1
            sql = "\n".join(sql_parts).strip()
            out.append(Record(
                kind="statement", line=line_no, sql=sql,
                expected_kind=expected, expected_lines=None, typestring=None,
                skip=skip,
            ))
            pending_onlyif.clear()
            pending_skipif.clear()
        elif s.startswith("query "):
            parts = s.split()
            ts = parts[1] if len(parts) >= 2 else ""
            sort_mode = parts[2] if len(parts) >= 3 else "nosort"
            label = parts[3] if len(parts) >= 4 else None
            i += 1
            sql_parts = []
            while i < n and lines[i].strip() != "----":
                if not lines[i].strip():
                    break
                sql_parts.append(lines[i])
                i += 1
            sql = "\n".join(sql_parts).strip()
            expected: list[str] = []
            if i < n and lines[i].strip() == "----":
                i += 1
                while i < n and lines[i].strip():
                    expected.append(lines[i])
                    i += 1
            out.append(Record(
                kind="query", line=line_no, sql=sql,
                expected_kind=None, expected_lines=expected, typestring=ts,
                sort_mode=sort_mode, label=label, skip=skip,
            ))
            pending_onlyif.clear()
            pending_skipif.clear()
        else:
            i += 1
    return out


# ----- Per-record verdict -------------------------------------------

def verdict_statement(conn: sqlite3.Connection, rec: Record):
    try:
        conn.executescript(rec.sql) if ";" in rec.sql.rstrip(";") else conn.execute(rec.sql)
        err = None
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    if rec.expected_kind == "ok":
        if err is None:
            return "PASS", ""
        return "FAIL", err
    if rec.expected_kind == "error":
        if err is not None:
            return "PASS", ""
        return "FAIL", "expected error, got success"
    return "FAIL", f"unknown statement-expected {rec.expected_kind!r}"


def verdict_query(conn: sqlite3.Connection, rec: Record, label_hashes):
    try:
        cur = conn.execute(rec.sql)
        rows = cur.fetchall()
    except Exception as exc:
        return "FAIL", f"{type(exc).__name__}: {exc}"
    ts = rec.typestring or ""
    sm = rec.sort_mode or "nosort"
    cells = project_cells(rows, ts, sm)
    expected = rec.expected_lines or []
    if len(expected) == 1:
        h = parse_hash_line(expected[0].strip())
        if h is not None:
            n_expected, hex_expected = h
            hex_actual = md5_hex_of_cells(cells)
            if rec.label:
                label_hashes[rec.label] = hex_actual
            if len(cells) == n_expected and hex_actual == hex_expected:
                return "PASS", ""
            return "FAIL", (
                f"hash mismatch: count got={len(cells)} expected={n_expected}, "
                f"md5 got={hex_actual} expected={hex_expected}"
            )
    if rec.label:
        label_hashes[rec.label] = md5_hex_of_cells(cells)
    canonical = project_cells_canonical(rows, sm)
    if cells == expected or canonical == expected:
        return "PASS", ""
    return "FAIL", (
        f"got({len(cells)})={cells[:8]!r} "
        f"expected({len(expected)})={expected[:8]!r}"
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: driver_sqlite.py <test-file>", file=sys.stderr)
        return 2
    test_path = sys.argv[1]
    conn = sqlite3.connect(":memory:")
    records = parse_test_file(test_path)
    label_hashes: dict[str, str] = {}
    n_pass = n_fail = n_defer = n_skip = 0
    for rec in records:
        if rec.skip:
            n_skip += 1
            print(f"SKIP {rec.line} {rec.kind}")
            continue
        if rec.kind == "statement":
            v, detail = verdict_statement(conn, rec)
        else:
            v, detail = verdict_query(conn, rec, label_hashes)
        if v == "PASS":
            n_pass += 1
        elif v == "FAIL":
            n_fail += 1
        else:
            n_defer += 1
        line = f"{v} {rec.line} {rec.kind}"
        if detail:
            line += f" {detail}"
        print(line)
    total = n_pass + n_fail + n_defer + n_skip
    print(
        f"SUMMARY target=sqlite pass={n_pass} fail={n_fail} "
        f"defer={n_defer} skip={n_skip} total={total}"
    )
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
