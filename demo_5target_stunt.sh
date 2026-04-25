#!/usr/bin/env bash
# sqlite-leap — single-command publication-ready 5-target stunt aggregator.
#
# Runs every 5-target proof on this branch in sequence, captures pass/fail
# and headline numbers, writes one consolidated REPORT.md a critic can read
# in 60 seconds.
#
# Idempotent. Tolerant of any single proof failing (continues, marks ✗,
# reports at end). macOS-compatible. Total runtime budget: ~5 min on warm
# laptop.
#
# Usage:  bash demo_5target_stunt.sh
# Output: bench/results/demo_5target_stunt/REPORT.md
#         bench/results/demo_5target_stunt/<step>.log

set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

OUT_DIR="$ROOT/bench/results/demo_5target_stunt"
mkdir -p "$OUT_DIR"
REPORT="$OUT_DIR/REPORT.md"

GREEN="\033[0;32m"
RED="\033[0;31m"
YELLOW="\033[0;33m"
BOLD="\033[1m"
DIM="\033[2m"
NC="\033[0m"

# -------- shared state for final aggregation -------------------------------
# Parallel arrays (bash 3.2 — no associative arrays).
STEP_KEY=()
STEP_TITLE=()
STEP_VERDICT=()   # PASS|FAIL|PARTIAL
STEP_HEADLINE=()  # 1-line summary

record_step() {
    STEP_KEY+=("$1")
    STEP_TITLE+=("$2")
    STEP_VERDICT+=("$3")
    STEP_HEADLINE+=("$4")
}

verdict_color() {
    case "$1" in
        PASS) echo -e "${GREEN}✓ PASS${NC}" ;;
        FAIL) echo -e "${RED}✗ FAIL${NC}" ;;
        PARTIAL) echo -e "${YELLOW}⚠ PARTIAL${NC}" ;;
        *) echo "$1" ;;
    esac
}

verdict_glyph() {
    case "$1" in
        PASS) echo "✓" ;;
        FAIL) echo "✗" ;;
        PARTIAL) echo "⚠" ;;
        *) echo "?" ;;
    esac
}

banner() {
    echo
    echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}  $1${NC}"
    echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
}

step_banner() {
    echo
    echo -e "${BOLD}── [$1] $2 ──${NC}"
}

# -------- prelude ----------------------------------------------------------
banner "sqlite-leap 5-target stunt aggregator"
echo "Output dir: $OUT_DIR"
echo "Started:    $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
START_TS=$(date +%s)

# Make sure tiny.db fixture exists (small; cheap to verify).
if [[ ! -f tests/fixtures/tiny.db ]]; then
    echo "tests/fixtures/tiny.db missing — cannot run fileformat probes" >&2
fi

# ===========================================================================
# Step 1 — 5-target SLT parity (extended.test)
# ===========================================================================
step_banner 1 "5-target SLT parity (extended.test, 125 records × 5 targets)"
LOG="$OUT_DIR/01_slt_parity.log"
SLT_FIXTURE="tests/sqllogictest/5target_harness/extended.test"
if [[ ! -f "$SLT_FIXTURE" ]]; then SLT_FIXTURE="tests/sqllogictest/5target_harness/canonical.test"; fi

if bash run_slt_5target.sh "$SLT_FIXTURE" >"$LOG" 2>&1; then
    rc=0
else
    rc=$?
fi
# Extract headline: count summary lines + check for divergence.
SLT_TOTALS=$(grep -E '^  SUMMARY target=' "$LOG" || true)
SLT_DIVERGE=$(grep -c '^  DIVERGE' "$LOG" || true)
SLT_PASS_TOTAL=$(echo "$SLT_TOTALS" | awk -F'pass=' '{s+=$2+0} END{print s+0}')
SLT_FAIL_TOTAL=$(echo "$SLT_TOTALS" | awk -F'fail=' '{ split($2,a," "); s+=a[1]+0 } END{print s+0}')
SLT_TARGETS=$(echo "$SLT_TOTALS" | wc -l | tr -d ' ')
if [[ "$rc" == "0" && "$SLT_DIVERGE" == "0" ]]; then
    v=PASS
else
    v=FAIL
fi
HEAD="targets=$SLT_TARGETS pass_total=$SLT_PASS_TOTAL fail_total=$SLT_FAIL_TOTAL diverge=$SLT_DIVERGE fixture=$(basename "$SLT_FIXTURE")"
record_step "slt_parity" "5-target SLT parity" "$v" "$HEAD"
echo "  $(verdict_color "$v")  $HEAD"

# ===========================================================================
# Step 2 — 5-target fileformat-write byte-identity (single page)
# ===========================================================================
step_banner 2 "5-target fileformat-write byte-identity (1 row append)"
LOG="$OUT_DIR/02_fileformat_write.log"
: >"$LOG"

# Strategy: copy tiny.db once per target, run that target's writer, sha1sum,
# compare. We invoke each target's runner directly rather than the build
# scripts (which already cross-check against Rust) so we control the comparison.
WRITE_RC=0
declare -a WRITE_TARGETS=()
declare -a WRITE_SHAS=()

run_write_target() {
    local t="$1"; local probe="/tmp/leap_stunt_write_$t.db"
    cp tests/fixtures/tiny.db "$probe" 2>>"$LOG" || return 1
    case "$t" in
        rust)
            (cd src-rust && cargo build --release --quiet --example fileformat_write_runner) >>"$LOG" 2>&1 || return 1
            src-rust/target/release/examples/fileformat_write_runner "$probe" >>"$LOG" 2>&1 || return 1
            ;;
        c)
            if [[ ! -x src-c/build/fileformat_write_smoke ]]; then
                gcc -Wall -Wextra -std=c11 -Wno-unused-parameter \
                    -o src-c/build/fileformat_write_smoke \
                    src-c/examples/fileformat_write_smoke.c >>"$LOG" 2>&1 || return 1
            fi
            src-c/build/fileformat_write_smoke "$probe" >>"$LOG" 2>&1 || return 1
            ;;
        zig)
            if [[ ! -x src-zig/zig-out/bin/fileformat_write_smoke ]]; then
                bash src-zig/build_fileformat_write_smoke.sh >>"$LOG" 2>&1 || return 1
            fi
            src-zig/zig-out/bin/fileformat_write_smoke "$probe" >>"$LOG" 2>&1 || return 1
            ;;
        go)
            if [[ ! -x bin/go-fileformat-write-smoke ]]; then
                bash src-go/build_fileformat_write_smoke.sh >>"$LOG" 2>&1 || return 1
            fi
            bin/go-fileformat-write-smoke "$probe" >>"$LOG" 2>&1 || return 1
            ;;
        python)
            python3 src-python/fileformat_write_runner.py "$probe" >>"$LOG" 2>&1 || return 1
            ;;
    esac
    local sha=$(shasum -a 1 "$probe" | awk '{print $1}')
    WRITE_TARGETS+=("$t")
    WRITE_SHAS+=("$sha")
    echo "  $t -> $sha" | tee -a "$LOG"
}

for t in rust c zig go python; do
    if ! run_write_target "$t"; then
        echo "  $t -> FAIL (see $LOG)" | tee -a "$LOG"
        WRITE_RC=1
    fi
done

# Compare all SHAs.
WRITE_UNIQUE=$(printf "%s\n" "${WRITE_SHAS[@]}" | sort -u | wc -l | tr -d ' ')
WRITE_OK=${#WRITE_TARGETS[@]}
if [[ "$WRITE_OK" == "5" && "$WRITE_UNIQUE" == "1" ]]; then
    v=PASS
elif [[ "$WRITE_OK" -gt 0 && "$WRITE_UNIQUE" == "1" ]]; then
    v=PARTIAL
else
    v=FAIL
fi
WRITE_SHA_REF="${WRITE_SHAS[0]:-NA}"
HEAD="targets_ok=$WRITE_OK/5 unique_sha1=$WRITE_UNIQUE sha1=${WRITE_SHA_REF:0:12}"
record_step "fileformat_write" "Fileformat-write byte-identity" "$v" "$HEAD"
echo "  $(verdict_color "$v")  $HEAD"

# ===========================================================================
# Step 3 — 5-target deep-split byte-identity (270 + 5000 rows)
# ===========================================================================
step_banner 3 "5-target deep-split byte-identity (270 + 5000 rows)"
LOG="$OUT_DIR/03_fileformat_deep_split.log"
: >"$LOG"

run_deep_target() {
    local t="$1"; local prefill="$2"; local probe="/tmp/leap_stunt_deep_${t}_${prefill}.db"
    cp tests/fixtures/tiny.db "$probe" 2>>"$LOG" || return 1
    case "$t" in
        rust)
            (cd src-rust && cargo build --release --quiet --example fileformat_deep_split_runner) >>"$LOG" 2>&1 || return 1
            src-rust/target/release/examples/fileformat_deep_split_runner "$probe" --prefill "$prefill" >>"$LOG" 2>&1 || return 1
            ;;
        c)
            if [[ ! -x src-c/build/fileformat_deep_split_smoke ]]; then
                gcc -Wall -Wextra -std=c11 -Wno-unused-parameter -Wno-shift-negative-value -O2 \
                    -o src-c/build/fileformat_deep_split_smoke \
                    src-c/examples/fileformat_deep_split_smoke.c >>"$LOG" 2>&1 || return 1
            fi
            src-c/build/fileformat_deep_split_smoke "$probe" --prefill "$prefill" >>"$LOG" 2>&1 || return 1
            ;;
        zig)
            if [[ ! -x src-zig/zig-out/bin/fileformat_deep_split_smoke ]]; then
                (cd src-zig && zig build) >>"$LOG" 2>&1 || true
            fi
            src-zig/zig-out/bin/fileformat_deep_split_smoke "$probe" --prefill "$prefill" >>"$LOG" 2>&1 || return 1
            ;;
        go)
            if [[ ! -x bin/go-fileformat-deep-split-smoke ]]; then
                bash src-go/build_fileformat_deep_split_smoke.sh >>"$LOG" 2>&1 || return 1
            fi
            bin/go-fileformat-deep-split-smoke "$probe" --prefill "$prefill" >>"$LOG" 2>&1 || return 1
            ;;
        python)
            python3 src-python/fileformat_deep_split_smoke.py "$probe" --prefill "$prefill" >>"$LOG" 2>&1 || return 1
            ;;
    esac
    local sha=$(shasum -a 1 "$probe" | awk '{print $1}')
    echo "  prefill=$prefill $t -> $sha" >> "$LOG"
    printf "%s" "$sha"
}

DEEP_RC=0
DEEP_VERDICTS=()
for prefill in 270 5000; do
    declare -a SHAS=()
    declare -a OK_TARGETS=()
    for t in rust c zig go python; do
        sha=$(run_deep_target "$t" "$prefill" 2>/dev/null) || sha=""
        if [[ -n "$sha" && ${#sha} -eq 40 ]]; then
            SHAS+=("$sha")
            OK_TARGETS+=("$t")
            echo "  prefill=$prefill $t -> $sha"
        else
            echo "  prefill=$prefill $t -> FAIL"
            echo "  prefill=$prefill $t -> FAIL" >> "$LOG"
            DEEP_RC=1
        fi
    done
    UNIQUE=$(printf "%s\n" "${SHAS[@]}" | sort -u | wc -l | tr -d ' ')
    OK=${#OK_TARGETS[@]}
    REF="${SHAS[0]:-NA}"
    DEEP_VERDICTS+=("prefill=$prefill ok=$OK/5 unique=$UNIQUE sha1=${REF:0:12}")
    if [[ "$OK" != "5" || "$UNIQUE" != "1" ]]; then
        DEEP_RC=1
    fi
    unset SHAS OK_TARGETS
done

if [[ "$DEEP_RC" == "0" ]]; then v=PASS
elif printf "%s\n" "${DEEP_VERDICTS[@]}" | grep -q 'unique=1'; then v=PARTIAL
else v=FAIL
fi
HEAD="${DEEP_VERDICTS[0]} ;; ${DEEP_VERDICTS[1]:-skipped}"
record_step "fileformat_deep_split" "Deep-split byte-identity 270+5000" "$v" "$HEAD"
echo "  $(verdict_color "$v")  $HEAD"

# ===========================================================================
# Step 4 — 5-target eq-runner JSON parity
# ===========================================================================
step_banner 4 "5-target eq-runner JSON parity"
LOG="$OUT_DIR/04_eq_check.log"
if bash run_eq_check.sh >"$LOG" 2>&1; then
    rc=0
else
    rc=$?
fi
EQ_AGREE=$(grep -E '^RESULT: all targets agree' "$LOG" | head -1)
EQ_DIVERGE=$(grep -c 'DIVERGE\|FAIL ' "$LOG" || true)
EQ_FILES=$(echo "$EQ_AGREE" | grep -oE '[0-9]+ corpus' | awk '{print $1}')
[[ -z "$EQ_FILES" ]] && EQ_FILES="?"
if [[ "$rc" == "0" ]]; then v=PASS
elif [[ "$EQ_DIVERGE" -gt 0 ]]; then v=FAIL
else v=PARTIAL
fi
HEAD="corpus_files=$EQ_FILES diverge=$EQ_DIVERGE rc=$rc"
record_step "eq_runner" "eq-runner JSON parity" "$v" "$HEAD"
echo "  $(verdict_color "$v")  $HEAD"

# ===========================================================================
# Step 5 — Lane 1 cold start
# ===========================================================================
step_banner 5 "Lane 1 — cold start"
LOG="$OUT_DIR/05_cold_start.log"
if bash bench/cold_start_5target.sh 11 >"$LOG" 2>&1; then rc=0; else rc=$?; fi
COLD_REPORT="$ROOT/bench/results/cold_start_5target/REPORT.md"
COLD_TABLE=""
if [[ -f "$COLD_REPORT" ]]; then
    COLD_TABLE=$(awk '/^\| target/,/^$/' "$COLD_REPORT" | head -20)
fi
COLD_FASTEST=$(echo "$COLD_TABLE" | awk -F'|' '/^\| (c|rust|zig|go|python) / { print $2"\t"$3"\t"$4 }' \
    | sort -k2 -n | head -1)
COLD_BEAT=$(echo "$COLD_TABLE" | awk -F'|' '
    /^\| (c|rust|zig|go) / { gsub(/x/,"",$4); if ($4+0 >= 1.0) n++ } END { print n+0 }')
if [[ "$rc" == "0" && -f "$COLD_REPORT" ]]; then v=PASS; else v=FAIL; fi
HEAD="fastest:$(echo "$COLD_FASTEST" | tr '\t' ' ' | xargs) ; native_beat_mainline=$COLD_BEAT/4"
record_step "cold_start" "Lane 1 cold start" "$v" "$HEAD"
echo "  $(verdict_color "$v")  $HEAD"

# ===========================================================================
# Step 6 — Lane 5 binary size
# ===========================================================================
step_banner 6 "Lane 5 — binary size"
LOG="$OUT_DIR/06_binary_size.log"
if bash bench/binary_size_5target.sh >"$LOG" 2>&1; then rc=0; else rc=$?; fi
SIZE_REPORT="$ROOT/bench/results/binary_size_5target/REPORT.md"
SIZE_HEAD="report-missing"
if [[ -f "$SIZE_REPORT" ]]; then
    SMALLEST=$(grep -E '^\*\*Smallest binary target' "$SIZE_REPORT" | head -1 | sed 's/^\*\*//;s/\*\*//')
    BEATS=$(grep -E '^\*\*C target beats mainline' "$SIZE_REPORT" | head -1 | sed 's/^\*\*//;s/\*\*//')
    SIZE_HEAD="${SMALLEST:-?} ; ${BEATS:-?}"
fi
if [[ "$rc" == "0" && -f "$SIZE_REPORT" ]]; then v=PASS; else v=FAIL; fi
record_step "binary_size" "Lane 5 binary size" "$v" "$SIZE_HEAD"
echo "  $(verdict_color "$v")  $SIZE_HEAD"

# ===========================================================================
# Step 7 — Lane 6 memory footprint
# ===========================================================================
step_banner 7 "Lane 6 — memory footprint"
LOG="$OUT_DIR/07_memory_footprint.log"
if bash bench/memory_footprint_5target.sh 5 >"$LOG" 2>&1; then rc=0; else rc=$?; fi
MEM_REPORT="$ROOT/bench/results/memory_footprint_5target/REPORT.md"
MEM_HEAD="report-missing"
if [[ -f "$MEM_REPORT" ]]; then
    LIGHTEST=$(awk -F'|' '/^\| (c|rust|zig|go|python) / { print $2"\t"$3"\t"$4"\t"$5 }' "$MEM_REPORT" \
        | sort -k2 -n | head -1 | xargs)
    MAINLINE_RSS=$(awk -F'|' '/^\| sqlite3 \(mainline\)/ { print $3 }' "$MEM_REPORT" | xargs)
    MEM_BEAT=$(awk -F'|' '/^\| (c|rust|zig|go|python) / { gsub(/x/,"",$5); if ($5+0 >= 1.0) n++ } END { print n+0 }' "$MEM_REPORT")
    MEM_HEAD="lightest: $LIGHTEST ; mainline=$MAINLINE_RSS bytes ; beat_mainline=$MEM_BEAT/5"
fi
if [[ "$rc" == "0" && -f "$MEM_REPORT" ]]; then v=PASS; else v=FAIL; fi
record_step "memory" "Lane 6 memory footprint" "$v" "$MEM_HEAD"
echo "  $(verdict_color "$v")  $MEM_HEAD"

# ===========================================================================
# Aggregate verdict
# ===========================================================================
END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

PASS_N=0; FAIL_N=0; PARTIAL_N=0
for v in "${STEP_VERDICT[@]}"; do
    case "$v" in
        PASS) PASS_N=$((PASS_N+1)) ;;
        FAIL) FAIL_N=$((FAIL_N+1)) ;;
        PARTIAL) PARTIAL_N=$((PARTIAL_N+1)) ;;
    esac
done

if [[ "$FAIL_N" == "0" && "$PARTIAL_N" == "0" ]]; then
    OVERALL=PASS
    OVERALL_LABEL="✓ stunt-grade"
elif [[ "$FAIL_N" == "0" ]]; then
    OVERALL=PARTIAL
    OVERALL_LABEL="⚠ partial"
else
    OVERALL=FAIL
    OVERALL_LABEL="✗ regressed"
fi

# Lookup helper for prose synthesis.
get_head() {
    local k="$1"; local i
    for i in "${!STEP_KEY[@]}"; do
        if [[ "${STEP_KEY[$i]}" == "$k" ]]; then echo "${STEP_HEADLINE[$i]}"; return; fi
    done
}
get_verdict() {
    local k="$1"; local i
    for i in "${!STEP_KEY[@]}"; do
        if [[ "${STEP_KEY[$i]}" == "$k" ]]; then echo "${STEP_VERDICT[$i]}"; return; fi
    done
}

# ---------------------------------------------------------------------------
# Write REPORT.md
# ---------------------------------------------------------------------------
{
    echo "# sqlite-leap — 5-target stunt aggregator"
    echo
    echo "Generated $(date -u +'%Y-%m-%dT%H:%M:%SZ') on $(uname -sm) in ${ELAPSED}s."
    echo "Branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo n/a)  ·  HEAD: $(git rev-parse --short HEAD 2>/dev/null || echo n/a)"
    echo
    echo "## TL;DR"
    echo
    echo "**One language-neutral spec → five working SQLite implementations** (Rust,"
    echo "C, Zig, Go, Python). This aggregator runs every 5-target proof on the"
    echo "branch and grades the result. Verdict: **$OVERALL_LABEL**"
    echo "(pass=$PASS_N partial=$PARTIAL_N fail=$FAIL_N out of ${#STEP_VERDICT[@]})."
    echo
    echo "Highlights:"
    echo "- SLT parity: $(get_head slt_parity)"
    echo "- Fileformat-write byte-identity: $(get_head fileformat_write)"
    echo "- Deep-split byte-identity: $(get_head fileformat_deep_split)"
    echo "- eq-runner JSON parity: $(get_head eq_runner)"
    echo "- Lane 1 cold start: $(get_head cold_start)"
    echo "- Lane 5 binary size: $(get_head binary_size)"
    echo "- Lane 6 memory: $(get_head memory)"
    echo
    echo "## Result table"
    echo
    echo "| # | Proof | Verdict | Headline |"
    echo "|---:|---|:-:|---|"
    for i in "${!STEP_KEY[@]}"; do
        n=$((i+1))
        echo "| $n | ${STEP_TITLE[$i]} | $(verdict_glyph "${STEP_VERDICT[$i]}") ${STEP_VERDICT[$i]} | ${STEP_HEADLINE[$i]} |"
    done
    echo

    # ----- Per-proof detail sections -------------------------------------
    echo "## 1. 5-target SLT parity"
    echo
    echo "Driver: \`run_slt_5target.sh $SLT_FIXTURE\`"
    echo
    echo "Headline: $(get_head slt_parity)"
    echo
    if [[ -n "$SLT_TOTALS" ]]; then
        echo "Per-target summary:"
        echo
        echo '```'
        echo "$SLT_TOTALS"
        echo '```'
    fi
    echo "Log: \`$OUT_DIR/01_slt_parity.log\`"
    echo

    echo "## 2. 5-target fileformat-write byte-identity"
    echo
    echo "Each target appends one row to a copy of \`tests/fixtures/tiny.db\` then"
    echo "we sha1sum the resulting files. Stunt grade requires all 5 SHAs equal."
    echo
    echo "Headline: $(get_head fileformat_write)"
    echo
    if [[ ${#WRITE_TARGETS[@]} -gt 0 ]]; then
        echo '| target | sha1 |'
        echo '|---|---|'
        for i in "${!WRITE_TARGETS[@]}"; do
            echo "| ${WRITE_TARGETS[$i]} | \`${WRITE_SHAS[$i]}\` |"
        done
        echo
    fi
    echo "Log: \`$OUT_DIR/02_fileformat_write.log\`"
    echo

    echo "## 3. 5-target deep-split byte-identity (270 + 5000 rows)"
    echo
    echo "Multi-page btree-write probe: each target prefills + inserts to trigger"
    echo "root-split (270 rows) and recursive split (5000 rows). All 5 .db files"
    echo "must be byte-identical at each prefill level."
    echo
    echo "Headline: $(get_head fileformat_deep_split)"
    echo
    for line in "${DEEP_VERDICTS[@]}"; do
        echo "- $line"
    done
    echo
    echo "Log: \`$OUT_DIR/03_fileformat_deep_split.log\`"
    echo

    echo "## 4. 5-target eq-runner JSON parity"
    echo
    echo "Driver: \`run_eq_check.sh\`. Each target's eq_runner emits canonical JSON"
    echo "for every corpus file under \`parts/eq-harness/corpus/\`; outputs must be"
    echo "byte-identical across all 5 targets."
    echo
    echo "Headline: $(get_head eq_runner)"
    echo
    grep -E '^==|matches|reference|DIVERGE|FAIL ' "$OUT_DIR/04_eq_check.log" 2>/dev/null \
        | sed 's/^/    /' || true
    echo
    echo "Log: \`$OUT_DIR/04_eq_check.log\`"
    echo

    echo "## 5. Lane 1 — cold start"
    echo
    echo "Driver: \`bench/cold_start_5target.sh\`. Median wallclock over 11 samples"
    echo "for cold-process \`SELECT 1+2\`. Mainline baseline = \`sqlite3 :memory:\`."
    echo
    echo "Headline: $(get_head cold_start)"
    echo
    if [[ -f "$COLD_REPORT" ]]; then
        awk '/^\| target/,/^$/' "$COLD_REPORT" | head -20
        echo
    fi
    echo "Full report: \`bench/results/cold_start_5target/REPORT.md\`"
    echo

    echo "## 6. Lane 5 — binary size"
    echo
    echo "Driver: \`bench/binary_size_5target.sh\`. Each target builds the SELECT"
    echo "behavioral smoke with smallest-binary flags; mainline baseline =\`/usr/bin/sqlite3\`."
    echo
    echo "Headline: $(get_head binary_size)"
    echo
    if [[ -f "$SIZE_REPORT" ]]; then
        awk '/^\| target/,/^$/' "$SIZE_REPORT" | head -20
        echo
        grep -E '^\*\*' "$SIZE_REPORT" | head -3
        echo
    fi
    echo "Full report: \`bench/results/binary_size_5target/REPORT.md\`"
    echo

    echo "## 7. Lane 6 — memory footprint"
    echo
    echo "Driver: \`bench/memory_footprint_5target.sh\`. Median peak RSS over 5"
    echo "samples for CREATE+1000 INSERT+SELECT. Mainline baseline = \`sqlite3\`."
    echo
    echo "Headline: $(get_head memory)"
    echo
    if [[ -f "$MEM_REPORT" ]]; then
        awk '/^\| target/,/^$/' "$MEM_REPORT" | head -20
        echo
    fi
    echo "Full report: \`bench/results/memory_footprint_5target/REPORT.md\`"
    echo

    echo "## Final verdict"
    echo
    echo "**$OVERALL_LABEL**"
    echo
    echo "- ${PASS_N} of ${#STEP_VERDICT[@]} proofs PASS"
    [[ $PARTIAL_N -gt 0 ]] && echo "- ${PARTIAL_N} PARTIAL"
    [[ $FAIL_N -gt 0 ]] && echo "- ${FAIL_N} FAIL"
    echo "- elapsed: ${ELAPSED}s"
    echo
    echo "_Reproduce: \`bash demo_5target_stunt.sh\` (idempotent; ~5 min on warm laptop)._"
} > "$REPORT"

# ---------------------------------------------------------------------------
# Final tmux-friendly banner
# ---------------------------------------------------------------------------
banner "Final verdict: $OVERALL_LABEL"
for i in "${!STEP_KEY[@]}"; do
    n=$((i+1))
    printf "  %d. %-42s %s\n" "$n" "${STEP_TITLE[$i]}" "$(verdict_color "${STEP_VERDICT[$i]}")"
done
echo
echo "  Report:  $REPORT"
echo "  Elapsed: ${ELAPSED}s"
echo
case "$OVERALL" in
    PASS) echo -e "${GREEN}${BOLD}  ✓ stunt-grade${NC}" ;;
    PARTIAL) echo -e "${YELLOW}${BOLD}  ⚠ partial${NC}" ;;
    FAIL) echo -e "${RED}${BOLD}  ✗ regressed${NC}" ;;
esac
echo

# Always exit 0 — the report is the artifact; aggregate verdict is in REPORT.md.
exit 0
