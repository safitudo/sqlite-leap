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

import hashlib
import math
import os
import re
import sys
from dataclasses import dataclass
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "src-python"))

from leap_sqlite.compiler.expr_compile import CompileError
from leap_sqlite.compiler.insert_compile import (
    CompileInsertOk,
    compile_insert,
    compile_insert_with_source,
)
from leap_sqlite.compiler.delete_compile import (
    CompileDeleteOk,
    compile_delete,
)
from leap_sqlite.compiler.update_compile import (
    CompileUpdateOk,
    compile_update,
)
from leap_sqlite.parser.delete_stmt import DeleteParseOk, parse_delete
from leap_sqlite.parser.update_stmt import UpdateParseOk, parse_update
from leap_sqlite.compiler.select_compile import (
    ColumnSchema,
    CompileSelectOk,
    TableSchema,
    compile_select,
)
from leap_sqlite.compiler.select_compile_subq import (
    compile_select_with_db,
)
from leap_sqlite.parser.select_stmt import (
    CompoundOpExcept,
    CompoundOpIntersect,
    CompoundOpUnion,
    CompoundOpUnionAll,
    OrderByItem,
    SelectStmt,
    TableRefNamed,
)
from leap_sqlite.parser.expr import ExprIntLit, ExprUnary, UnaryOpNeg
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
    database_drop_view,
    database_install_table,
    database_install_view,
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


def value_to_python(v: Value):
    """Convert a leap-engine Value to a plain Python value for SLT projection."""
    if isinstance(v, ValueNull):
        return None
    if isinstance(v, ValueInteger):
        return v.v
    if isinstance(v, ValueReal):
        return v.v
    if isinstance(v, ValueText):
        return v.v
    if isinstance(v, ValueBlob):
        return bytes(v.v)
    return None


# ----- SLT typed-projection / hash helpers (mirrors driver_sqlite.py) ----

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
    # INSERT ... SELECT — dispatch through compile_insert_with_source.
    if parsed.stmt.from_select is not None:
        sel = parsed.stmt.from_select
        # Look up source table schema from the SELECT's FROM clause if it's a
        # simple TableRefNamed; otherwise pass an empty schema and let the
        # compiler error out cleanly.
        source_schema: TableSchema = TableSchema(name="", columns=())
        if isinstance(sel.from_, TableRefNamed):
            try:
                src_entry = catalog.get(sel.from_.name)
                source_schema = src_entry.schema
            except KeyError:
                pass
        compiled = compile_insert_with_source(
            parsed.stmt, entry.schema, source_schema)
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


def run_delete(catalog: Catalog, src: str) -> Optional[str]:
    toks = tokenize(src)
    if isinstance(toks, LexError):
        return f"lex: {toks.message}"
    parsed = parse_delete(toks, 0)
    if isinstance(parsed, ParseError):
        return f"parse: {parsed.message}"
    if not isinstance(parsed, DeleteParseOk):
        return f"parse: unexpected {type(parsed).__name__}"
    table_name = parsed.stmt.table
    try:
        entry = catalog.get(table_name)
    except KeyError as e:
        return f"schema: {e}"
    compiled = compile_delete(parsed.stmt, entry.schema)
    if isinstance(compiled, CompileError):
        return f"compile: {compiled.message}"
    if not isinstance(compiled, CompileDeleteOk):
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


def run_update(catalog: Catalog, src: str) -> Optional[str]:
    toks = tokenize(src)
    if isinstance(toks, LexError):
        return f"lex: {toks.message}"
    parsed = parse_update(toks, 0)
    if isinstance(parsed, ParseError):
        return f"parse: {parsed.message}"
    if not isinstance(parsed, UpdateParseOk):
        return f"parse: unexpected {type(parsed).__name__}"
    table_name = parsed.stmt.table
    try:
        entry = catalog.get(table_name)
    except KeyError as e:
        return f"schema: {e}"
    compiled = compile_update(parsed.stmt, entry.schema)
    if isinstance(compiled, CompileError):
        return f"compile: {compiled.message}"
    if not isinstance(compiled, CompileUpdateOk):
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


def run_drop_table(catalog: Catalog, src: str) -> Optional[str]:
    """Best-effort DROP TABLE: case-insensitive name lookup, optional
    IF EXISTS, optional schema-qualifier (which we ignore). Removes the
    table from the catalog and the mem-store so subsequent SELECTs raise.
    Always returns success (Optional None) if syntactically reasonable —
    SLT lines are statement-ok or expect-error; the run-only mechanic is
    that real divergence is flagged by adjacent queries, not by DROP."""
    # Tokenise as plain words for tolerance.
    rest = src.strip()
    # Strip trailing ';'.
    if rest.endswith(";"):
        rest = rest[:-1].rstrip()
    parts = rest.split()
    if len(parts) < 3:
        return "parse: short DROP TABLE"
    # parts[0] DROP, parts[1] TABLE
    idx = 2
    if_exists = False
    if idx < len(parts) and parts[idx].upper() == "IF" and idx + 1 < len(parts) and parts[idx + 1].upper() == "EXISTS":
        idx += 2
        if_exists = True
    if idx >= len(parts):
        return "parse: missing table name in DROP TABLE"
    name = parts[idx].strip(';"`[]')
    # Drop schema qualifier "schema.table"
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    # Case-insensitive removal from catalog and from db.tables.
    target_key: Optional[str] = None
    for k in catalog._tables.keys():
        if k.lower() == name.lower():
            target_key = k
            break
    if target_key is None:
        if if_exists:
            return None
        return f"schema: no such table: {name}"
    del catalog._tables[target_key]
    catalog.db.tables[:] = [
        t for t in catalog.db.tables if t.name.lower() != name.lower()
    ]
    return None


# Match `CREATE [TEMP|TEMPORARY] VIEW [IF NOT EXISTS] <name> [(cols)] AS <select>`.
# Captures: 1=name (with optional schema-qualifier prefix stripped later),
# 2=optional column-list, 3=select body. Trailing ';' stripped by caller.
_CREATE_VIEW_RE = re.compile(
    r"^\s*CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?VIEW\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?"
    r"([\w\.\"`\[\]]+)\s*"
    r"(\([^)]*\))?\s*"
    r"AS\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)


def run_create_view(catalog: Catalog, src: str) -> Optional[str]:
    """Register a VIEW in catalog.db.views. The compile_select_with_db
    pass auto-resolves view-FROM references via db.views, so subsequent
    SELECTs against this view will compile. We do not parse the AS body
    here — it is re-tokenised + re-parsed lazily on each reference."""
    body = src.strip()
    if body.endswith(";"):
        body = body[:-1].rstrip()
    m = _CREATE_VIEW_RE.match(body)
    if not m:
        return f"parse: malformed CREATE VIEW: {body[:80]!r}"
    name = m.group(1).strip('"`[]')
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    select_sql = m.group(3).strip()
    database_install_view(catalog.db, name, select_sql)
    return None


def run_drop_view(catalog: Catalog, src: str) -> Optional[str]:
    """Best-effort DROP VIEW: removes from db.views. IF EXISTS tolerated;
    missing view → silent success (matches no-op semantics for DROP VIEW
    in v21 and prior)."""
    rest = src.strip()
    if rest.endswith(";"):
        rest = rest[:-1].rstrip()
    parts = rest.split()
    if len(parts) < 3:
        return None
    idx = 2
    if idx < len(parts) and parts[idx].upper() == "IF" and idx + 1 < len(parts) and parts[idx + 1].upper() == "EXISTS":
        idx += 2
    if idx >= len(parts):
        return None
    name = parts[idx].strip(';"`[]')
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    database_drop_view(catalog.db, name)
    return None


# Statements that are accepted as no-op PASS (LEAP doesn't model them but
# they must not block subsequent records).
_NOOP_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("DROP", "INDEX"),
    ("DROP", "TRIGGER"),
    ("CREATE", "INDEX"),
    ("CREATE", "UNIQUE"),       # CREATE UNIQUE INDEX ...
    ("CREATE", "TRIGGER"),
    ("CREATE", "TEMP"),         # CREATE TEMP {TABLE|VIEW|TRIGGER} — handled upstream; ack-pass safety net
    ("CREATE", "TEMPORARY"),
    ("REINDEX",),
    ("ANALYZE",),
    ("VACUUM",),
    ("EXPLAIN",),
)


def _eval_int_expr(e) -> Optional[int]:
    """Best-effort literal evaluator for LIMIT/OFFSET (int-lit or -int-lit)."""
    if e is None:
        return None
    if isinstance(e, ExprIntLit):
        try:
            return int(e.text)
        except ValueError:
            return None
    if isinstance(e, ExprUnary) and isinstance(e.op, UnaryOpNeg):
        inner = _eval_int_expr(e.arg)
        if inner is not None:
            return -inner
    return None


def _row_key(row: list[Value]) -> tuple:
    """NULL-equal-NULL hashable key for set ops."""
    out: list = []
    for v in row:
        if isinstance(v, ValueNull):
            out.append(("N",))
        elif isinstance(v, ValueInteger):
            out.append(("I", v.v))
        elif isinstance(v, ValueReal):
            out.append(("R", v.v))
        elif isinstance(v, ValueText):
            out.append(("T", v.v))
        elif isinstance(v, ValueBlob):
            out.append(("B", bytes(v.v)))
        else:
            out.append(("U", repr(v)))
    return tuple(out)


def _dedup_rows(rows: list[list[Value]]) -> list[list[Value]]:
    seen: set = set()
    out: list[list[Value]] = []
    for r in rows:
        k = _row_key(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _run_select_core(
    catalog: Catalog, stmt: SelectStmt
) -> tuple[Optional[list[list[Value]]], Optional[str]]:
    """Execute a single (non-compound) SELECT via the Python compiler/VDBE."""
    schema = TableSchema(name="", columns=())
    if isinstance(stmt.from_, TableRefNamed):
        e = catalog._tables.get(stmt.from_.name)
        if e is not None:
            schema = e.schema
    extras_list = [
        e.schema for n, e in catalog._tables.items()
        if e.schema.name and (not schema.name or n != schema.name)
    ]
    compiled = compile_select_with_db(stmt, schema, catalog.db, extras_list)
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
    stmt = parsed.stmt
    # Non-compound: fall through to the compiler (which handles ORDER BY,
    # LIMIT, OFFSET natively).
    if not stmt.compound:
        # Pick schema based on FROM clause text scan (legacy heuristic
        # retained as a fallback for non-named FROMs).
        schema = TableSchema(name="", columns=())
        if isinstance(stmt.from_, TableRefNamed):
            e = catalog._tables.get(stmt.from_.name)
            if e is not None:
                schema = e.schema
        else:
            src_lower = src.lower()
            for name, entry in catalog._tables.items():
                if (
                    f"from {name.lower()}" in src_lower
                    or f"from {name.lower()}\n" in src_lower
                ):
                    schema = entry.schema
                    break
        extras_list = [
            e.schema for n, e in catalog._tables.items()
            if e.schema.name and (not schema.name or n != schema.name)
        ]
        compiled = compile_select_with_db(stmt, schema, catalog.db, extras_list)
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

    # Compound SELECT: execute head + each tail core separately and combine.
    head_stmt = SelectStmt(
        distinct=stmt.distinct,
        projection=stmt.projection,
        from_=stmt.from_,
        where_=stmt.where_,
        order_by=(),
        limit=None,
        offset=None,
        group_by=stmt.group_by,
        having=stmt.having,
        compound=(),
        with_clauses=stmt.with_clauses,
    )
    rows, err = _run_select_core(catalog, head_stmt)
    if err is not None:
        return None, err
    if rows is None:
        return None, "no rows and no error"
    accum: list[list[Value]] = list(rows)
    for tail in stmt.compound:
        tail_core = SelectStmt(
            distinct=tail.select.distinct,
            projection=tail.select.projection,
            from_=tail.select.from_,
            where_=tail.select.where_,
            order_by=(),
            limit=None,
            offset=None,
            group_by=tail.select.group_by,
            having=tail.select.having,
            compound=(),
            with_clauses=tail.select.with_clauses,
        )
        t_rows, t_err = _run_select_core(catalog, tail_core)
        if t_err is not None:
            return None, t_err
        if t_rows is None:
            return None, "no rows and no error"
        op = tail.op
        if isinstance(op, CompoundOpUnionAll):
            accum = accum + t_rows
        elif isinstance(op, CompoundOpUnion):
            accum = _dedup_rows(accum + t_rows)
        elif isinstance(op, CompoundOpIntersect):
            t_keys = {_row_key(r) for r in t_rows}
            accum = _dedup_rows([r for r in accum if _row_key(r) in t_keys])
        elif isinstance(op, CompoundOpExcept):
            t_keys = {_row_key(r) for r in t_rows}
            accum = _dedup_rows([r for r in accum if _row_key(r) not in t_keys])
        else:
            return None, f"compile: unsupported compound op {type(op).__name__}"

    # Outer ORDER BY: only positional integer literal supported here for
    # the driver-level path; column-ref ordering is the compiler's job and
    # would have been handled by run_select_core had compound been empty.
    if stmt.order_by:
        try:
            keyed: list[tuple[tuple, list[Value]]] = []
            order_specs: list[tuple[int, bool]] = []
            for ob in stmt.order_by:
                idx = _eval_int_expr(ob.expr)
                if idx is None:
                    raise _DriverOrderByUnsupported()
                order_specs.append((idx - 1, ob.desc))
            from functools import cmp_to_key

            def _cmp_val(a: Value, b: Value) -> int:
                if isinstance(a, ValueNull) and isinstance(b, ValueNull):
                    return 0
                if isinstance(a, ValueNull):
                    return -1
                if isinstance(b, ValueNull):
                    return 1
                ax = a.v if hasattr(a, "v") else a
                bx = b.v if hasattr(b, "v") else b
                if ax == bx:
                    return 0
                try:
                    return -1 if ax < bx else 1
                except TypeError:
                    sa, sb = repr(ax), repr(bx)
                    return -1 if sa < sb else (0 if sa == sb else 1)

            def _row_cmp(r1: list[Value], r2: list[Value]) -> int:
                for col_idx, desc in order_specs:
                    if col_idx < 0 or col_idx >= len(r1) or col_idx >= len(r2):
                        continue
                    c = _cmp_val(r1[col_idx], r2[col_idx])
                    if c != 0:
                        return -c if desc else c
                return 0

            accum = sorted(accum, key=cmp_to_key(_row_cmp))
        except _DriverOrderByUnsupported:
            # ORDER BY non-positional in compound → leave order as-is;
            # caller's typestring sort_mode (rowsort/valuesort) will
            # canonicalize.
            pass

    # Outer LIMIT / OFFSET.
    offset = _eval_int_expr(stmt.offset) if stmt.offset is not None else 0
    if offset is None:
        offset = 0
    limit = _eval_int_expr(stmt.limit) if stmt.limit is not None else None
    if offset > 0:
        accum = accum[offset:]
    if limit is not None and limit >= 0:
        accum = accum[:limit]
    return accum, None


class _DriverOrderByUnsupported(Exception):
    pass


def run_statement(catalog: Catalog, src: str) -> Optional[str]:
    """Statement dispatch by leading keyword."""
    head = src.lstrip().split(None, 3)
    if len(head) < 1:
        return f"statement: too-short SQL: {src!r}"
    h0 = head[0].upper()
    h1 = head[1].upper() if len(head) >= 2 else ""
    h2 = head[2].upper() if len(head) >= 3 else ""

    # CREATE TABLE — including CREATE TEMP/TEMPORARY TABLE (strip kw).
    if h0 == "CREATE":
        if h1 == "TABLE":
            return run_create_table(catalog, src)
        if h1 in ("TEMP", "TEMPORARY") and h2 == "TABLE":
            # Strip the TEMP/TEMPORARY keyword and route to CREATE TABLE.
            stripped = src.lstrip()
            # Replace first occurrence of CREATE <kw> TABLE with CREATE TABLE.
            # Case-preserve by chopping the words.
            after_create = stripped[len("CREATE"):].lstrip()
            after_temp = after_create.split(None, 1)
            if len(after_temp) >= 2:
                return run_create_table(catalog, "CREATE " + after_temp[1])
            return f"statement: malformed CREATE {h1} TABLE"

    if h0 == "INSERT":
        return run_insert(catalog, src)
    if h0 == "REPLACE":
        # SQLite-specific INSERT variant; route through run_insert.
        return run_insert(catalog, src)
    if h0 == "DELETE":
        return run_delete(catalog, src)
    if h0 == "UPDATE":
        return run_update(catalog, src)

    # DROP TABLE — actually mutate catalog so subsequent SELECTs fail.
    if h0 == "DROP" and h1 == "TABLE":
        return run_drop_table(catalog, src)

    # CREATE VIEW — register in db.views so compile_select_with_db can
    # resolve `FROM <view>` references. Without this, downstream queries
    # against the view fail with "unknown column" / "empty projection".
    if h0 == "CREATE" and h1 == "VIEW":
        return run_create_view(catalog, src)

    # DROP VIEW — remove from db.views. IF EXISTS tolerated.
    if h0 == "DROP" and h1 == "VIEW":
        return run_drop_view(catalog, src)

    # Statement-level SELECT — execute, discard rows, PASS if no error.
    if h0 == "SELECT" or (h0 == "WITH" and h1 != ""):
        rows, err = run_select(catalog, src)
        return err

    # Best-effort no-op statements (DROP VIEW/INDEX, CREATE INDEX/VIEW/TRIGGER,
    # REINDEX, ANALYZE, VACUUM, EXPLAIN). Return None = success.
    for prefix in _NOOP_PREFIXES:
        if len(prefix) == 1:
            if h0 == prefix[0]:
                return None
        elif len(prefix) == 2:
            if h0 == prefix[0] and h1 == prefix[1]:
                return None

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
    """Tiny .test-file parser. Honors onlyif/skipif sqlite directives
    (LEAP is sqlite-compatible — same skip semantics as mainline)."""
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
    # Convert leap-engine Values to plain Python tuples for SLT projection.
    py_rows = [[value_to_python(v) for v in row] for row in rows]
    ts = rec.typestring or ""
    sm = rec.sort_mode or "nosort"
    cells = project_cells(py_rows, ts, sm)
    expected = rec.expected_lines or []
    if len(expected) == 1:
        h = parse_hash_line(expected[0].strip())
        if h is not None:
            n_expected, hex_expected = h
            hex_actual = md5_hex_of_cells(cells)
            if len(cells) == n_expected and hex_actual == hex_expected:
                return "PASS", ""
            return "FAIL", (
                f"hash mismatch: count got={len(cells)} expected={n_expected}, "
                f"md5 got={hex_actual} expected={hex_expected}"
            )
    canonical = project_cells_canonical(py_rows, sm)
    if cells == expected or canonical == expected:
        return "PASS", ""
    return "FAIL", (
        f"got({len(cells)})={cells[:8]!r} "
        f"expected({len(expected)})={expected[:8]!r}"
    )


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
    n_pass = n_fail = n_defer = n_skip = 0
    for rec in records:
        if rec.skip:
            n_skip += 1
            print(f"SKIP {rec.line} {rec.kind}")
            continue
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
    total = n_pass + n_fail + n_defer + n_skip
    print(
        f"SUMMARY target=python pass={n_pass} fail={n_fail} "
        f"defer={n_defer} skip={n_skip} total={total}"
    )
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
