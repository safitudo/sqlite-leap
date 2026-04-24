#!/usr/bin/env python3
"""eqcheck — run the cross-target equivalence harness over a corpus file.

Invokes each available per-target runner with the corpus path, reports
OK / FAIL / SKIP per target, and exits non-zero if any non-SKIP runner
fails. A clean exit means the spec emitted equivalent implementations
for this corpus entry.

Runners known to this orchestrator:
    rust   — `cargo run --release --example eq_runner -- <corpus>`
    python — `python3 src-python/eq_runner.py <corpus>`
    go     — `go run ./cmd/eq_runner <corpus>`
    zig    — SKIP (VdbeState constructor mapping pending)
    c      — SKIP (VdbeState constructor mapping pending)

Usage:
    parts/eq-harness/eqcheck.py parts/eq-harness/corpus/count_star_x3.json
    parts/eq-harness/eqcheck.py --all        # run every corpus file
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

RUNNERS = [
    {
        "name": "rust",
        "available": lambda: (REPO / "src-rust/Cargo.toml").exists(),
        "argv": lambda corpus: [
            "cargo", "run", "--release", "--quiet",
            "--manifest-path", str(REPO / "src-rust/Cargo.toml"),
            "--example", "eq_runner",
            "--", str(corpus),
        ],
        "cwd": REPO,
    },
    {
        "name": "python",
        "available": lambda: (REPO / "src-python/eq_runner.py").exists(),
        "argv": lambda corpus: ["python3", str(REPO / "src-python/eq_runner.py"), str(corpus)],
        "env_extra": {"PYTHONPATH": str(REPO / "src-python")},
        "cwd": REPO,
    },
    {
        "name": "go",
        "available": lambda: (REPO / "src-go/cmd/eq_runner/main.go").exists(),
        "argv": lambda corpus: ["go", "run", "./cmd/eq_runner", str(corpus)],
        "cwd": REPO / "src-go",
    },
    {
        "name": "zig",
        "available": lambda: False,   # SKIP until ctor mapping ships
        "skip_reason": "VdbeState ctor mapping pending",
    },
    {
        "name": "c",
        "available": lambda: False,   # SKIP until ctor mapping ships
        "skip_reason": "VdbeState ctor mapping pending",
    },
]


def run_one(runner: dict, corpus: Path) -> tuple[str, int | None, str]:
    """Returns (status, exit_code|None, detail)."""
    if not runner["available"]():
        return ("SKIP", None, runner.get("skip_reason", "unavailable"))
    env = dict(os.environ)
    for k, v in (runner.get("env_extra") or {}).items():
        env[k] = v
    try:
        r = subprocess.run(
            runner["argv"](corpus),
            cwd=runner["cwd"],
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        return ("SKIP", None, f"missing toolchain: {e}")
    detail = (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else ""
    return (("OK" if r.returncode == 0 else "FAIL"), r.returncode, detail)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpus", nargs="?", type=Path, help="Corpus JSON file (or --all).")
    ap.add_argument("--all", action="store_true", help="Run every *.json under corpus/.")
    args = ap.parse_args()

    if args.all:
        files = sorted((REPO / "parts/eq-harness/corpus").glob("*.json"))
    elif args.corpus is not None:
        files = [args.corpus]
    else:
        ap.print_usage(file=sys.stderr)
        return 2

    any_fail = False
    for corpus in files:
        print(f"\n{corpus.name}:")
        for runner in RUNNERS:
            status, code, detail = run_one(runner, corpus)
            suffix = f"  ({detail})" if detail else ""
            print(f"  {runner['name']:<6} {status}{suffix}")
            if status == "FAIL":
                any_fail = True
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
