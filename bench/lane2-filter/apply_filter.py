#!/usr/bin/env python3
"""Apply the 3-engine intersection filter to corpus.sql.
Statements are split on `;` outside single-quoted strings (matching
the C/Rust split_stmts logic). Reads masks (one OK/ERR per line) for
mainline / leap-c / leap-rust. Emits a statement to the output file
only when ALL THREE masks say OK.
"""
import sys
from pathlib import Path

corpus = Path(sys.argv[1]).read_text()
mask_main = Path(sys.argv[2]).read_text().splitlines()
mask_c = Path(sys.argv[3]).read_text().splitlines()
mask_rust = Path(sys.argv[4]).read_text().splitlines()
out_path = Path(sys.argv[5])

# Mirror split_stmts: split on ';' outside single quotes, trim each.
stmts = []
buf = []
in_str = False
for ch in corpus:
    if ch == "'":
        in_str = not in_str
    if ch == ';' and not in_str:
        s = ''.join(buf).strip()
        if s:
            stmts.append(s)
        buf = []
    else:
        buf.append(ch)
tail = ''.join(buf).strip()
if tail:
    stmts.append(tail)

assert len(stmts) == len(mask_main) == len(mask_c) == len(mask_rust), \
    f"length mismatch: stmts={len(stmts)} main={len(mask_main)} c={len(mask_c)} rust={len(mask_rust)}"

total = len(stmts)
kept_lines = []
kept = 0
dropped_main = dropped_c = dropped_rust = 0
for s, mm, mc, mr in zip(stmts, mask_main, mask_c, mask_rust):
    if mm == "OK" and mc == "OK" and mr == "OK":
        kept_lines.append(s + ";")
        kept += 1
    else:
        if mm != "OK": dropped_main += 1
        if mc != "OK": dropped_c += 1
        if mr != "OK": dropped_rust += 1

dropped = total - kept
header = (
    "-- filtered 2026-04-27: dropped {drop} statements ({pct:.1f}% of original)\n"
    "-- where leap-c or leap-rust (or mainline) failed to prepare;\n"
    "-- remaining {keep} statements all 3 engines parse.\n"
    "-- per-engine drops (non-exclusive): mainline={dm} leap-c={dc} leap-rust={dr}\n"
).format(drop=dropped, pct=100.0*dropped/total, keep=kept,
         dm=dropped_main, dc=dropped_c, dr=dropped_rust)

out_path.write_text(header + "\n".join(kept_lines) + "\n")
print(f"kept={kept} dropped={dropped} total={total}")
print(f"per-engine drops: mainline={dropped_main} leap-c={dropped_c} leap-rust={dropped_rust}")
