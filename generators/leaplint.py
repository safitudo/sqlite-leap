#!/usr/bin/env python3
"""leaplint — §Generation-scope linter + toolchain smoke for sqlite-leap v2 emissions.

Two modes:

1. **Lint mode (default)** — enforces `spec/part-conventions.spec.md`
   §"Generation scope": emitted target code must not contain inline
   tests, stubs, invented helpers, test-only constructors, or entry
   points. Walks `src-{rust,c,zig,go,python}/`; only lints files
   whose first 3 lines contain the marker "Generated from".

2. **Toolchain check mode (`--check-toolchain`)** — runs each
   target's canonical behavioral smoke (CountStar×3 → Integer(3))
   and reports pass/fail per target. The smokes exercise the
   canonical VdbeState ctor + execute_program surface declared in
   parts/vdbe/shapes.json. Failure signals the per-target mapping's
   "Toolchain pin" section is out of date — re-emit, don't
   hand-patch. See feedback_target_toolchain_pin.md.

Usage:
    ./leaplint.py                       # lint everything
    ./leaplint.py --target rust         # restrict lint to one target
    ./leaplint.py --path src-c/vdbe/opcodes_rows.c
    ./leaplint.py --check-toolchain     # run all 5 behavioral smokes
    ./leaplint.py --check-toolchain --target zig  # one target
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# target -> (src-tree, ext list, rules).
# Each rule is (rule_name, compiled regex, description-for-why-banned).
# Patterns are line-anchored where anchor is meaningful; otherwise
# bare (applied per-line).

_MARKER = re.compile(r"Generated from")
_RUNNER_MARKER = re.compile(r"leaplint:\s*runner")

# Rules in this set are waived for files marked `leaplint: runner`
# (e.g. file-format read runners, eq_runners, smoke binaries). The
# §Generation-scope spec authorizes a `main`/entry point on these —
# everything else (inline tests, stubs, invented helpers, NotImplementedError)
# still fires.
ENTRYPOINT_RULES = {
    "int-main",        # c
    "pub-main",        # zig
    "bare-main",       # zig
    "main-guard",      # python
}

TARGETS = {
    "rust": {
        "tree": "src-rust",
        "exts": {".rs"},
        "rules": [
            ("inline-test-attr",   re.compile(r"^\s*#\[test\]")),
            ("cfg-test-attr",      re.compile(r"^\s*#\[cfg\(test\)\]")),
            ("cfg-any-test",       re.compile(r"^\s*#\[cfg\(any\(test,")),
            ("mod-tests",          re.compile(r"^\s*(?:pub\s+)?mod\s+tests?\s*\{?")),
            ("mod-test",           re.compile(r"^\s*(?:pub\s+)?mod\s+test\s*\{?")),
            ("unimplemented-macro", re.compile(r"\bunimplemented!\s*\(")),
            ("todo-macro",         re.compile(r"\btodo!\s*\(")),
            ("stub-fn-name",       re.compile(r"\bfn\s+\w*_stub\b")),
        ],
    },
    "c": {
        "tree": "src-c",
        "exts": {".c", ".h"},
        "rules": [
            ("int-main",           re.compile(r"^\s*(?:static\s+)?int\s+main\s*\(")),
            ("ifdef-test",         re.compile(r"^\s*#\s*ifdef\s+TEST\b")),
            ("ifdef-unit-test",    re.compile(r"^\s*#\s*ifdef\s+UNIT_TEST\b")),
            ("ifndef-ndebug-test", re.compile(r"^\s*#\s*ifndef\s+NDEBUG.*TEST")),
            ("stub-fn-name",       re.compile(r"\b\w*_stub\s*\(")),
        ],
    },
    "zig": {
        "tree": "src-zig",
        "exts": {".zig"},
        "rules": [
            ("test-block",         re.compile(r"^\s*test\s*\"")),
            ("pub-main",           re.compile(r"^\s*pub\s+fn\s+main\s*\(")),
            ("bare-main",          re.compile(r"^\s*fn\s+main\s*\(")),
            ("panic-not-impl",     re.compile(r"@panic\s*\(\s*\"(?:not implemented|unimplemented|TODO)")),
            ("stub-fn-name",       re.compile(r"\bfn\s+\w*[Ss]tub\w*\s*\(")),
        ],
    },
    "go": {
        "tree": "src-go",
        "exts": {".go"},
        "rules": [
            # `func TestXxx(t *testing.T)` — forbidden regardless of file.
            ("func-Test",          re.compile(r"^\s*func\s+Test[A-Z]\w*\s*\(")),
            # `_test.go` files shouldn't exist at all in emissions.
            ("new-for-test",       re.compile(r"\bNewForTest\b")),
            ("panic-not-impl",     re.compile(r"panic\s*\(\s*\"(?:not implemented|unimplemented|TODO)")),
            ("stub-fn-name",       re.compile(r"\bfunc\s+\w*[Ss]tub\w*\s*\(")),
        ],
    },
    "python": {
        "tree": "src-python",
        "exts": {".py"},
        "rules": [
            ("import-unittest",    re.compile(r"^\s*import\s+unittest\b")),
            ("from-unittest",      re.compile(r"^\s*from\s+unittest\b")),
            ("import-pytest",      re.compile(r"^\s*import\s+pytest\b")),
            ("class-Test",         re.compile(r"^\s*class\s+\w*Test\w*\b")),
            ("main-guard",         re.compile(r"^\s*if\s+__name__\s*==\s*['\"]__main__['\"]")),
            ("stub-class",         re.compile(r"^\s*class\s+_Stub\w*\b")),
            ("not-implemented",    re.compile(r"\braise\s+NotImplementedError\b")),
        ],
    },
}


def has_marker(path: Path) -> bool:
    """True if any of the first 3 lines mentions 'Generated from'."""
    try:
        with path.open("r", errors="replace") as f:
            for _, line in zip(range(3), f):
                if _MARKER.search(line):
                    return True
    except OSError:
        return False
    return False


def is_runner(path: Path) -> bool:
    """True if any of the first 8 lines declares `leaplint: runner`.

    A runner is an authorized entry-point file (e.g. fileformat_read_runner.py,
    tokenize_smoke.rs) declared as such in its part's master.md. The linter
    waives entry-point rules on these; §Generation-scope still applies to
    everything else.
    """
    try:
        with path.open("r", errors="replace") as f:
            for _, line in zip(range(8), f):
                if _RUNNER_MARKER.search(line):
                    return True
    except OSError:
        return False
    return False


def lint_file(path: Path, rules: list[tuple[str, re.Pattern]],
              runner: bool = False) -> list[tuple[int, str, str]]:
    """Return list of (line_no, rule_name, snippet).

    When `runner` is True, entry-point rules (ENTRYPOINT_RULES) are skipped.
    """
    active_rules = [(n, p) for (n, p) in rules if not (runner and n in ENTRYPOINT_RULES)]
    out: list[tuple[int, str, str]] = []
    try:
        with path.open("r", errors="replace") as f:
            for lineno, raw in enumerate(f, start=1):
                line = raw.rstrip("\n")
                for name, pat in active_rules:
                    if pat.search(line):
                        snippet = line.strip()
                        if len(snippet) > 100:
                            snippet = snippet[:97] + "..."
                        out.append((lineno, name, snippet))
                        break
    except OSError as e:
        out.append((0, "read-error", str(e)))
    return out


def walk_target(target: str, only_path: Path | None) -> list[Path]:
    spec = TARGETS[target]
    tree = REPO_ROOT / spec["tree"]
    if not tree.exists():
        return []
    files: list[Path] = []
    for p in tree.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in spec["exts"]:
            continue
        if only_path is not None and p != only_path:
            continue
        if not has_marker(p):
            continue
        files.append(p)
    return files


# Canonical behavioral smokes — each must exit 0 and emit a line
# that matches SMOKE_OK_PATTERN (proves the CountStar×3 → Integer(3)
# round-trip worked, not just that the process launched).
#
# `cmd` is the argv; `cwd` is repo-relative. `prepare` (optional) is
# a pre-step (e.g. build the C archive) that must succeed first.

SMOKE_OK_PATTERN = re.compile(
    r"(OK: .*CountStar.*= 3"          # rust, c, zig
    r"|OK: .*count_star_x3"           # python eq_runner (corpus is CountStar×3)
    r"|captured=3 \(ok=1\)"            # c raw line
    r"|captured=3 \(ok=true\))"        # zig, go raw line
)

def _c_prepare(timeout: float) -> tuple[bool, str]:
    """Build libleap.a + /tmp/c_smoke. Returns (ok, stderr_tail)."""
    src_c = REPO_ROOT / "src-c"
    obj_args: list[list[str]] = []
    for c in sorted(src_c.rglob("*.c")):
        if c.name == "smoke_count.c":
            continue
        obj = c.with_suffix(".o")
        obj_args.append(["cc", "-std=c11", "-Wall", "-Wno-unused-parameter",
                         f"-I{src_c}", "-c", "-o", str(obj), str(c)])
    for a in obj_args:
        r = subprocess.run(a, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return False, r.stderr[-400:]
    libleap = Path("/tmp/libleap.a")
    libleap.unlink(missing_ok=True)
    objs = [str(o) for o in sorted(src_c.rglob("*.o"))
            if o.name != "smoke_count.o"]
    r = subprocess.run(["ar", "rcs", str(libleap), *objs],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        return False, r.stderr[-400:]
    r = subprocess.run(["cc", "-std=c11", "-Wall", "-Wno-unused-parameter",
                        f"-I{src_c}", "-o", "/tmp/c_smoke",
                        str(src_c / "smoke_count.c"), str(libleap)],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        return False, r.stderr[-400:]
    return True, ""

TOOLCHAIN_SMOKES = {
    "rust": {
        "cmd": ["cargo", "run", "--release", "--quiet", "--example", "smoke_count"],
        "cwd": "src-rust",
        "prepare": None,
    },
    "c": {
        "cmd": ["/tmp/c_smoke"],
        "cwd": ".",
        "prepare": _c_prepare,
    },
    "zig": {
        "cmd": ["zig", "build", "smoke"],
        "cwd": "src-zig",
        "prepare": None,
    },
    "go": {
        "cmd": ["go", "run", "./cmd/smoke_count"],
        "cwd": "src-go",
        "prepare": None,
    },
    "python": {
        "cmd": ["python3", "src-python/eq_runner.py",
                "parts/eq-harness/corpus/count_star_x3.json"],
        "cwd": ".",
        "prepare": None,
    },
}


def check_toolchain(target: str, timeout: float = 120.0) -> tuple[bool, float, str]:
    """Run one target's behavioral smoke. Returns (ok, elapsed_s, report)."""
    spec = TOOLCHAIN_SMOKES[target]
    start = time.monotonic()
    if spec["prepare"] is not None:
        ok, err_tail = spec["prepare"](timeout)
        if not ok:
            return False, time.monotonic() - start, f"prepare failed: {err_tail}"
    cwd = REPO_ROOT / spec["cwd"]
    try:
        r = subprocess.run(spec["cmd"], cwd=cwd, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, time.monotonic() - start, f"timeout after {timeout}s"
    except FileNotFoundError as e:
        return False, time.monotonic() - start, f"binary missing: {e}"
    elapsed = time.monotonic() - start
    output = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        return False, elapsed, f"exit {r.returncode}; tail: {output[-400:]}"
    if not SMOKE_OK_PATTERN.search(output):
        return False, elapsed, f"OK marker not found; tail: {output[-400:]}"
    # Extract the OK line for the report.
    ok_line = next((ln for ln in output.splitlines() if SMOKE_OK_PATTERN.search(ln)), output.splitlines()[-1] if output else "")
    return True, elapsed, ok_line.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", choices=list(TARGETS), help="Restrict to one target.")
    ap.add_argument("--path", type=Path, help="Lint only this specific file.")
    ap.add_argument("--quiet", action="store_true", help="No output on success.")
    ap.add_argument("--check-toolchain", action="store_true",
                    help="Run each target's behavioral smoke instead of linting.")
    ap.add_argument("--timeout", type=float, default=120.0,
                    help="Per-target smoke timeout in seconds (default 120).")
    args = ap.parse_args()

    if args.check_toolchain:
        targets = [args.target] if args.target else list(TOOLCHAIN_SMOKES)
        any_fail = False
        for t in targets:
            ok, elapsed, report = check_toolchain(t, timeout=args.timeout)
            status = "PASS" if ok else "FAIL"
            print(f"[{status}] {t:7s} {elapsed:6.1f}s  {report}")
            if not ok:
                any_fail = True
        return 1 if any_fail else 0

    only_path = args.path.resolve() if args.path else None
    targets = [args.target] if args.target else list(TARGETS)

    total_files = 0
    total_violations = 0
    all_violations: list[tuple[Path, int, str, str]] = []

    for t in targets:
        files = walk_target(t, only_path)
        spec = TARGETS[t]
        for f in files:
            total_files += 1
            violations = lint_file(f, spec["rules"], runner=is_runner(f))
            for lineno, rule, snippet in violations:
                total_violations += 1
                all_violations.append((f, lineno, rule, snippet))

    if all_violations:
        for f, lineno, rule, snippet in all_violations:
            rel = f.relative_to(REPO_ROOT) if f.is_relative_to(REPO_ROOT) else f
            print(f"{rel}:{lineno}: {rule}: {snippet}")
        print(f"\nleaplint: {total_violations} violation(s) across {total_files} emitted file(s).",
              file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"leaplint: clean. {total_files} emitted file(s) scanned.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
