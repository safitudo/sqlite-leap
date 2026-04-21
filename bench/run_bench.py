#!/usr/bin/env python3
"""
sqlite-leap benchmark harness — covers 5 of the 6 public lanes.

Compares three engines on every lane where they're comparable:
  - leap-c:       src-c/bin/sqlite-leap-cli
  - leap-rust:    src-rust target/release/sqlite-leap-cli  (via `cargo run`)
  - mainline:     system `sqlite3` (3.41.2)

Lane coverage (as of 2026-04-18):
  L1 Cold start              — open + 1 query, N invocations, median wall time
  L2 Parse speed             — run many trivial statements, bottleneck is parse
  L3 In-memory-ish SELECT    — populated DB, pure SELECT pass, median wall time
  L4 INSERT throughput       — 10k INSERTs, single-writer, median wall time
  L5 Binary size             — stat of the CLI binaries + .wasm + mainline sqlite3
  L6 Memory footprint        — peak RSS (macOS `/usr/bin/time -l`) on a small workload

Outputs:
  - human-readable table to stdout
  - CSV to bench/results/<YYYY-MM-DD>-<HHMM>.csv

NO PUBLICATION — numbers are for internal review only per Stan's 2026-04-18 direction.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BENCH_RESULTS = REPO / "bench" / "results"
C_CLI    = REPO / "src-c" / "bin" / "sqlite-leap-cli"
RUST_CLI = REPO / "src-rust" / "target" / "release" / "sqlite-leap-cli"
WASM_ART = REPO / "src-rust" / "target" / "wasm32-unknown-unknown" / "release" / "sqlite_leap.wasm"

RUSTUP_CARGO_PATH_PREFIX = f"{os.environ['HOME']}/.rustup/toolchains/stable-aarch64-apple-darwin/bin"

N_COLDSTART = 30    # repetitions for lane 1 timing
N_PARSE     = 5     # repetitions for lane 2 timing
N_SELECT    = 15    # repetitions for lane 3 timing
N_INSERT    = 5     # repetitions for lane 4 timing


@dataclass
class Target:
    key: str
    label: str
    invoke: list[str]            # argv prefix; a db-path and a sql string will be appended
    env: dict | None = None      # optional env override


def build_targets() -> list[Target]:
    out = []
    if C_CLI.exists():
        out.append(Target("leap-c", "leap-c", [str(C_CLI)]))
    if RUST_CLI.exists():
        out.append(Target("leap-rust", "leap-rust", [str(RUST_CLI)]))
    else:
        # fallback to cargo run — slower per invocation but always available
        out.append(Target("leap-rust", "leap-rust",
                          ["cargo", "run", "--release", "--quiet", "--bin", "sqlite-leap-cli", "--"],
                          env={"CARGO_TARGET_DIR": str(REPO / "src-rust/target")}))
    mainline = shutil.which("sqlite3")
    if mainline:
        out.append(Target("mainline", "mainline-sqlite3", [mainline]))
    return out


def ensure_rust_binary_built():
    """Pre-build the Rust CLI so bench numbers don't include compile time."""
    print("[bench] ensuring rust release build is warm...", file=sys.stderr)
    env = os.environ.copy()
    env["PATH"] = f"{RUSTUP_CARGO_PATH_PREFIX}:{env['PATH']}"
    subprocess.run(
        ["cargo", "build", "--release", "--quiet", "--bin", "sqlite-leap-cli"],
        cwd=str(REPO / "src-rust"), env=env, check=True,
    )


def invoke(target: Target, db: Path, sql: str) -> tuple[float, int]:
    """Run target with (db, sql). Returns (wall_seconds, return_code). Measured via perf_counter_ns, excluding only the Python overhead around subprocess.run."""
    cmd = target.invoke + [str(db), sql]
    env = os.environ.copy()
    if target.env:
        env.update(target.env)
    t0 = time.perf_counter_ns()
    proc = subprocess.run(cmd, capture_output=True, env=env)
    dt = (time.perf_counter_ns() - t0) / 1e9
    return dt, proc.returncode


def median_of(samples: list[float]) -> float:
    return statistics.median(samples)


# ---- Lane 1 — cold start -----------------------------------------------

def lane1_cold_start(targets: list[Target]) -> dict[str, float]:
    """Open a fresh empty DB + run `SELECT 1;`. Each iteration starts from a non-existent path."""
    print("\n=== Lane 1 — cold start (open + 1 query, median wall seconds) ===")
    results = {}
    with tempfile.TemporaryDirectory(prefix="bench-l1-") as td:
        td = Path(td)
        for tgt in targets:
            samples = []
            for i in range(N_COLDSTART):
                db = td / f"l1-{tgt.key}-{i}.db"
                if db.exists():
                    db.unlink()
                dt, rc = invoke(tgt, db, "SELECT 1;")
                if rc != 0 and tgt.key.startswith("leap") and i == 0:
                    # leap builds may need to CREATE TABLE first — but SELECT 1 has no FROM
                    # so should succeed. If it fails, note and skip.
                    print(f"  {tgt.label} rc={rc} on cold-start SELECT 1;, skipping")
                    break
                samples.append(dt)
            if samples:
                med = median_of(samples)
                results[tgt.key] = med
                print(f"  {tgt.label:>20s}: {med*1000:8.2f} ms   (n={len(samples)}, min={min(samples)*1000:.2f}, max={max(samples)*1000:.2f})")
    return results


# ---- Lane 2 — parse speed ---------------------------------------------

def lane2_parse_speed(targets: list[Target]) -> dict[str, float]:
    """Execute a big batch of simple INSERTs in one invocation. Parse cost dominates."""
    print("\n=== Lane 2 — parse-heavy workload (5000 trivial INSERTs, median wall seconds) ===")
    N = 5000
    setup_sql = "CREATE TABLE t (x INTEGER);"
    batch = "".join(f"INSERT INTO t VALUES ({i});" for i in range(N))
    sql = setup_sql + batch
    results = {}
    with tempfile.TemporaryDirectory(prefix="bench-l2-") as td:
        td = Path(td)
        for tgt in targets:
            samples = []
            for i in range(N_PARSE):
                db = td / f"l2-{tgt.key}-{i}.db"
                if db.exists():
                    db.unlink()
                # mainline will want BEGIN; ... COMMIT; for any reasonable bench
                if tgt.key == "mainline":
                    wrapped = f"BEGIN;{sql}COMMIT;"
                else:
                    wrapped = sql
                dt, rc = invoke(tgt, db, wrapped)
                if rc != 0:
                    print(f"  {tgt.label} rc={rc} at iter {i}, skipping")
                    break
                samples.append(dt)
            if samples:
                med = median_of(samples)
                results[tgt.key] = med
                print(f"  {tgt.label:>20s}: {med:7.3f} s   ({N/med:8.0f} stmts/s)   n={len(samples)}")
    return results


# ---- Lane 3 — in-memory-ish SELECT ------------------------------------

def lane3_select_speed(targets: list[Target]) -> dict[str, float]:
    """
    Populate a DB once (not timed) with 10k rows, then measure the time to run
    `SELECT x FROM t;` which scans all rows. For leap builds, every invocation
    reads the entire file into RAM (per our simplicity strategy), so the cost
    includes one open + scan. For mainline it uses a page cache but cold on each call.
    Not a pure in-memory benchmark — honest label is "cold-scan of a populated DB".
    """
    print("\n=== Lane 3 — full-scan of 10k-row DB (median wall seconds; disk-cached) ===")
    N_ROWS = 10000
    results = {}
    with tempfile.TemporaryDirectory(prefix="bench-l3-") as td:
        td = Path(td)
        # Build one populated DB using mainline (since it's fastest at bulk insert) and SHARE it across targets.
        populated = td / "populated.db"
        pop_sql = "CREATE TABLE t (x INTEGER);BEGIN;" + "".join(f"INSERT INTO t VALUES ({i});" for i in range(N_ROWS)) + "COMMIT;"
        subprocess.run(["sqlite3", str(populated)], input=pop_sql, text=True, check=True)
        # Warm the OS page cache with one read
        _ = populated.read_bytes()
        for tgt in targets:
            samples = []
            for _ in range(N_SELECT):
                db_copy = td / f"l3-{tgt.key}-scan.db"
                shutil.copyfile(populated, db_copy)
                dt, rc = invoke(tgt, db_copy, "SELECT x FROM t;")
                if rc != 0:
                    print(f"  {tgt.label} rc={rc} during scan, skipping")
                    break
                samples.append(dt)
            if samples:
                med = median_of(samples)
                results[tgt.key] = med
                print(f"  {tgt.label:>20s}: {med*1000:7.2f} ms   ({N_ROWS/med:9.0f} rows/s)   n={len(samples)}")
    return results


# ---- Lane 4 — INSERT throughput ---------------------------------------

def lane4_insert_throughput(targets: list[Target]) -> dict[str, float]:
    """10k INSERTs in one session. Mainline uses rollback journal; leap uses slurp/flush."""
    print("\n=== Lane 4 — 10k INSERTs single-writer (median wall seconds) ===")
    N = 10000
    setup = "CREATE TABLE t (x INTEGER);"
    inserts = "".join(f"INSERT INTO t VALUES ({i});" for i in range(N))
    sql_leap = setup + inserts
    sql_main = f"{setup}BEGIN;{inserts}COMMIT;"
    results = {}
    with tempfile.TemporaryDirectory(prefix="bench-l4-") as td:
        td = Path(td)
        for tgt in targets:
            samples = []
            for i in range(N_INSERT):
                db = td / f"l4-{tgt.key}-{i}.db"
                if db.exists():
                    db.unlink()
                sql = sql_main if tgt.key == "mainline" else sql_leap
                dt, rc = invoke(tgt, db, sql)
                if rc != 0:
                    print(f"  {tgt.label} rc={rc}, skipping")
                    break
                samples.append(dt)
            if samples:
                med = median_of(samples)
                results[tgt.key] = med
                print(f"  {tgt.label:>20s}: {med:7.3f} s   ({N/med:8.0f} inserts/s)   n={len(samples)}")
    return results


# ---- Lane 5 — binary size ---------------------------------------------

def lane5_binary_size() -> dict[str, int]:
    """Bytes on disk for each binary."""
    print("\n=== Lane 5 — binary size (bytes) ===")
    results = {}
    candidates = [
        ("leap-c-cli",        C_CLI),
        ("leap-rust-cli",     RUST_CLI),
        ("leap-rust-wasm",    WASM_ART),
    ]
    mainline_path = shutil.which("sqlite3")
    if mainline_path:
        candidates.append(("mainline-sqlite3", Path(mainline_path)))
    for label, p in candidates:
        if not p.exists():
            print(f"  {label:>20s}:  n/a (not built at {p})")
            continue
        size = p.stat().st_size
        results[label] = size
        print(f"  {label:>20s}: {size:>10,} bytes  ({size/1024:.1f} KiB)")
    return results


# ---- Lane 6 — memory footprint ----------------------------------------

def lane6_memory(targets: list[Target]) -> dict[str, int]:
    """Peak RSS (macOS: bytes via /usr/bin/time -l) on a small open+select."""
    print("\n=== Lane 6 — peak RSS on open+small-SELECT (bytes via /usr/bin/time -l) ===")
    results = {}
    with tempfile.TemporaryDirectory(prefix="bench-l6-") as td:
        td = Path(td)
        # Populate a tiny DB beforehand.
        small_db = td / "small.db"
        subprocess.run(["sqlite3", str(small_db)],
                       input="CREATE TABLE t (x INTEGER); INSERT INTO t VALUES (1); INSERT INTO t VALUES (2);",
                       text=True, check=True)
        for tgt in targets:
            db_copy = td / f"l6-{tgt.key}.db"
            shutil.copyfile(small_db, db_copy)
            cmd = ["/usr/bin/time", "-l"] + tgt.invoke + [str(db_copy), "SELECT x FROM t;"]
            env = os.environ.copy()
            if tgt.env:
                env.update(tgt.env)
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
            m = re.search(r"(\d+)\s+maximum resident set size", proc.stderr)
            if m:
                rss = int(m.group(1))
                results[tgt.key] = rss
                print(f"  {tgt.label:>20s}: {rss:>12,} bytes  ({rss/1024/1024:.2f} MiB)")
            else:
                print(f"  {tgt.label:>20s}: failed to parse /usr/bin/time output")
    return results


# ---- orchestration ----------------------------------------------------

def main() -> int:
    ensure_rust_binary_built()
    targets = build_targets()
    for t in targets:
        print(f"[bench] target detected: {t.label} -> {' '.join(t.invoke)}")
    print()

    l1 = lane1_cold_start(targets)
    l2 = lane2_parse_speed(targets)
    l3 = lane3_select_speed(targets)
    l4 = lane4_insert_throughput(targets)
    l5 = lane5_binary_size()
    l6 = lane6_memory(targets)

    # write CSV
    BENCH_RESULTS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d-%H%M")
    csv_path = BENCH_RESULTS / f"{ts}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["lane", "metric", "target", "value", "unit"])
        for k, v in l1.items():
            w.writerow(["1", "cold_start_open_plus_select_1", k, f"{v:.6f}", "s"])
        for k, v in l2.items():
            w.writerow(["2", "parse_heavy_5000_inserts", k, f"{v:.6f}", "s"])
        for k, v in l3.items():
            w.writerow(["3", "full_scan_10k_rows", k, f"{v:.6f}", "s"])
        for k, v in l4.items():
            w.writerow(["4", "10k_inserts_single_writer", k, f"{v:.6f}", "s"])
        for k, v in l5.items():
            w.writerow(["5", "binary_size", k, str(v), "bytes"])
        for k, v in l6.items():
            w.writerow(["6", "peak_rss_small_db_open_plus_select", k, str(v), "bytes"])

    print()
    print(f"[bench] CSV written to {csv_path}")
    # summary ratios — leap vs mainline (if mainline present)
    print("\n=== Ratios vs mainline (lower-is-better for time; lower-is-better for size/RSS) ===")
    def ratio(metric_dict, leap_key, main_key="mainline"):
        if main_key in metric_dict and leap_key in metric_dict:
            r = metric_dict[leap_key] / metric_dict[main_key]
            return f"{r:.2f}×"
        return "n/a"
    rows = [
        ("L1 cold start",       ratio(l1, "leap-c"),     ratio(l1, "leap-rust")),
        ("L2 parse 5k inserts", ratio(l2, "leap-c"),     ratio(l2, "leap-rust")),
        ("L3 scan 10k rows",    ratio(l3, "leap-c"),     ratio(l3, "leap-rust")),
        ("L4 insert 10k",       ratio(l4, "leap-c"),     ratio(l4, "leap-rust")),
        ("L5 binary size",      ratio(l5, "leap-c-cli",  "mainline-sqlite3"),
                                ratio(l5, "leap-rust-cli", "mainline-sqlite3")),
        ("L6 peak RSS",         ratio(l6, "leap-c"),     ratio(l6, "leap-rust")),
    ]
    print(f"  {'lane':<22s}  {'leap-c':>10s}  {'leap-rust':>10s}")
    for name, c_r, r_r in rows:
        print(f"  {name:<22s}  {c_r:>10s}  {r_r:>10s}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
