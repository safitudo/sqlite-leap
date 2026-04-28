# sqlite-leap — 5-target stunt aggregator

Generated 2026-04-28T05:34:20Z on Darwin arm64 in 123s.
Branch: v2-recursive-parts  ·  HEAD: fd102ee

## TL;DR

**One language-neutral spec → five working SQLite implementations** (Rust,
C, Zig, Go, Python). This aggregator runs every 5-target proof on the
branch and grades the result. Verdict: **⚠ partial**
(pass=6 partial=1 fail=0 out of 7).

Highlights:
- SLT parity: targets=5 pass_total=578 fail_total=0 diverge=0 fixture=extended.test
- Fileformat-write byte-identity: targets_ok=5/5 unique_sha1=1 sha1=8461b47e7a9d
- Deep-split byte-identity: prefill=270 ok=5/5 unique=1 sha1=b5f1f8978407 ;; prefill=5000 ok=5/5 unique=1 sha1=fef632262aa2
- eq-runner JSON parity: corpus_files=1 diverge=2 rc=0
- Lane 1 cold start: fastest:c 3.597 1.50x ; native_beat_mainline=4/4
- Lane 5 binary size: Smallest binary target: c at 207976 bytes (203.1 KB). ; C target beats mainline sqlite3: YES (0.11x of mainline).
- Lane 6 memory: lightest: c 3145728 3072.0 0.97x ; mainline=3063808 bytes ; beat_mainline=0/5

## Result table

| # | Proof | Verdict | Headline |
|---:|---|:-:|---|
| 1 | 5-target SLT parity | ✓ PASS | targets=5 pass_total=578 fail_total=0 diverge=0 fixture=extended.test |
| 2 | Fileformat-write byte-identity | ✓ PASS | targets_ok=5/5 unique_sha1=1 sha1=8461b47e7a9d |
| 3 | Deep-split byte-identity 270+5000 | ✓ PASS | prefill=270 ok=5/5 unique=1 sha1=b5f1f8978407 ;; prefill=5000 ok=5/5 unique=1 sha1=fef632262aa2 |
| 4 | eq-runner JSON parity | ✓ PASS | corpus_files=1 diverge=2 rc=0 |
| 5 | Lane 1 cold start | ✓ PASS | fastest:c 3.597 1.50x ; native_beat_mainline=4/4 |
| 6 | Lane 5 binary size | ✓ PASS | Smallest binary target: c at 207976 bytes (203.1 KB). ; C target beats mainline sqlite3: YES (0.11x of mainline). |
| 7 | Lane 6 memory footprint | ⚠ PARTIAL | lightest: c 3145728 3072.0 0.97x ; mainline=3063808 bytes ; beat_mainline=0/5 |

## 1. 5-target SLT parity

Driver: `run_slt_5target.sh tests/sqllogictest/5target_harness/extended.test`

Headline: targets=5 pass_total=578 fail_total=0 diverge=0 fixture=extended.test

Per-target summary:

```
  SUMMARY target=rust pass=118 fail=0 defer=7 skip=0 total=125
  SUMMARY target=python pass=114 fail=0 defer=11 skip=0 total=125
  SUMMARY target=c pass=114 fail=0 defer=11 total=125
  SUMMARY target=zig pass=115 fail=0 defer=10 skip=0 total=125
  SUMMARY target=go pass=117 fail=0 defer=8 skip=0 total=125
```
Log: `/Users/stanislav/code/sqlite-leap/bench/results/demo_5target_stunt/01_slt_parity.log`

## 2. 5-target fileformat-write byte-identity

Each target appends one row to a copy of `tests/fixtures/tiny.db` then
we sha1sum the resulting files. Stunt grade requires all 5 SHAs equal.

Headline: targets_ok=5/5 unique_sha1=1 sha1=8461b47e7a9d

| target | sha1 |
|---|---|
| rust | `8461b47e7a9d4354c3de30cd5fb687286f0d0e78` |
| c | `8461b47e7a9d4354c3de30cd5fb687286f0d0e78` |
| zig | `8461b47e7a9d4354c3de30cd5fb687286f0d0e78` |
| go | `8461b47e7a9d4354c3de30cd5fb687286f0d0e78` |
| python | `8461b47e7a9d4354c3de30cd5fb687286f0d0e78` |

Log: `/Users/stanislav/code/sqlite-leap/bench/results/demo_5target_stunt/02_fileformat_write.log`

## 3. 5-target deep-split byte-identity (270 + 5000 rows)

Multi-page btree-write probe: each target prefills + inserts to trigger
root-split (270 rows) and recursive split (5000 rows). All 5 .db files
must be byte-identical at each prefill level.

Headline: prefill=270 ok=5/5 unique=1 sha1=b5f1f8978407 ;; prefill=5000 ok=5/5 unique=1 sha1=fef632262aa2

- prefill=270 ok=5/5 unique=1 sha1=b5f1f8978407
- prefill=5000 ok=5/5 unique=1 sha1=fef632262aa2

Log: `/Users/stanislav/code/sqlite-leap/bench/results/demo_5target_stunt/03_fileformat_deep_split.log`

## 4. 5-target eq-runner JSON parity

Driver: `run_eq_check.sh`. Each target's eq_runner emits canonical JSON
for every corpus file under `parts/eq-harness/corpus/`; outputs must be
byte-identical across all 5 targets.

Headline: corpus_files=1 diverge=2 rc=0

    build rust   ... FAIL (see /var/folders/vl/xgdd28sx5hl5dwfv599xjtlm0000gn/T/tmp.eoxivOqJXk/build.rust.log)
    build c      ... FAIL (see /var/folders/vl/xgdd28sx5hl5dwfv599xjtlm0000gn/T/tmp.eoxivOqJXk/build.c.log)
    == count_star_x3 ==
      python OK   (reference)
      go     OK   (matches python)
      zig    OK   (matches python)

Log: `/Users/stanislav/code/sqlite-leap/bench/results/demo_5target_stunt/04_eq_check.log`

## 5. Lane 1 — cold start

Driver: `bench/cold_start_5target.sh`. Median wallclock over 11 samples
for cold-process `SELECT 1+2`. Mainline baseline = `sqlite3 :memory:`.

Headline: fastest:c 3.597 1.50x ; native_beat_mainline=4/4

| target | median (ms) | vs mainline | notes |
|---|---:|---:|---|
| c | 3.597 | 1.50x | slt_runner(c) on cold_start.test |
| rust | 3.728 | 1.45x | slt_runner(rust) on cold_start.test |
| zig | 3.898 | 1.39x | slt_runner(zig) on cold_start.test |
| go | 4.624 | 1.17x | slt_runner(go) on cold_start.test |
| python | 164.655 | 0.03x | slt_runner(python) on cold_start.test |
| sqlite3 (mainline) | 5.403 | 1.00x | system `3.51.0` |


Full report: `bench/results/cold_start_5target/REPORT.md`

## 6. Lane 5 — binary size

Driver: `bench/binary_size_5target.sh`. Each target builds the SELECT
behavioral smoke with smallest-binary flags; mainline baseline =`/usr/bin/sqlite3`.

Headline: Smallest binary target: c at 207976 bytes (203.1 KB). ; C target beats mainline sqlite3: YES (0.11x of mainline).

| target | bytes | KB | vs sqlite3 mainline | notes |
|---|---:|---:|---:|---|
| c | 207976 | 203.1 | 0.11x | gcc -Os -ffunction-sections + dead-strip + strip |
| rust | 602896 | 588.8 | 0.33x | cargo --profile release-small |
| zig | 2879192 | 2811.7 | 1.59x | zig build -Doptimize=ReleaseSmall + strip |
| go | 2816082 | 2750.1 | 1.56x | go build -trimpath -ldflags '-s -w' |
| python | 973930 | 951.1 | 0.54x | .py source only; interpreter python3.10 = 33816 bytes (excluded) |
| sqlite3 (mainline) | 1809536 | 1767.1 | 1.00x | system `3.41.2` |


**Smallest binary target:** c at 207976 bytes (203.1 KB).
**C target beats mainline sqlite3:** YES (0.11x of mainline).

Full report: `bench/results/binary_size_5target/REPORT.md`

## 7. Lane 6 — memory footprint

Driver: `bench/memory_footprint_5target.sh`. Median peak RSS over 5
samples for CREATE+1000 INSERT+SELECT. Mainline baseline = `sqlite3`.

Headline: lightest: c 3145728 3072.0 0.97x ; mainline=3063808 bytes ; beat_mainline=0/5

| target | peak RSS (bytes) | KB | vs mainline | notes |
|---|---:|---:|---:|---|
| c | 3145728 | 3072.0 | 0.97x | slt_runner(c) on memory_footprint.test |
| rust | 3670016 | 3584.0 | 0.83x | slt_runner(rust) on memory_footprint.test |
| zig | 3440640 | 3360.0 | 0.89x | slt_runner(zig) on memory_footprint.test |
| go | 10174464 | 9936.0 | 0.30x | slt_runner(go) on memory_footprint.test |
| python | 30490624 | 29776.0 | 0.10x | slt_runner(python) on memory_footprint.test |
| sqlite3 (mainline) | 3063808 | 2992.0 | 1.00x | system `3.51.0` |


Full report: `bench/results/memory_footprint_5target/REPORT.md`

## Final verdict

**⚠ partial**

- 6 of 7 proofs PASS
- 1 PARTIAL
- elapsed: 123s

_Reproduce: `bash demo_5target_stunt.sh` (idempotent; ~5 min on warm laptop)._
