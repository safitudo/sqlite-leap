#!/usr/bin/env python3
"""
Wrap a raw multi-statement SQL file as a sqllogictest-format .slt file.

Background:
  The leap-c and leap-rust bench targets are exercised through their
  `sqllogictest` runner binary, which requires one directive (`statement ok`
  or similar) per SQL record, records separated by blank lines. Prior to
  2026-04-20 the bench lanes 2/3/4 wrapped the entire multi-statement
  corpus with a single `statement ok` header, which caused the runner to
  fail on the second statement with PARSE_UNEXPECTED_TOKEN and exit in
  ~50ms. Reported throughput numbers were an artefact of that fast
  rejection — mainline sqlite3 (which takes raw SQL on stdin) executed
  the full corpus, leap binaries executed nothing.

Fix: split the corpus on statement-terminating `;`, wrap each non-empty
statement as its own `statement ok` record. SELECT statements are also
wrapped as `statement ok` rather than `query` records — we don't need to
validate result sets for the bench lanes, only measure wall time across
identical work. The leap sqllogictest runner continues past FAIL
directives (it reports pass/fail counts at end, we only look at timing),
so statements that fail at execution (e.g. references to tables that
don't yet exist in lane 2's random corpus) still contribute their
parse+execute cost to the wall clock — which is exactly what the
parse-speed lane is meant to measure.

Usage:
  python3 _wrap_sql.py <input.sql> <output.slt>
"""

from __future__ import annotations

import sys
from pathlib import Path


def split_sql_statements(src: str) -> list[str]:
    """
    Split a SQL text on statement-terminating semicolons, respecting
    single-quoted string literals. Returns a list of statements each
    ending in `;`. Empty statements (stretches of whitespace between
    semicolons) are discarded.

    Note: our bench corpora are template-generated; no string literal
    contains an embedded `;`, no double-quoted identifiers with `;`
    inside, no `--` or `/* */` comments. The simple character-level
    scanner below is sufficient for those inputs; it is NOT a general
    SQL splitter.
    """
    stmts: list[str] = []
    buf: list[str] = []
    in_str = False
    for ch in src:
        if ch == "'":
            in_str = not in_str
            buf.append(ch)
        elif ch == ";" and not in_str:
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt + ";")
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def wrap_as_sqllogictest(stmts: list[str]) -> str:
    """Emit one `statement ok` record per SQL statement."""
    out: list[str] = []
    for s in stmts:
        out.append("statement ok\n")
        out.append(s)
        out.append("\n\n")
    return "".join(out)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <input.sql> <output.slt>", file=sys.stderr)
        return 2
    src = Path(argv[1]).read_text()
    stmts = split_sql_statements(src)
    wrapped = wrap_as_sqllogictest(stmts)
    Path(argv[2]).write_text(wrapped)
    print(
        f"[_wrap_sql] {argv[1]} ({len(src)} bytes) -> "
        f"{argv[2]} ({len(wrapped)} bytes, {len(stmts)} statements)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
