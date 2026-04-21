#!/usr/bin/env python3
"""Plot a results CSV produced by bench/run-all.sh.

One bar chart per lane, one bar per target. PNGs are written next to the
input CSV with suffix .<lane>.png. matplotlib is optional — if it's not
installed the script prints an install hint and exits cleanly (non-zero).

Usage:
    ./bench/plot.py bench/results/2026-04-20-mymac.csv
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: plot.py <results.csv>", file=sys.stderr)
        return 2
    csv_path = Path(argv[1])
    if not csv_path.is_file():
        print(f"not a file: {csv_path}", file=sys.stderr)
        return 2

    try:
        import matplotlib  # noqa: F401
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(
            "matplotlib is not installed. Install with: pip install matplotlib",
            file=sys.stderr,
        )
        return 3

    # lane -> list[(target, value, units)]
    by_lane: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    with csv_path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                val = float(row["value"])
            except (ValueError, KeyError):
                # NA rows (missing binary) — skip silently.
                continue
            by_lane[row["lane"]].append((row["target"], val, row["units"]))

    if not by_lane:
        print("no plottable rows in CSV", file=sys.stderr)
        return 1

    stem = csv_path.with_suffix("")
    for lane, rows in sorted(by_lane.items()):
        rows.sort(key=lambda r: r[0])
        targets = [r[0] for r in rows]
        values = [r[1] for r in rows]
        units = rows[0][2]

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.bar(targets, values)
        ax.set_title(f"{lane} ({units})")
        ax.set_ylabel(units)
        ax.tick_params(axis="x", rotation=20)
        fig.tight_layout()

        out = Path(f"{stem}.{lane}.png")
        fig.savefig(out, dpi=120)
        plt.close(fig)
        print(f"wrote {out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
