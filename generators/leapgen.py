#!/usr/bin/env python3
"""leapgen — assemble a LEAP build brief for `part × target`.

Walks the inheritance + imports graph rooted at a leaf's `master.md`
and `shapes.json`, and prints a universal build brief to stdout. The
brief is identical in shape regardless of target or leaf; only the
path list and target-specific forbiddens differ. Feed the output
into a subagent spawn (Anthropic API, Claude Code Agent tool, etc.).

Usage:
    ./leapgen.py --part vdbe/opcodes-rows --target rust
    ./leapgen.py --part storage/btree     --target c

Exits nonzero if the part or target is missing from the repo.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

UNIVERSAL_INHERITS = [
    "spec/part-conventions.spec.md",
    "spec/type-system.spec.md",
    "spec/memory-discipline.spec.md",
    "schema/shape.schema.json",
]

TARGETS = {
    "rust":   {"label": "Rust",   "ext": "rs",  "forbid": "no inline tests, no stubs, no test-only constructors"},
    "c":      {"label": "C",      "ext": "c",   "forbid": "no `main()`, no `#ifdef TEST`, no stubs"},
    "zig":    {"label": "Zig",    "ext": "zig", "forbid": "no `test \"...\" { }` blocks, no stubs"},
    "go":     {"label": "Go",     "ext": "go",  "forbid": "no `func Test*`, no `_test.go`, no stubs"},
    "python": {"label": "Python", "ext": "py",  "forbid": "no `import unittest`, no `class ...Test*`, no `__main__`, no `_Stub*` classes"},
}


def resolve_part_dir(part_name: str) -> Path:
    """vdbe/opcodes-rows -> parts/vdbe/parts/opcodes-rows"""
    segments = part_name.split("/")
    d = REPO_ROOT / "parts"
    for i, seg in enumerate(segments):
        d = d / seg
        if i < len(segments) - 1:
            d = d / "parts"
    return d


def _frontmatter_body(md_path: Path) -> str:
    text = md_path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    return m.group(1) if m else ""


def frontmatter_inherits(md_path: Path) -> list[str]:
    """Parse front-matter `inherits:` list (non-universal only)."""
    body = _frontmatter_body(md_path)
    match = re.search(r"^inherits:\s*\n((?:\s+-\s+\S.*\n)+)", body, re.MULTILINE)
    if not match:
        return []
    return [line.strip().lstrip("-").strip() for line in match.group(1).splitlines() if line.strip()]


def frontmatter_kind(md_path: Path) -> str:
    """Returns 'leaf' (default) or 'inner'."""
    body = _frontmatter_body(md_path)
    m = re.search(r"^kind:\s*(\S+)", body, re.MULTILINE)
    return m.group(1) if m else "leaf"


def frontmatter_emits(md_path: Path, target: str) -> list[Path]:
    """For inner parts: parse the front-matter `emits:` block.
    Format (YAML subset):
        emits:
          rust: { path: src-rust/vdbe/mod.rs }
          c:    { path: src-c/vdbe/mod.c, headers: [src-c/vdbe/mod.h] }
    Returns absolute paths (path + any headers) for the named target, or []."""
    body = _frontmatter_body(md_path)
    m = re.search(rf"^\s+{re.escape(target)}:\s*\{{(.+?)\}}", body, re.MULTILINE)
    if not m:
        return []
    block = m.group(1)
    out: list[Path] = []
    pm = re.search(r"path:\s*([^\s,}]+)", block)
    if pm:
        out.append(REPO_ROOT / pm.group(1))
    hm = re.search(r"headers:\s*\[([^\]]+)\]", block)
    if hm:
        for h in hm.group(1).split(","):
            h = h.strip()
            if h:
                out.append(REPO_ROOT / h)
    return out


def walk_imports(shapes_path: Path, seen: set[Path]) -> list[Path]:
    """Transitive closure of shapes.json.imports -> list of imported shapes.json paths."""
    shapes_path = shapes_path.resolve()
    if shapes_path in seen:
        return []
    seen.add(shapes_path)
    try:
        shapes = json.loads(shapes_path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    out = []
    for _name, owner in shapes.get("imports", {}).items():
        imp = (REPO_ROOT / owner.lstrip("/") / "shapes.json").resolve()
        if imp.exists() and imp not in seen:
            out.extend(walk_imports(imp, seen))
            out.append(imp)
    return out


def derive_output_paths(part_name: str, target: str) -> list[Path]:
    """Name -> path. Hyphens become underscores. C is .h+.c pair. Go is package-dir. Python lives under src-python/leap_sqlite/."""
    under = part_name.replace("-", "_")
    if target == "c":
        return [REPO_ROOT / f"src-c/{under}.h", REPO_ROOT / f"src-c/{under}.c"]
    if target == "go":
        parent = "/".join(under.split("/")[:-1])
        leaf = under.split("/")[-1]
        return [REPO_ROOT / f"src-go/{parent}/{leaf}/{leaf}.go"]
    if target == "python":
        return [REPO_ROOT / f"src-python/leap_sqlite/{under}.py"]
    ext = TARGETS[target]["ext"]
    return [REPO_ROOT / f"src-{target}/{under}.{ext}"]


def find_siblings(part_dir: Path, target: str) -> list[Path]:
    """Already-emitted leaves under the same parent — for style reference."""
    if not part_dir.parent.exists():
        return []
    siblings: list[Path] = []
    for other in part_dir.parent.iterdir():
        if not other.is_dir() or other == part_dir or other.name == "parts":
            continue
        other_name = "/".join(other.relative_to(REPO_ROOT / "parts").parts)
        other_name = other_name.replace("/parts/", "/")
        for p in derive_output_paths(other_name, target):
            if p.exists() and p.stat().st_size > 0:
                siblings.append(p)
                break
    return siblings


def assemble_brief(part: str, target: str) -> str:
    part_dir = resolve_part_dir(part)
    master = part_dir / "master.md"
    shapes = part_dir / "shapes.json"
    if not master.exists() or not shapes.exists():
        sys.exit(f"ERROR: part `{part}` not found at {part_dir} "
                 f"(need both master.md and shapes.json)")
    if target not in TARGETS:
        sys.exit(f"ERROR: unknown target `{target}`; known: {list(TARGETS)}")

    kind = frontmatter_kind(master)
    if kind == "inner":
        outputs = frontmatter_emits(master, target)
        if not outputs:
            sys.exit(f"ERROR: inner part `{part}` has no `emits.{target}` "
                     f"entry in master.md front-matter")
        siblings: list[Path] = []
    else:
        outputs = derive_output_paths(part, target)
        siblings = find_siblings(part_dir, target)
    imports = walk_imports(shapes, set())
    extra_inherits = frontmatter_inherits(master)
    tgt = TARGETS[target]

    lines: list[str] = []
    w = lines.append

    w(f"You are a {tgt['label']} code generator for sqlite-leap v2.")
    w("")
    w("## Task")
    w(f"Emit the {tgt['label']} target code for LEAP part `{part}` by writing:")
    for p in outputs:
        w(f"- {p}")
    w("")
    w("## Inputs (read ALL in order, then walk the graph)")
    w("Universal specs:")
    for p in UNIVERSAL_INHERITS:
        w(f"- {REPO_ROOT / p}")
    w("")
    w("Target mapping (authoritative for emission rules):")
    w(f"- {REPO_ROOT / 'parts' / 'targets' / target / 'mapping.md'}")
    w("")
    w("The leaf:")
    w(f"- {master}")
    w(f"- {shapes}")
    if imports:
        w("")
        w("Transitive shape imports:")
        for p in imports:
            w(f"- {p}")
    if extra_inherits:
        w("")
        w("Explicit front-matter inherits:")
        for p in extra_inherits:
            w(f"- {REPO_ROOT / p.lstrip('/')}")
    w("")
    if siblings:
        w("## Style reference (optional)")
        for s in siblings:
            w(f"- {s}")
        w("")
    w("## Universal rules")
    w("- Do NOT read: other target emissions, mainline SQLite source, Turso/Limbo source, any `_original/` directory.")
    w("- Do NOT invent helpers, types, methods, or extern function names not declared in shapes.json + transitive imports. If ambiguous, STOP and report the gap.")
    w(f"- `spec/part-conventions.spec.md` §\"Generation scope\" applies universally: {tgt['forbid']}, no helpers beyond what's strictly needed to render declared shapes.")
    w("- master.md §\"Correctness pins\" are your hard constraints — satisfy every one.")
    w("- master.md §\"Regeneration envelope\" sets your line-count budget.")
    w("")
    w("## Deliverable")
    w("Write the file(s). Report under 200 words:")
    w("1. Line count" + (" (each file)." if len(outputs) > 1 else "."))
    w("2. For each numbered §\"Correctness pin\" in master.md, one line: \"Pin N: satisfied by <how>.\"")
    w("3. Any mapping gap or ambiguity — or \"none.\"")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--part", required=True, help='e.g. "vdbe/opcodes-rows"')
    ap.add_argument("--target", required=True, choices=list(TARGETS))
    args = ap.parse_args()
    print(assemble_brief(args.part, args.target), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
