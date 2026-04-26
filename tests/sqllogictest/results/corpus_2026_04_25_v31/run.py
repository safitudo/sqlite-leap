#!/usr/bin/env python3
"""Drive each of the 5 target slt_runners across the same sampled subset of
upstream sqllogictest corpus, in parallel. Emits a per-target summary."""
import os, sys, subprocess, time, re, json
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter

ROOT = "/Users/stanislav/code/sqlite-leap"
CORPUS = f"{ROOT}/tests/sqllogictest/upstream/test"
OUT = f"{ROOT}/tests/sqllogictest/results/corpus_2026_04_25_v31"
PER_FILE_TIMEOUT = 60

TARGETS = {
    "rust":   [f"{ROOT}/src-rust/target/release/examples/slt_runner"],
    "c":      [f"{ROOT}/src-c/build/slt_runner"],
    "go":     [f"{ROOT}/src-go/slt_runner"],
    "zig":    [f"{ROOT}/src-zig/zig-out/bin/slt_runner"],
    "python": ["python3", f"{ROOT}/tests/sqllogictest/5target_harness/driver_python.py"],
    "sqlite": ["python3", f"{ROOT}/tests/sqllogictest/5target_harness/driver_sqlite.py"],
}

def build_filelist():
    files = []
    for i in range(1, 6):
        files.append(f"select{i}.test")
    ev = sorted(os.listdir(f"{CORPUS}/evidence"))
    files.extend(f"evidence/{f}" for f in ev if f.endswith(".test"))
    idx_buckets = [
        "index/between/1", "index/commute/10", "index/delete/10",
        "index/in/10", "index/orderby/10", "index/orderby_nosort/10",
        "index/random/10", "index/view/10",
    ]
    for b in idx_buckets:
        for f in sorted(os.listdir(f"{CORPUS}/{b}")):
            if f.endswith(".test"):
                files.append(f"{b}/{f}")
    for d in ["random/aggregates", "random/expr", "random/groupby", "random/select"]:
        all_f = sorted([f for f in os.listdir(f"{CORPUS}/{d}") if f.endswith(".test")])
        n = max(1, len(all_f) // 8)
        for f in all_f[::n][:8]:
            files.append(f"{d}/{f}")
    return files

def run_one(args):
    target, rel = args
    cmd = TARGETS[target] + [f"{CORPUS}/{rel}"]
    t0 = time.time()
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=PER_FILE_TIMEOUT)
        return (target, rel, cp.returncode, cp.stdout, cp.stderr, int((time.time()-t0)*1000), False)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b'').decode('utf-8', 'replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
        return (target, rel, -1, out, "TIMEOUT", int((time.time()-t0)*1000), True)
    except Exception as e:
        return (target, rel, -2, "", f"ERR: {e}", int((time.time()-t0)*1000), False)

def normalize_reason(detail):
    if not detail: return "(no detail)"
    d = detail.strip()
    d = re.sub(r"\b\d+:\d+\b", "<pos>", d)
    d = re.sub(r"'[^']*'", "'<s>'", d)
    d = re.sub(r'"[^"]*"', '"<s>"', d)
    d = re.sub(r"\b\d+\b", "<n>", d)
    if len(d) > 120: d = d[:120] + "..."
    return d

def main():
    files = build_filelist()
    print(f"Total sampled files: {len(files)}; targets: {list(TARGETS)}", file=sys.stderr)
    work = [(t, f) for t in TARGETS for f in files]
    print(f"Total runs: {len(work)}", file=sys.stderr)

    per_target = {t: {"pass":0, "fail":0, "defer":0, "skip":0,
                       "fail_reasons": Counter(), "defer_reasons": Counter(),
                       "files": [], "timeouts": [], "crashes": []}
                  for t in TARGETS}

    with ProcessPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(run_one, w): w for w in work}
        done = 0
        for fut in as_completed(futs):
            target, rel, rc, stdout, stderr, ms, was_timeout = fut.result()
            done += 1
            n_pass = n_fail = n_defer = n_skip = 0
            status = "OK"
            if was_timeout: status = "TIMEOUT"; per_target[target]["timeouts"].append(rel)
            elif rc < 0 or rc > 128: status = "PANIC"; per_target[target]["crashes"].append((rel, str(stderr)[:200]))
            for ln in stdout.splitlines():
                if ln.startswith("SUMMARY"): continue
                parts = ln.split(" ", 3)
                if len(parts) < 3: continue
                verdict = parts[0]
                detail = parts[3] if len(parts) == 4 else ""
                if verdict == "PASS": n_pass += 1
                elif verdict == "FAIL":
                    n_fail += 1
                    per_target[target]["fail_reasons"][normalize_reason(detail)] += 1
                elif verdict == "DEFER":
                    n_defer += 1
                    per_target[target]["defer_reasons"][normalize_reason(detail)] += 1
                elif verdict == "SKIP": n_skip += 1
            per_target[target]["pass"] += n_pass
            per_target[target]["fail"] += n_fail
            per_target[target]["defer"] += n_defer
            per_target[target]["skip"] += n_skip
            per_target[target]["files"].append((rel, n_pass, n_fail, n_defer, n_skip, status, ms))
            if done % 100 == 0:
                print(f"  progress: {done}/{len(work)}", file=sys.stderr)

    summary_lines = ["# v10 corpus run 2026-04-25 (5 leap targets + mainline sqlite baseline)\n",
                     f"Files sampled per target: {len(files)}",
                     f"Per-file timeout: {PER_FILE_TIMEOUT}s\n",
                     "## Per-target aggregate (record-level)\n",
                     "| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP | excl-SKIP |",
                     "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    json_out = {}
    for t in TARGETS:
        s = per_target[t]
        tot = s["pass"]+s["fail"]+s["defer"]+s["skip"]
        non_skip = tot - s["skip"]
        rate = 100.0*s["pass"]/tot if tot else 0.0
        excl = 100.0*s["pass"]/non_skip if non_skip else 0.0
        summary_lines.append(f"| {t} | {s['pass']} | {s['fail']} | {s['defer']} | {s['skip']} | {tot} | {rate:.2f}% | {excl:.2f}% |")
        json_out[t] = {"pass":s["pass"], "fail":s["fail"], "defer":s["defer"], "skip":s["skip"], "total":tot, "incl_skip":rate, "excl_skip":excl,
                        "timeouts": s["timeouts"], "crashes": [c[0] for c in s["crashes"]]}

    summary_lines.append("\n## Top 10 DEFER reasons per target\n")
    for t in TARGETS:
        summary_lines.append(f"### {t}")
        for reason, n in per_target[t]["defer_reasons"].most_common(10):
            summary_lines.append(f"- {n}\t{reason}")
        summary_lines.append("")

    summary_lines.append("\n## Top 10 FAIL reasons per target\n")
    for t in TARGETS:
        summary_lines.append(f"### {t}")
        for reason, n in per_target[t]["fail_reasons"].most_common(10):
            summary_lines.append(f"- {n}\t{reason}")
        summary_lines.append("")

    with open(f"{OUT}/summary.md", "w") as f:
        f.write("\n".join(summary_lines))
    with open(f"{OUT}/summary.json", "w") as f:
        json.dump(json_out, f, indent=2)
    print("\n".join(summary_lines[:15]))

if __name__ == "__main__":
    main()
