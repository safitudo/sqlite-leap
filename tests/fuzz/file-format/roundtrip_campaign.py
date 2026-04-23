#!/usr/bin/env python3
"""
Bidirectional file-format roundtrip campaign.

Generates K random deterministic SQL workloads (schema + INSERT/UPDATE/
DELETE + SELECT), exercises each across a producer/reader matrix of
{mainline, leap-c, leap-rust}, and records byte-identical vs divergent
verdicts per (producer, reader, workload).

"Byte-identical" here means: identical canonical row-set representation
for every SELECT in the workload. Each engine emits its own output
format (mainline: pipe-separated ASCII; leap: JSON), so we parse both
into Python lists of tuples and compare those. This checks result
equivalence, not wire-format byte-identity — which is the correct
level: the file-format contract requires that reading a DB produced by
one engine through another engine yields the same logical rows. The
actual DB-file bytes need not match between producers, only the
semantic content read out of them.

Workload shape: for each seed S:
  - PRAGMA page_size=<one of 4096,8192>;   (only on first run against fresh DB)
  - CREATE TABLE t (id INTEGER PRIMARY KEY, a INTEGER, b TEXT, c REAL);
  - CREATE INDEX idx_t_a ON t(a);
  - INSERT INTO t (a,b,c) VALUES (...),(...)...   [~50 rows]
  - UPDATE t SET b=? WHERE a BETWEEN ? AND ?;     [a few rows]
  - DELETE FROM t WHERE id = ?;                    [a few rows]
  - The verification SELECT list:
      SELECT COUNT(*) FROM t;
      SELECT id, a, b, c FROM t ORDER BY id;
      SELECT a, COUNT(*) FROM t GROUP BY a ORDER BY a;
      SELECT id FROM t WHERE a > ? ORDER BY id;
      SELECT MAX(id), MIN(id), SUM(a) FROM t;

We don't try every possible SQL — we want a reproducible, mechanical
corpus that exercises pager + b-tree + WAL + index paths without
depending on exotic grammar.

Matrix directions (we run each for every workload):
  mainline  -> mainline  (self-check / oracle anchor)
  mainline  -> leap-c
  mainline  -> leap-rust
  leap-c    -> mainline
  leap-c    -> leap-c
  leap-c    -> leap-rust
  leap-rust -> mainline
  leap-rust -> leap-c
  leap-rust -> leap-rust

One-shot run per pairing: "producer" builds the DB file, "reader" runs
the verification SELECTs against it. Results compared to the mainline
baseline (mainline-produced, mainline-read) — if any column of any row
differs, count as divergence.

Output: a Markdown matrix plus a triage list.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path


MAINLINE = "/Users/stanislav/code/sqlite-leap/bench/baselines/bin/sqlite-mainline"
LEAPC = "/Users/stanislav/code/sqlite-leap/src-c/bin/sqlite-leap-cli"
LEAPRUST = "/Users/stanislav/code/sqlite-leap/src-rust/target/release/sqlite-leap-cli"

# A "verdict" for a SELECT is a list-of-tuples representation with values
# normalised to a canonical Python type. We keep the comparison strict:
# integer vs float distinction matters, text equality is byte-for-byte.


def canon_cell(x):
    """Canonicalise a cell from parsed engine output.
    - Leap emits JSON, which gives us ints, floats, strings, bools, None.
    - Mainline emits ASCII pipe-delimited; we try to coerce to int/float
      where possible so comparisons don't fail on string vs number."""
    if x is None:
        return None
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        # Normalize -0.0 → 0.0; keep precision as-is
        if x == 0.0:
            return 0.0
        return x
    if isinstance(x, str):
        if x == "":
            return ""
        # Try int
        try:
            return int(x)
        except ValueError:
            pass
        try:
            f = float(x)
            return f
        except ValueError:
            pass
        return x
    return x


def parse_mainline(out: str):
    """Mainline output: one row per line, columns `|`-separated.
    Empty output = empty rowset."""
    out = out.rstrip("\n")
    if out == "":
        return []
    rows = []
    for ln in out.split("\n"):
        cells = ln.split("|")
        rows.append(tuple(canon_cell(c) for c in cells))
    return rows


def parse_leap(out: str):
    """Leap output: JSON object {"rows": [[...]]} per statement.
    Multi-statement invocations concatenate multiple JSON objects, one
    per statement, on separate lines. For our workload we pass a single
    SELECT per query call, so we expect exactly one JSON object."""
    out = out.strip()
    if not out:
        return []
    # Split on lines, take the last non-empty JSON (last statement).
    chunks = [c for c in out.split("\n") if c.strip()]
    if not chunks:
        return []
    obj = json.loads(chunks[-1])
    rows = obj.get("rows", [])
    return [tuple(canon_cell(v) for v in row) for row in rows]


def run_cmd(cmd, timeout=30):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "", "timeout"
    if proc.returncode < 0:
        return "CRASH", proc.stdout, f"signal={-proc.returncode}: {proc.stderr[:200]}"
    if proc.returncode != 0:
        return "ERROR", proc.stdout, f"exit={proc.returncode}: {proc.stderr[:500]}"
    return "OK", proc.stdout, ""


def produce(engine: str, db_path: str, setup_sql: str):
    """Run the producer workload on a fresh DB file.
    For leap-*, also detect JSON {"error":...} output — the CLI exits 0
    even when a statement fails, we have to scan stdout."""
    if engine == "mainline":
        cmd = [MAINLINE, db_path]
        try:
            proc = subprocess.run(cmd, input=setup_sql, capture_output=True,
                                  text=True, timeout=30, check=False)
        except subprocess.TimeoutExpired:
            return "TIMEOUT", "timeout"
        if proc.returncode != 0:
            return "ERROR", f"exit={proc.returncode}: {proc.stderr[:500]}"
        return "OK", ""
    if engine == "leap-c":
        bin_ = LEAPC
    elif engine == "leap-rust":
        bin_ = LEAPRUST
    else:
        raise ValueError(engine)
    status, out, err = run_cmd([bin_, db_path, setup_sql])
    if status != "OK":
        return status, err
    # Scan JSON output lines for any error object
    for ln in (out or "").split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("{") and '"error"' in ln:
            return "ERROR", f"stmt-error: {ln[:200]}"
    return "OK", ""


def query(engine: str, db_path: str, sql: str):
    """Run a single SELECT against an existing DB. Returns (status, rows, err)."""
    if engine == "mainline":
        cmd = [MAINLINE, db_path]
        try:
            proc = subprocess.run(cmd, input=sql, capture_output=True,
                                  text=True, timeout=30, check=False)
        except subprocess.TimeoutExpired:
            return "TIMEOUT", None, "timeout"
        if proc.returncode != 0:
            return "ERROR", None, f"exit={proc.returncode}: {proc.stderr[:500]}"
        return "OK", parse_mainline(proc.stdout), ""
    if engine == "leap-c":
        bin_ = LEAPC
    elif engine == "leap-rust":
        bin_ = LEAPRUST
    else:
        raise ValueError(engine)
    status, out, err = run_cmd([bin_, db_path, sql])
    if status != "OK":
        return status, None, err
    try:
        rows = parse_leap(out)
    except Exception as e:
        return "ERROR", None, f"parse: {e}: raw={out[:200]}"
    return "OK", rows, ""


def gen_workload(rng: random.Random, n_rows: int = 50) -> tuple[str, str, list[str]]:
    """Return (mainline_setup_sql, leap_setup_sql, list_of_verification_sqls).

    mainline_setup_sql includes PRAGMA page_size and VACUUM; leap_setup_sql
    omits them (leap doesn't yet support PRAGMA page_size / VACUUM — the
    roundtrip test is specifically about file-format compatibility of the
    schema+rows, not pragma semantics). Both setups produce identical
    user-visible rowsets under a SELECT, which is what we compare."""
    page_size = rng.choice([4096, 8192])
    # Build a set of (a, b, c) rows
    rows = []
    for _ in range(n_rows):
        a = rng.randint(-1000, 1000)
        # restricted text chars to keep mainline ASCII-pipe parsing easy;
        # unicode handling is exercised elsewhere.
        blen = rng.randint(1, 16)
        b = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789-_")
                    for _ in range(blen))
        c = round(rng.uniform(-100, 100), 3)
        rows.append((a, b, c))
    # Pick some ids to update and delete after insert — the inserted rowids
    # are 1..n_rows.
    n_updates = rng.randint(2, 6)
    n_deletes = rng.randint(1, 4)
    update_ids = rng.sample(range(1, n_rows + 1), n_updates)
    delete_ids = rng.sample([i for i in range(1, n_rows + 1)
                             if i not in update_ids], n_deletes)

    core_parts = []
    core_parts.append("CREATE TABLE t (id INTEGER PRIMARY KEY, a INTEGER, b TEXT, c REAL);")
    core_parts.append("CREATE INDEX idx_t_a ON t(a);")
    for i, (a, b, c) in enumerate(rows):
        core_parts.append(f"INSERT INTO t (a, b, c) VALUES ({a}, '{b}', {c});")
    for uid in update_ids:
        new_b = "updated_" + str(uid)
        core_parts.append(f"UPDATE t SET b='{new_b}' WHERE id={uid};")
    for did in delete_ids:
        core_parts.append(f"DELETE FROM t WHERE id={did};")
    core = "\n".join(core_parts) + "\n"

    mainline_setup = (f"PRAGMA page_size={page_size};\n"
                      "VACUUM;\n" + core)
    leap_setup = core

    # Pick a threshold for the range query
    threshold = rng.randint(-500, 500)

    queries = [
        "SELECT COUNT(*) FROM t;",
        "SELECT id, a, b, c FROM t ORDER BY id;",
        "SELECT a, COUNT(*) FROM t GROUP BY a ORDER BY a;",
        f"SELECT id FROM t WHERE a > {threshold} ORDER BY id;",
        "SELECT MAX(id), MIN(id), SUM(a) FROM t;",
    ]
    return mainline_setup, leap_setup, queries


def workload_hash(setup: str, queries: list[str]) -> str:
    import hashlib
    h = hashlib.md5()
    h.update(setup.encode())
    for q in queries:
        h.update(q.encode())
    return h.hexdigest()[:10]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-md", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--tmp", default="/tmp/rt_campaign")
    ap.add_argument("--n-workloads", type=int, default=100)
    ap.add_argument("--n-rows", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0xFEEDF00D)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    tmp = Path(args.tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    engines = ["mainline", "leap-c", "leap-rust"]
    # Matrix key: (producer, reader) → counts {byte_identical, divergent, producer_err, reader_err}
    matrix = {(p, r): {"identical": 0, "diverge": 0, "produce_err": 0,
                      "read_err": 0, "read_crash": 0}
              for p in engines for r in engines}

    divergences = []  # list of triage entries
    produce_errors = []
    reader_errors = []
    reader_crashes = []

    start = time.monotonic()
    for i in range(args.n_workloads):
        mainline_setup, leap_setup, queries = gen_workload(rng, args.n_rows)
        wid = workload_hash(mainline_setup, queries)

        # Establish oracle: mainline produces, mainline reads
        oracle_db = tmp / f"wl{i:03d}_oracle.db"
        if oracle_db.exists():
            oracle_db.unlink()
        pstat, perr = produce("mainline", str(oracle_db), mainline_setup)
        if pstat != "OK":
            # oracle broken — skip this workload entirely
            produce_errors.append(("mainline-oracle", wid, perr))
            continue
        oracle_rows = []
        oracle_ok = True
        for q in queries:
            qs, rows, qerr = query("mainline", str(oracle_db), q)
            if qs != "OK":
                oracle_ok = False
                reader_errors.append(("mainline-oracle", wid, q, qerr))
                break
            oracle_rows.append(rows)
        if not oracle_ok:
            continue

        # For every producer, build a DB, then run every reader against it.
        for producer in engines:
            prod_db = tmp / f"wl{i:03d}_{producer}.db"
            if prod_db.exists():
                prod_db.unlink()
            if producer == "mainline":
                # reuse oracle DB
                prod_db_path = str(oracle_db)
            else:
                pstat, perr = produce(producer, str(prod_db), leap_setup)
                if pstat != "OK":
                    # Count produce-failure against every reader for this producer.
                    for r in engines:
                        matrix[(producer, r)]["produce_err"] += 1
                    produce_errors.append((producer, wid, perr))
                    continue
                prod_db_path = str(prod_db)

            for reader in engines:
                got_rows = []
                read_status = "OK"
                for q_idx, q in enumerate(queries):
                    qs, rows, qerr = query(reader, prod_db_path, q)
                    if qs == "CRASH":
                        matrix[(producer, reader)]["read_crash"] += 1
                        reader_crashes.append((producer, reader, wid, q, qerr))
                        read_status = "CRASH"
                        break
                    if qs != "OK":
                        matrix[(producer, reader)]["read_err"] += 1
                        reader_errors.append((producer, reader, wid, q, qerr))
                        read_status = "ERR"
                        break
                    got_rows.append(rows)
                if read_status != "OK":
                    continue
                # Compare to oracle
                if got_rows == oracle_rows:
                    matrix[(producer, reader)]["identical"] += 1
                else:
                    matrix[(producer, reader)]["diverge"] += 1
                    # diff the first mismatching query
                    for q_idx in range(len(queries)):
                        if got_rows[q_idx] != oracle_rows[q_idx]:
                            divergences.append({
                                "producer": producer,
                                "reader": reader,
                                "workload": wid,
                                "query": queries[q_idx],
                                "expected_sample": oracle_rows[q_idx][:5],
                                "got_sample": got_rows[q_idx][:5],
                                "expected_len": len(oracle_rows[q_idx]),
                                "got_len": len(got_rows[q_idx]),
                            })
                            break

        if (i + 1) % 10 == 0:
            elapsed = time.monotonic() - start
            print(f"[progress] {i+1}/{args.n_workloads} workloads, "
                  f"elapsed={elapsed:.1f}s", file=sys.stderr)

    elapsed = time.monotonic() - start

    # Write JSON
    result = {
        "n_workloads": args.n_workloads,
        "n_rows": args.n_rows,
        "seed": args.seed,
        "elapsed_s": elapsed,
        "engines": engines,
        "matrix": {f"{p}__{r}": v for (p, r), v in matrix.items()},
        "divergences": divergences,
        "produce_errors": produce_errors,
        "reader_errors": reader_errors,
        "reader_crashes": reader_crashes,
    }
    Path(args.out_json).write_text(json.dumps(result, indent=2, default=str))

    # Write Markdown
    md = []
    md.append("# File-format bidirectional roundtrip fuzz — 2026-04-21\n")
    md.append(f"- Campaign seed: `{args.seed}`\n")
    md.append(f"- Workloads: {args.n_workloads}")
    md.append(f"- Rows per workload: {args.n_rows}")
    md.append(f"- Elapsed: {elapsed:.1f}s\n")
    md.append("## Matrix: byte-identical SELECT results\n")
    md.append("Each cell shows `identical / diverge / produce_err / read_err / read_crash`.\n")
    md.append("Oracle = mainline writes, mainline reads, so `(mainline, mainline)` "
              "counts the number of workloads where the oracle pipeline itself "
              "succeeded.\n")
    # Header
    md.append("| producer \\ reader | " + " | ".join(engines) + " |")
    md.append("|" + "---|" * (len(engines) + 1))
    for p in engines:
        row = [p]
        for r in engines:
            v = matrix[(p, r)]
            row.append(f"{v['identical']} / {v['diverge']} / "
                       f"{v['produce_err']} / {v['read_err']} / "
                       f"{v['read_crash']}")
        md.append("| " + " | ".join(row) + " |")
    md.append("")

    # Totals
    tot_identical = sum(v["identical"] for v in matrix.values())
    tot_diverge = sum(v["diverge"] for v in matrix.values())
    tot_prod_err = sum(v["produce_err"] for v in matrix.values())
    tot_read_err = sum(v["read_err"] for v in matrix.values())
    tot_read_crash = sum(v["read_crash"] for v in matrix.values())
    md.append("## Totals\n")
    md.append(f"- Byte-identical cells: **{tot_identical}**")
    md.append(f"- Divergent cells: **{tot_diverge}**")
    md.append(f"- Producer errors (counted per-reader): {tot_prod_err}")
    md.append(f"- Reader engine errors: {tot_read_err}")
    md.append(f"- Reader crashes: {tot_read_crash}\n")

    if divergences:
        md.append("## Divergences (first 20)\n")
        for d in divergences[:20]:
            md.append(f"- `{d['producer']} → {d['reader']}` wl=`{d['workload']}` "
                      f"query `{d['query']}`")
            md.append(f"  - expected rows={d['expected_len']} sample="
                      f"`{d['expected_sample']}`")
            md.append(f"  - got      rows={d['got_len']} sample="
                      f"`{d['got_sample']}`")
        if len(divergences) > 20:
            md.append(f"... and {len(divergences) - 20} more (see JSON)")
        md.append("")
    else:
        md.append("## Divergences\n\nNone.\n")

    if produce_errors:
        md.append("## Producer failures (sample)\n")
        for pe in produce_errors[:10]:
            md.append(f"- `{pe[0]}` wl=`{pe[1]}` err: `{pe[2]}`")
        if len(produce_errors) > 10:
            md.append(f"... and {len(produce_errors) - 10} more (see JSON)")
        md.append("")

    if reader_errors:
        md.append("## Reader errors (sample)\n")
        for re_ in reader_errors[:10]:
            if len(re_) == 5:
                md.append(f"- `{re_[0]} -> {re_[1]}` wl=`{re_[2]}` "
                          f"query `{re_[3]}` err: `{re_[4]}`")
            else:
                md.append(f"- `{re_}`")
        if len(reader_errors) > 10:
            md.append(f"... and {len(reader_errors) - 10} more (see JSON)")
        md.append("")

    if reader_crashes:
        md.append("## Reader crashes\n")
        for rc in reader_crashes[:10]:
            md.append(f"- `{rc[0]} -> {rc[1]}` wl=`{rc[2]}` "
                      f"query `{rc[3]}` signal: `{rc[4]}`")
        md.append("")

    Path(args.out_md).write_text("\n".join(md) + "\n")
    print(f"[done] wrote {args.out_md} and {args.out_json}")


if __name__ == "__main__":
    main()
