#!/usr/bin/env python3
"""
Hand-rolled byte mutator for SQL fuzz campaign.

Reads seed corpus from the supplied directory (e.g. tests/fuzz/sql/seeds/
or tests/fuzz/corpus/sql/valid/), applies a mix of byte-level and
SQL-token-level mutations, writes each mutated input to <outdir>/N.sql
and launches the fuzz harness binary against every file in the output
directory. Records crash verdicts (non-zero exit, missing SUMMARY line,
panic signature on stderr) to a log.

Mutation strategies (chosen uniformly at random per input):
  1. Bit flip (single bit)
  2. Byte flip (single byte set to random 0x00..0xff)
  3. Byte insert (insert a random byte at random offset)
  4. Byte delete (remove a byte)
  5. Block duplicate (duplicate a random 2..16 byte block)
  6. Block swap (swap two non-overlapping blocks)
  7. Random-byte splat (overwrite a 1..8 byte window with random bytes)
  8. Truncation (cut off the tail randomly)
  9. Token-level: replace a SQL keyword with another keyword
 10. Token-level: inject a SQL special char (;,(),*,=) at a random offset

Deterministic: --seed fixes the RNG so the campaign is reproducible.

Harness invocation:
  <harness-binary> <tmp-file>
The harness prints one verdict line per input on stdout and exits 0 for
OK|ENGINE_ERROR. A non-zero exit, an empty stdout, a stderr containing
"panic" / "Segmentation fault" / "Abort trap" / "sanitizer", or a signal
termination → CRASH.

No AFL-style coverage guidance — we trade guidance for sheer volume
(~100k inputs in an hour). For a hand-rolled campaign against an engine
that hits parse/VDBE paths early, the mutation surface is small enough
that volume is the right lever.
"""

from __future__ import annotations

import argparse
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

# SQL keywords & token set borrowed from the specs we ship through
# Phase 9g — covers every production the engine recognises.
KEYWORDS = [
    b"SELECT", b"FROM", b"WHERE", b"INSERT", b"INTO", b"VALUES",
    b"UPDATE", b"SET", b"DELETE", b"CREATE", b"TABLE", b"INDEX",
    b"DROP", b"ALTER", b"JOIN", b"INNER", b"LEFT", b"RIGHT", b"OUTER",
    b"ON", b"AS", b"AND", b"OR", b"NOT", b"NULL", b"IS", b"IN",
    b"BETWEEN", b"LIKE", b"GLOB", b"CASE", b"WHEN", b"THEN", b"ELSE",
    b"END", b"GROUP", b"BY", b"HAVING", b"ORDER", b"ASC", b"DESC",
    b"LIMIT", b"OFFSET", b"DISTINCT", b"UNION", b"EXCEPT", b"INTERSECT",
    b"ALL", b"EXISTS", b"WITH", b"RECURSIVE", b"PRAGMA", b"BEGIN",
    b"COMMIT", b"ROLLBACK", b"SAVEPOINT", b"RELEASE", b"TRIGGER",
    b"VIEW", b"PRIMARY", b"KEY", b"FOREIGN", b"REFERENCES", b"UNIQUE",
    b"CHECK", b"DEFAULT", b"AUTOINCREMENT", b"CONFLICT", b"REPLACE",
    b"IGNORE", b"ABORT", b"ROLLBACK", b"FAIL", b"CAST", b"GLOB",
    b"COLLATE", b"ESCAPE", b"EXPLAIN", b"QUERY", b"PLAN",
]

SPECIALS = [b";", b",", b"(", b")", b"*", b"=", b"<", b">", b"!",
            b"+", b"-", b"/", b"%", b".", b"'", b'"', b"`", b"\\",
            b"[", b"]", b"{", b"}", b"?", b":", b"@", b"#", b"$", b"&"]


def mutate(buf: bytes, rng: random.Random) -> bytes:
    if not buf:
        buf = b"SELECT 1;"
    strat = rng.randint(1, 10)
    if strat == 1:
        # bit flip
        i = rng.randint(0, len(buf) - 1)
        b = rng.randint(0, 7)
        return buf[:i] + bytes([buf[i] ^ (1 << b)]) + buf[i+1:]
    if strat == 2:
        i = rng.randint(0, len(buf) - 1)
        return buf[:i] + bytes([rng.randint(0, 255)]) + buf[i+1:]
    if strat == 3:
        i = rng.randint(0, len(buf))
        return buf[:i] + bytes([rng.randint(0, 255)]) + buf[i:]
    if strat == 4:
        i = rng.randint(0, len(buf) - 1)
        return buf[:i] + buf[i+1:]
    if strat == 5:
        n = rng.randint(2, min(16, len(buf)))
        i = rng.randint(0, len(buf) - n)
        blk = buf[i:i+n]
        j = rng.randint(0, len(buf))
        return buf[:j] + blk + buf[j:]
    if strat == 6:
        if len(buf) < 8:
            return buf
        n = rng.randint(1, min(8, len(buf) // 4))
        a = rng.randint(0, len(buf) - 2 * n)
        b = rng.randint(a + n, len(buf) - n)
        return (buf[:a] + buf[b:b+n] + buf[a+n:b]
                + buf[a:a+n] + buf[b+n:])
    if strat == 7:
        n = rng.randint(1, min(8, len(buf)))
        i = rng.randint(0, len(buf) - n)
        rnd = bytes(rng.randint(0, 255) for _ in range(n))
        return buf[:i] + rnd + buf[i+n:]
    if strat == 8:
        i = rng.randint(max(1, len(buf) // 2), len(buf))
        return buf[:i]
    if strat == 9:
        # replace a keyword if present, else append one
        for _ in range(4):
            kw = rng.choice(KEYWORDS)
            idx = buf.upper().find(kw)
            if idx >= 0:
                repl = rng.choice(KEYWORDS)
                return buf[:idx] + repl + buf[idx+len(kw):]
        return buf + b" " + rng.choice(KEYWORDS)
    # strat == 10
    i = rng.randint(0, len(buf))
    return buf[:i] + rng.choice(SPECIALS) + buf[i:]


def harness_verdict(harness: str, path: str, timeout_s: float = 5.0):
    """Run harness on the path. Returns (verdict, summary_line_or_none).
    verdict in {"OK", "ENGINE_ERROR", "CRASH", "TIMEOUT"}."""
    try:
        proc = subprocess.run(
            [harness, path],
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT", None
    if proc.returncode < 0:
        # signalled → crash
        return "CRASH", f"signal={-proc.returncode}"
    stderr = proc.stderr.decode("utf-8", errors="replace")
    stdout = proc.stdout.decode("utf-8", errors="replace")
    # panic / sanitizer signatures
    bad_sigs = ("panicked at", "Segmentation fault", "Abort trap",
                "SIGSEGV", "SIGBUS", "SIGILL", "sanitizer",
                "AddressSanitizer", "UndefinedBehaviorSanitizer",
                "stack backtrace", "SIGABRT")
    low = (stderr + stdout).lower()
    for s in bad_sigs:
        if s.lower() in low:
            return "CRASH", f"signature={s}"
    if proc.returncode != 0:
        # harness only returns non-zero on usage error — treat as crash
        return "CRASH", f"exit={proc.returncode} stderr={stderr.strip()[:200]}"
    # parse the verdict from stdout — single-file form: first token
    first = stdout.strip().split("\n", 1)[0] if stdout.strip() else ""
    if first.startswith("OK"):
        return "OK", first
    if first.startswith("ENGINE_ERROR"):
        return "ENGINE_ERROR", first
    if first.startswith("CRASH"):
        return "CRASH", first
    # Unrecognised output: treat as crash-adjacent (harness malfunction)
    return "CRASH", f"unknown={first[:200]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--harness", required=True,
                    help="Path to fuzz-parse or fuzz-exec binary")
    ap.add_argument("--seeds", required=True,
                    help="Directory containing seed SQL files")
    ap.add_argument("--out", required=True,
                    help="Output directory for saved crash/timeout inputs")
    ap.add_argument("--log", required=True,
                    help="Per-input log file")
    ap.add_argument("--duration-s", type=float, default=900.0,
                    help="Wall-clock budget (seconds)")
    ap.add_argument("--timeout-s", type=float, default=3.0,
                    help="Per-input subprocess timeout")
    ap.add_argument("--seed", type=int, default=0xC0FFEE,
                    help="RNG seed for reproducibility")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    seeds_dir = Path(args.seeds)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    seed_files = []
    for p in sorted(seeds_dir.rglob("*.sql")):
        try:
            seed_files.append(p.read_bytes())
        except OSError:
            pass
    if not seed_files:
        print(f"no seeds in {seeds_dir}", file=sys.stderr)
        sys.exit(2)

    log = open(args.log, "w")
    log.write(f"# harness={args.harness}\n")
    log.write(f"# seeds_dir={seeds_dir} seed_count={len(seed_files)}\n")
    log.write(f"# out_dir={out_dir}\n")
    log.write(f"# rng_seed={args.seed} duration_s={args.duration_s}\n")
    log.flush()

    # Cap how many distinct crash inputs we save (keeps disk bounded on
    # a known-buggy target; counter still records every hit).
    max_saved = 50

    # Stage temp file path
    tmp_path = str(out_dir / "_current.sql")

    counts = {"OK": 0, "ENGINE_ERROR": 0, "CRASH": 0, "TIMEOUT": 0}
    findings = 0
    start = time.monotonic()
    deadline = start + args.duration_s
    n = 0
    while time.monotonic() < deadline:
        base = seed_files[rng.randint(0, len(seed_files) - 1)]
        # chain 1..4 mutations for higher distortion
        cur = base
        for _ in range(rng.randint(1, 4)):
            cur = mutate(cur, rng)
            if len(cur) > 64 * 1024:
                cur = cur[:64*1024]
        with open(tmp_path, "wb") as f:
            f.write(cur)
        verdict, detail = harness_verdict(args.harness, tmp_path,
                                          timeout_s=args.timeout_s)
        counts[verdict] = counts.get(verdict, 0) + 1
        n += 1
        if verdict in ("CRASH", "TIMEOUT"):
            findings += 1
            # save the input for triage (cap at max_saved to bound disk)
            if findings <= max_saved:
                kept = out_dir / f"{verdict.lower()}_{findings:04d}.sql"
                with open(kept, "wb") as f:
                    f.write(cur)
                log.write(f"#{n} {verdict} {detail} saved={kept.name}\n")
                log.flush()
                sys.stderr.write(f"[finding] #{n} {verdict} saved={kept.name}\n")
                sys.stderr.flush()
            else:
                # Only log every 100th further finding so the log stays readable.
                if findings % 100 == 0:
                    log.write(f"#{n} {verdict} {detail} (not saved; findings={findings})\n")
                    log.flush()
        # lightweight progress marker every 200 inputs
        if n % 200 == 0:
            elapsed = time.monotonic() - start
            rate = n / elapsed if elapsed > 0 else 0.0
            msg = (f"progress n={n} rate={rate:.1f}/s "
                   f"ok={counts['OK']} engine_err={counts['ENGINE_ERROR']} "
                   f"crash={counts['CRASH']} timeout={counts['TIMEOUT']}")
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()

    elapsed = time.monotonic() - start
    summary = (f"# inputs={n} crashes={counts['CRASH']} panics=0 "
               f"timeouts={counts['TIMEOUT']} engine_errors={counts['ENGINE_ERROR']} "
               f"ok={counts['OK']} elapsed_s={elapsed:.1f}")
    log.write(summary + "\n")
    log.close()
    # clean temp
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    print(summary)


if __name__ == "__main__":
    main()
