#!/usr/bin/env python3
"""Drive slt_runner across a sampled subset of upstream sqllogictest corpus,
capturing per-record PASS/FAIL/DEFER lines and aggregating reasons."""
import os, sys, subprocess, time, re, json
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter, defaultdict

ROOT = "/Users/stanislav/code/sqlite-leap"
CORPUS = f"{ROOT}/tests/sqllogictest/upstream/test"
BIN = f"{ROOT}/src-rust/target/release/examples/slt_runner"
OUT = f"{ROOT}/tests/sqllogictest/results/corpus_2026_04_25_post_from_alias"
PER_FILE_TIMEOUT = 60  # seconds; if hit -> TIMEOUT

def build_filelist():
    files = []
    # All selectN.test
    for i in range(1, 6):
        files.append(f"select{i}.test")
    # All evidence
    ev = sorted(os.listdir(f"{CORPUS}/evidence"))
    files.extend(f"evidence/{f}" for f in ev if f.endswith(".test"))
    # Index small buckets
    idx_buckets = [
        "index/between/1",
        "index/commute/10",
        "index/delete/10",
        "index/in/10",
        "index/orderby/10",
        "index/orderby_nosort/10",
        "index/random/10",
        "index/view/10",
    ]
    for b in idx_buckets:
        for f in sorted(os.listdir(f"{CORPUS}/{b}")):
            if f.endswith(".test"):
                files.append(f"{b}/{f}")
    # Random sample: 8 per subdir
    for d in ["random/aggregates", "random/expr", "random/groupby", "random/select"]:
        all_f = sorted([f for f in os.listdir(f"{CORPUS}/{d}") if f.endswith(".test")])
        # take every Nth to span the bucket
        n = max(1, len(all_f) // 8)
        for f in all_f[::n][:8]:
            files.append(f"{d}/{f}")
    return files

def run_one(rel):
    t0 = time.time()
    try:
        cp = subprocess.run(
            [BIN, f"{CORPUS}/{rel}"],
            capture_output=True, text=True,
            timeout=PER_FILE_TIMEOUT,
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        return (rel, cp.returncode, cp.stdout, cp.stderr, elapsed_ms, False)
    except subprocess.TimeoutExpired as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        out = (e.stdout or b'').decode('utf-8', 'replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
        return (rel, -1, out, "TIMEOUT", elapsed_ms, True)
    except Exception as e:
        return (rel, -2, "", f"ERR: {e}", int((time.time()-t0)*1000), False)

def normalize_reason(detail):
    """Bucket a free-text reason string into a coarse category."""
    if not detail:
        return "(no detail)"
    d = detail.strip()
    # Strip line numbers / position info: "1:13" "at 5:7"
    d = re.sub(r"\b\d+:\d+\b", "<pos>", d)
    # Strip quoted identifiers / string literals
    d = re.sub(r"'[^']*'", "'<s>'", d)
    d = re.sub(r'"[^"]*"', '"<s>"', d)
    # Strip bare numbers
    d = re.sub(r"\b\d+\b", "<n>", d)
    # Truncate
    if len(d) > 120:
        d = d[:120] + "..."
    return d

def main():
    files = build_filelist()
    print(f"Total sampled files: {len(files)}", file=sys.stderr)
    total_pass = total_fail = total_defer = 0
    file_records = []  # (rel, n_pass, n_fail, n_defer, status, elapsed_ms)
    defer_reasons = Counter()
    fail_reasons = Counter()
    crashed = []
    timed_out = []
    raw_log_path = f"{OUT}/raw_records.log"
    raw_log = open(raw_log_path, "w")

    # parallel
    with ProcessPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(run_one, f): f for f in files}
        done = 0
        for fut in as_completed(futures):
            rel, rc, stdout, stderr, ms, was_timeout = fut.result()
            done += 1
            n_pass = n_fail = n_defer = 0
            file_status = "OK"
            if was_timeout:
                file_status = "TIMEOUT"
                timed_out.append(rel)
            elif rc < 0 or rc > 128:
                file_status = "PANIC"
                crashed.append((rel, stderr[:200]))
            raw_log.write(f"### FILE {rel} status={file_status} rc={rc} ms={ms}\n")
            for ln in stdout.splitlines():
                raw_log.write(ln + "\n")
                if ln.startswith("SUMMARY"):
                    continue
                # parse: "<verdict> <line> <kind> <detail?>"
                parts = ln.split(" ", 3)
                if len(parts) < 3:
                    continue
                verdict = parts[0]
                detail = parts[3] if len(parts) == 4 else ""
                if verdict == "PASS":
                    n_pass += 1
                elif verdict == "FAIL":
                    n_fail += 1
                    fail_reasons[normalize_reason(detail)] += 1
                elif verdict == "DEFER":
                    n_defer += 1
                    defer_reasons[normalize_reason(detail)] += 1
            total_pass += n_pass
            total_fail += n_fail
            total_defer += n_defer
            file_records.append((rel, n_pass, n_fail, n_defer, file_status, ms))
            if done % 20 == 0:
                print(f"  progress: {done}/{len(files)}", file=sys.stderr)
    raw_log.close()

    grand_total = total_pass + total_fail + total_defer
    pass_pct = 100.0 * total_pass / grand_total if grand_total else 0.0

    # File-level pass-rate distribution
    buckets = {">95%": 0, "50-95%": 0, "<50%": 0, "no-records": 0}
    per_file_rates = []
    for rel, p, f, d, st, ms in file_records:
        tot = p + f + d
        if tot == 0:
            buckets["no-records"] += 1
            per_file_rates.append((rel, None, p, f, d, st))
            continue
        rate = 100.0 * p / tot
        per_file_rates.append((rel, rate, p, f, d, st))
        if rate > 95:
            buckets[">95%"] += 1
        elif rate > 50:
            buckets["50-95%"] += 1
        else:
            buckets["<50%"] += 1

    # Write summary
    summary_path = f"{OUT}/summary.md"
    with open(summary_path, "w") as f:
        f.write("# Corpus run 2026-04-25 post-unary+qualifier (Rust)\n\n")
        f.write(f"Files sampled: {len(files)}\n")
        f.write(f"Binary: {BIN}\n")
        f.write(f"Per-file timeout: {PER_FILE_TIMEOUT}s\n\n")
        f.write("## Aggregate (record-level)\n\n")
        f.write(f"- PASS:  {total_pass}\n- FAIL:  {total_fail}\n- DEFER: {total_defer}\n")
        f.write(f"- TOTAL: {grand_total}\n")
        f.write(f"- PASS rate: {pass_pct:.2f}%\n\n")
        f.write("## File-level pass-rate distribution\n\n")
        for k, v in buckets.items():
            f.write(f"- {k}: {v}\n")
        f.write("\n## Top 20 DEFER reasons\n\n")
        for reason, cnt in defer_reasons.most_common(20):
            f.write(f"- {cnt}\t{reason}\n")
        f.write("\n## Top 20 FAIL reasons\n\n")
        for reason, cnt in fail_reasons.most_common(20):
            f.write(f"- {cnt}\t{reason}\n")
        f.write("\n## Timeouts\n\n")
        for rel in timed_out:
            f.write(f"- {rel}\n")
        f.write("\n## Crashes / panics\n\n")
        for rel, err in crashed:
            f.write(f"- {rel}: {err}\n")
        f.write("\n## Per-file detail (rel, pass%, pass, fail, defer, status)\n\n")
        per_file_rates.sort(key=lambda x: (x[1] if x[1] is not None else -1))
        for rel, rate, p, fc, d, st in per_file_rates:
            r = f"{rate:.1f}%" if rate is not None else "n/a"
            f.write(f"- {rel}\t{r}\t{p}\t{fc}\t{d}\t{st}\n")

    # Also write JSON
    with open(f"{OUT}/summary.json", "w") as f:
        json.dump({
            "files_sampled": len(files),
            "total_pass": total_pass, "total_fail": total_fail, "total_defer": total_defer,
            "total_records": grand_total, "pass_pct": pass_pct,
            "file_buckets": buckets,
            "top_defer": defer_reasons.most_common(50),
            "top_fail": fail_reasons.most_common(50),
            "timeouts": timed_out,
            "crashes": [r for r,_ in crashed],
        }, f, indent=2)
    print(f"Wrote {summary_path}", file=sys.stderr)
    print(f"PASS={total_pass} FAIL={total_fail} DEFER={total_defer} TOTAL={grand_total} ({pass_pct:.2f}%)")

if __name__ == "__main__":
    main()
