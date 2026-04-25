#!/usr/bin/env python3
# 5-target sqllogictest driver — Python target.
#
# Reads a thin sqllogictest subset (statement ok / query <typestring>
# nosort) from argv[1], dispatches each record into the Python
# leap_sqlite parser/compiler/vdbe stack, and emits one
# PASS|FAIL|DEFER line per record on stdout.
#
# Output line format:
#   <verdict> <line> <kind> <detail>
# where verdict ∈ {PASS, FAIL, DEFER}, kind ∈ {statement, query},
# detail is empty on PASS, an error sketch on FAIL/DEFER.
#
# Final line is:
#   SUMMARY target=python pass=<int> fail=<int> defer=<int> total=<int>
#
# Exit 0 iff fail == 0. DEFERs do not affect exit (missing-feature is
# not a divergence).
#
# This driver is intentionally a thin wrapper. It does not attempt to
# implement the full runner spec — it implements just enough to drive
# the canonical 5target fixture.

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "src-python"))

from leap_sqlite.compiler.expr_compile import CompileError
from leap_sqlite.compiler.insert_compile import (
    CompileInsertOk,
    compile_insert,
)
from leap_sqlite.compiler.select_compile import (
    ColumnSchema,
    CompileSelectOk,
    TableSchema,
    compile_select,
)
from leap_sqlite.core import (
    HaltStatusError,
    HaltStatusOk,
    Register,
    Value,
    ValueBlob,
    ValueInteger,
    ValueNull,
    ValueReal,
    ValueText,
)
from leap_sqlite.parser.create_table_stmt import (
    CreateTableParseOk,
    parse_create_table,
)
from leap_sqlite.parser.expr import ParseError
from leap_sqlite.parser.insert_stmt import InsertParseOk, parse_insert
from leap_sqlite.parser.select_stmt import SelectParseOk, parse_select
from leap_sqlite.parser.tokenizer import LexError, tokenize
from leap_sqlite.storage import (
    Database,
    database_install_table,
    database_new,
)
from leap_sqlite.vdbe import Program, VdbeState, execute_program


# ----- Canonical row rendering --------------------------------------

def render_value(v: Value) -> str:
    """Render one Value into the canonical sqllogictest cell form.
    NULL → 'NULL', empty text → '(empty)'. Reals render via repr to
    avoid trailing-zero ambiguity; integers render as decimal."""
    if isinstance(v, ValueNull):
        return "NULL"
    if isinstance(v, ValueInteger):
        return str(v.v)
    if isinstance(v, ValueReal):
        return repr(v.v)
    if isinstance(v, ValueText):
        return v.v if v.v else "(empty)"
    if isinstance(v, ValueBlob):
        return v.v.hex()
    return f"<unknown:{type(v).__name__}>"


# ----- Schema registry ----------------------------------------------

@dataclass
class TableEntry:
    schema: TableSchema
    column_names: tuple[str, ...]


class Catalog:
    """In-memory CREATE TABLE catalog: maps table name → TableSchema
    + column-names list (the latter used to install the empty table
    into the mem-store on first INSERT)."""
    def __init__(self) -> None:
        self.db: Database = database_new()
        self._tables: dict[str, TableEntry] = {}

    def install_create_table(self, name: str, columns: list[str]) -> None:
        """Install a fresh empty table with the given columns."""
        if name in self._tables:
            raise ValueError(f"table {name!r} already exists")
        self._tables[name] = TableEntry(
            schema=TableSchema(
                name=name,
                columns=tuple(
                    ColumnSchema(name=c, index=i) for i, c in enumerate(columns)
                ),
            ),
            column_names=tuple(columns),
        )
        database_install_table(self.db, name, list(columns), [])

    def get(self, name: str) -> TableEntry:
        e = self._tables.get(name)
        if e is None:
            raise KeyError(f"unknown table {name!r}")
        return e


# ----- VDBE row sink ------------------------------------------------

COLLECTED: list[list[Value]] = []


def sink(state: VdbeState, start: Register, count: int) -> None:
    row: list[Value] = []
    for i in range(count):
        row.append(state.get_register(Register(value=start.value + i)))
    COLLECTED.append(row)


def take_rows() -> list[list[Value]]:
    rows = list(COLLECTED)
    COLLECTED.clear()
    return rows


# ----- Statement / query dispatch -----------------------------------

def run_create_table(catalog: Catalog, src: str) -> Optional[str]:
    toks = tokenize(src)
    if isinstance(toks, LexError):
        return f"lex: {toks.message}"
    parsed = parse_create_table(toks, 0)
    if isinstance(parsed, ParseError):
        return f"parse: {parsed.message}"
    if not isinstance(parsed, CreateTableParseOk):
        return f"parse: unexpected {type(parsed).__name__}"
    cols = [c.name for c in parsed.stmt.columns]
    try:
        catalog.install_create_table(parsed.stmt.name, cols)
    except ValueError as e:
        return f"install: {e}"
    return None


def _exec_program(program: Program) -> Optional[str]:
    take_rows()  # reset sink buffer
    halt = execute_program(program, catalog.db, sink)
    if isinstance(halt, HaltStatusError):
        return f"execute: {halt.condition}"
    return None


def run_insert(catalog: Catalog, src: str) -> Optional[str]:
    toks = tokenize(src)
    if isinstance(toks, LexError):
        return f"lex: {toks.message}"
    parsed = parse_insert(toks, 0)
    if isinstance(parsed, ParseError):
        return f"parse: {parsed.message}"
    if not isinstance(parsed, InsertParseOk):
        return f"parse: unexpected {type(parsed).__name__}"
    table_name = parsed.stmt.table
    try:
        entry = catalog.get(table_name)
    except KeyError as e:
        return f"schema: {e}"
    compiled = compile_insert(parsed.stmt, entry.schema)
    if isinstance(compiled, CompileError):
        return f"compile: {compiled.message}"
    if not isinstance(compiled, CompileInsertOk):
        return f"compile: unexpected {type(compiled).__name__}"
    program = Program(
        opcodes=compiled.opcodes,
        num_registers=compiled.num_registers,
        num_cursors=compiled.num_cursors,
        num_aggregates=0,
        num_windows=0,
        row_sink=sink,
    )
    return _exec_program(program)


def run_select(
    catalog: Catalog, src: str
) -> tuple[Optional[list[list[Value]]], Optional[str]]:
    toks = tokenize(src)
    if isinstance(toks, LexError):
        return None, f"lex: {toks.message}"
    parsed = parse_select(toks, 0)
    if isinstance(parsed, ParseError):
        return None, f"parse: {parsed.message}"
    if not isinstance(parsed, SelectParseOk):
        return None, f"parse: unexpected {type(parsed).__name__}"
    # Pick the schema based on the SELECT's first FROM table, else empty.
    schema = TableSchema(name="", columns=())
    src_lower = src.lower()
    for name, entry in catalog._tables.items():
        if f"from {name.lower()}" in src_lower or f"from {name.lower()}\n" in src_lower:
            schema = entry.schema
            break
    compiled = compile_select(parsed.stmt, schema)
    if isinstance(compiled, CompileError):
        return None, f"compile: {compiled.message}"
    if not isinstance(compiled, CompileSelectOk):
        return None, f"compile: unexpected {type(compiled).__name__}"
    program = Program(
        opcodes=compiled.opcodes,
        num_registers=compiled.num_registers,
        num_cursors=compiled.num_cursors,
        num_aggregates=getattr(compiled, "num_aggregates", 0),
        num_windows=getattr(compiled, "num_windows", 0),
        row_sink=sink,
    )
    err = _exec_program(program)
    if err:
        return None, err
    return take_rows(), None


def run_statement(catalog: Catalog, src: str) -> Optional[str]:
    """Statement dispatch by leading keyword."""
    head = src.lstrip().split(None, 2)
    if len(head) < 2:
        return f"statement: too-short SQL: {src!r}"
    h0 = head[0].upper()
    h1 = head[1].upper()
    if h0 == "CREATE" and h1 == "TABLE":
        return run_create_table(catalog, src)
    if h0 == "INSERT":
        return run_insert(catalog, src)
    return f"statement: unsupported leading kw {h0!r}"


# ----- .test file parser --------------------------------------------

@dataclass
class Record:
    kind: str          # "statement" or "query"
    line: int
    sql: str
    expected_kind: Optional[str]   # "ok" / "error" for statement; None for query
    expected_lines: Optional[list[str]]  # for query records, raw post-`----` lines
    typestring: Optional[str]      # e.g. "IT" for query records


def parse_test_file(path: str) -> list[Record]:
    """Tiny .test-file parser. Sufficient for the canonical fixture
    (no hashes, no labels, no skipif, no multi-line SQL, no mode
    directives)."""
    with open(path) as f:
        lines = f.read().splitlines()

    out: list[Record] = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        s = ln.strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        line_no = i + 1
        if s.startswith("statement "):
            parts = s.split(None, 2)
            expected = parts[1]  # "ok" or "error"
            i += 1
            sql_parts: list[str] = []
            while i < n and lines[i].strip() and not lines[i].lstrip().startswith("#"):
                sql_parts.append(lines[i])
                i += 1
            sql = "\n".join(sql_parts).strip()
            out.append(Record(
                kind="statement", line=line_no, sql=sql,
                expected_kind=expected, expected_lines=None, typestring=None,
            ))
        elif s.startswith("query "):
            parts = s.split()
            ts = parts[1]
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
            ))
        else:
            # Unrecognised — skip, advance one line.
            i += 1
    return out


# ----- Per-record verdict -------------------------------------------

def verdict_statement(catalog: Catalog, rec: Record) -> tuple[str, str]:
    try:
        err = run_statement(catalog, rec.sql)
    except Exception as exc:
        if rec.expected_kind == "error":
            return "PASS", ""
        return "FAIL", f"runtime: {type(exc).__name__}: {exc}"
    if rec.expected_kind == "ok":
        if err is None:
            return "PASS", ""
        # Distinguish DEFER (parser/compile not implementing a feature)
        # from FAIL (semantic divergence).
        if any(tag in err for tag in ("parse:", "compile:", "statement: unsupported")):
            return "DEFER", err
        return "FAIL", err
    if rec.expected_kind == "error":
        if err is not None:
            return "PASS", ""
        return "FAIL", "expected error, got success"
    return "FAIL", f"unknown statement-expected {rec.expected_kind!r}"


def verdict_query(catalog: Catalog, rec: Record) -> tuple[str, str]:
    try:
        rows, err = run_select(catalog, rec.sql)
    except Exception as exc:
        return "FAIL", f"runtime: {type(exc).__name__}: {exc}"
    if err is not None:
        if any(tag in err for tag in ("parse:", "compile:")):
            return "DEFER", err
        return "FAIL", err
    if rows is None:
        return "FAIL", "no rows and no error"
    # nosort canonical: render row-by-row, value-per-line.
    rendered: list[str] = []
    for row in rows:
        for v in row:
            rendered.append(render_value(v))
    expected = rec.expected_lines or []
    if rendered == expected:
        return "PASS", ""
    return "FAIL", f"got={rendered!r} expected={expected!r}"


# ----- Main ---------------------------------------------------------

catalog: Catalog  # set in main, used by _exec_program


def main() -> int:
    global catalog
    if len(sys.argv) != 2:
        print("usage: driver_python.py <test-file>", file=sys.stderr)
        return 2
    test_path = sys.argv[1]
    catalog = Catalog()
    records = parse_test_file(test_path)
    n_pass = n_fail = n_defer = 0
    for rec in records:
        if rec.kind == "statement":
            v, detail = verdict_statement(catalog, rec)
        else:
            v, detail = verdict_query(catalog, rec)
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
    total = n_pass + n_fail + n_defer
    print(
        f"SUMMARY target=python pass={n_pass} fail={n_fail} "
        f"defer={n_defer} total={total}"
    )
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
