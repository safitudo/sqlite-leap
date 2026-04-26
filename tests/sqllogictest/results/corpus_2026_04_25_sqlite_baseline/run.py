#!/usr/bin/env python3
"""Mainline-sqlite baseline: drive driver_sqlite.py over the same corpus
filelist used by corpus_2026_04_25_5target_v8/v9 to establish the
incl-SKIP / excl-SKIP ceiling for honest comparison."""
import os, sys, subprocess, time, re, json
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter

ROOT = "/Users/stanislav/code/sqlite-leap"
CORPUS = f"{ROOT}/tests/sqllogictest/upstream/test"
OUT = f"{ROOT}/tests/sqllogictest/results/corpus_2026_04_25_sqlite_baseline"
PER_FILE_TIMEOUT = 60

DRIVER = ["python3", f"{ROOT}/tests/sqllogictest/5target_harness/driver_sqlite.py"]


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


def run_one(rel):
    cmd = DRIVER + [f"{CORPUS}/{rel}"]
    t0 = time.time()
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=PER_FILE_TIMEOUT)
        return (rel, cp.returncode, cp.stdout, cp.stderr, int((time.time()-t0)*1000), False)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b'').decode('utf-8', 'replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
        return (rel, -1, out, "TIMEOUT", int((time.time()-t0)*1000), True)
    except Exception as e:
        return (rel, -2, "", f"ERR: {e}", int((time.time()-t0)*1000), False)


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
    print(f"Total sampled files: {len(files)}", file=sys.stderr)
    n_pass = n_fail = n_defer = n_skip = 0
    fail_reasons = Counter()
    timeouts = []
    crashes = []
    per_file = []

    with ProcessPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(run_one, f): f for f in files}
        done = 0
        for fut in as_completed(futs):
            rel, rc, stdout, stderr, ms, was_timeout = fut.result()
            done += 1
            fp = ff = fd = fs = 0
            status = "OK"
            if was_timeout: status = "TIMEOUT"; timeouts.append(rel)
            elif rc < 0 or rc > 128: status = "PANIC"; crashes.append((rel, str(stderr)[:200]))
            for ln in stdout.splitlines():
                if ln.startswith("SUMMARY"): continue
                parts = ln.split(" ", 3)
                if len(parts) < 3: continue
                v = parts[0]
                detail = parts[3] if len(parts) == 4 else ""
                if v == "PASS": fp += 1
                elif v == "FAIL":
                    ff += 1
                    fail_reasons[normalize_reason(detail)] += 1
                elif v == "DEFER": fd += 1
                elif v == "SKIP": fs += 1
            n_pass += fp; n_fail += ff; n_defer += fd; n_skip += fs
            per_file.append((rel, fp, ff, fd, fs, status, ms))
            if done % 50 == 0:
                print(f"  progress: {done}/{len(files)}", file=sys.stderr)

    total = n_pass + n_fail + n_defer + n_skip
    incl_skip = 100.0 * n_pass / total if total else 0.0
    excl_skip = 100.0 * n_pass / (total - n_skip) if (total - n_skip) else 0.0

    md = ["# Mainline-sqlite corpus baseline\n",
          f"Driver: /usr/bin/sqlite3 via Python sqlite3 module (system version)",
          f"Files sampled: {len(files)}",
          f"Per-file timeout: {PER_FILE_TIMEOUT}s\n",
          "## Aggregate (record-level)\n",
          "| target | PASS | FAIL | DEFER | SKIP | TOTAL | incl-SKIP rate | excl-SKIP rate |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |",
          f"| sqlite (mainline) | {n_pass} | {n_fail} | {n_defer} | {n_skip} | {total} | {incl_skip:.2f}% | {excl_skip:.2f}% |",
          "",
          f"Timeouts: {len(timeouts)}",
          f"Crashes: {len(crashes)}",
          ""]
    if fail_reasons:
        md.append("## Top FAIL reasons\n")
        for reason, n in fail_reasons.most_common(20):
            md.append(f"- {n}\t{reason}")
    js = {"target":"sqlite_mainline","pass":n_pass,"fail":n_fail,"defer":n_defer,
          "skip":n_skip,"total":total,"incl_skip_rate":incl_skip,"excl_skip_rate":excl_skip,
          "timeouts":timeouts,"crashes":[c[0] for c in crashes]}
    with open(f"{OUT}/summary.md","w") as f: f.write("\n".join(md))
    with open(f"{OUT}/summary.json","w") as f: json.dump(js, f, indent=2)
    print("\n".join(md[:12]))


if __name__ == "__main__":
    main()
