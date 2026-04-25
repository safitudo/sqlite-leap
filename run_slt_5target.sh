#!/usr/bin/env bash
# 5-target sqllogictest matrix harness.
#
# Runs the canonical .test fixture against every target's SLT driver
# and emits a (target × record) matrix of PASS/FAIL/DEFER.
#
# Per-target driver contract (see tests/sqllogictest/5target_harness/):
#   * argv[1] is the .test file path
#   * stdout: one line per record, format
#       <PASS|FAIL|DEFER> <line> <kind> [detail...]
#     followed by exactly one summary line:
#       SUMMARY target=<name> pass=<int> fail=<int> defer=<int> total=<int>
#   * exit 0 iff fail == 0
#
# Targets with no driver (C / Zig / Go at v1) are reported as
# DEFER on every record — they do not yet expose a SQL-text-driven
# entry point. Adding one is mechanical (mirror src-rust/.../slt_runner)
# but out of scope for this harness's first cut.
#
# Exit 0 iff every target with a driver produced fail == 0.

set -o pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

TEST_FILE="${1:-tests/sqllogictest/5target_harness/canonical.test}"
if [[ ! -f "$TEST_FILE" ]]; then
    echo "test file not found: $TEST_FILE" >&2
    exit 2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

GREEN="\033[0;32m"
RED="\033[0;31m"
YELLOW="\033[0;33m"
DIM="\033[2m"
BOLD="\033[1m"
NC="\033[0m"

echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  5-target sqllogictest matrix${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo
echo "Fixture: $TEST_FILE"
echo

# ----- Build phase --------------------------------------------------

echo -e "${BOLD}── Building per-target drivers ──${NC}"

build_rust()  {
    (cd src-rust && cargo build --release --quiet --example slt_runner) \
        > "$TMP/build.rust.log" 2>&1
}
build_python(){ :; }
build_c()     {
    ./src-c/build_slt_runner.sh > "$TMP/build.c.log" 2>&1
}
build_zig()   {
    bash src-zig/build_slt_runner.sh > "$TMP/build.zig.log" 2>&1
}
build_go()    {
    (cd src-go && ./build_slt_runner.sh) > "$TMP/build.go.log" 2>&1
}

run_rust()    { src-rust/target/release/examples/slt_runner "$1"; }
run_python()  {
    PYTHONPATH=src-python python3 \
        tests/sqllogictest/5target_harness/driver_python.py "$1"
}
run_c()       { src-c/build/slt_runner "$1"; }
run_zig()     { src-zig/zig-out/bin/slt_runner "$1"; }
run_go()      { src-go/slt_runner "$1"; }

BUILD_OK_LIST=""    # space-separated list of built-ok targets
build_ok() { case " $BUILD_OK_LIST " in *" $1 "*) return 0;; *) return 1;; esac; }
for t in rust python c zig go; do
    printf "  %-7s ... " "$t"
    if build_$t; then
        echo -e "${GREEN}ok${NC}"
        BUILD_OK_LIST="$BUILD_OK_LIST $t"
    else
        echo -e "${YELLOW}DEFER${NC} (no driver)"
    fi
done
echo

# ----- Run phase ----------------------------------------------------

echo -e "${BOLD}── Running each target on the fixture ──${NC}"
echo

for t in rust python c zig go; do
    if build_ok "$t"; then
        run_$t "$TEST_FILE" > "$TMP/$t.out" 2> "$TMP/$t.err" || true
    fi
done

# Extract record list from the rust driver's output (any driver works
# — output is stable across drivers since they parse the same fixture).
REF_TARGET=""
for t in rust python; do
    if build_ok "$t" && [[ -s "$TMP/$t.out" ]]; then
        REF_TARGET="$t"; break
    fi
done
if [[ -z "$REF_TARGET" ]]; then
    echo "no driver produced output — cannot build matrix" >&2
    exit 1
fi

RECORD_KEYS=()
while IFS= read -r line; do
    RECORD_KEYS+=("$line")
done < <(grep -E '^(PASS|FAIL|DEFER) ' "$TMP/$REF_TARGET.out" \
    | awk '{ printf "%s/%s\n", $2, $3 }')

# Build per-target verdict map and per-record column.
get_verdict() {
    local target="$1"; local key="$2"
    if ! build_ok "$target"; then
        echo "DEFER"; return
    fi
    local line="${key%%/*}"
    local kind="${key##*/}"
    local v
    v=$(awk -v ln="$line" -v k="$kind" \
        '$2==ln && $3==k && ($1=="PASS" || $1=="FAIL" || $1=="DEFER") { print $1; exit }' \
        "$TMP/$target.out")
    if [[ -z "$v" ]]; then v="?"; fi
    echo "$v"
}

# ----- Render matrix ------------------------------------------------

printf "%-7s %-10s" "line" "kind"
for t in rust python c zig go; do
    printf " %-7s" "$t"
done
echo

for key in "${RECORD_KEYS[@]}"; do
    line="${key%%/*}"
    kind="${key##*/}"
    printf "%-7s %-10s" "$line" "$kind"
    for t in rust python c zig go; do
        v=$(get_verdict "$t" "$key")
        case "$v" in
            PASS)  color="$GREEN" ;;
            FAIL)  color="$RED" ;;
            DEFER) color="$YELLOW" ;;
            *)     color="$DIM" ;;
        esac
        printf " ${color}%-7s${NC}" "$v"
    done
    echo
done
echo

# ----- Summaries + divergence detection ----------------------------

echo -e "${BOLD}── Per-target summary ──${NC}"
OVERALL=0
for t in rust python c zig go; do
    if build_ok "$t"; then
        line=$(grep '^SUMMARY' "$TMP/$t.out" || echo "SUMMARY target=$t MISSING")
        echo "  $line"
        if grep -q "^SUMMARY .* fail=0 " <<<"$line"; then :; else OVERALL=1; fi
    else
        echo -e "  ${YELLOW}SUMMARY target=$t SKIPPED (no driver)${NC}"
    fi
done

# Divergence: among targets that have a driver, fail if any record
# disagrees with the others (excluding DEFER).
echo
echo -e "${BOLD}── Cross-target equivalence ──${NC}"
DIVERGE=0
for key in "${RECORD_KEYS[@]}"; do
    line="${key%%/*}"; kind="${key##*/}"
    seen=""
    for t in rust python c zig go; do
        build_ok "$t" || continue
        v=$(get_verdict "$t" "$key")
        [[ "$v" == "DEFER" || "$v" == "?" ]] && continue
        if [[ -z "$seen" ]]; then
            seen="$v"
        elif [[ "$seen" != "$v" ]]; then
            echo -e "  ${RED}DIVERGE${NC} line=$line kind=$kind: targets disagree"
            DIVERGE=1
            break
        fi
    done
done
if [[ "$DIVERGE" == "0" ]]; then
    echo -e "  ${GREEN}OK${NC} all participating targets agree on every record"
fi

echo
if [[ "$OVERALL" == "0" && "$DIVERGE" == "0" ]]; then
    echo -e "${BOLD}${GREEN}RESULT: every participating target green; no divergence.${NC}"
    exit 0
else
    echo -e "${BOLD}${RED}RESULT: failure or divergence detected (see above).${NC}"
    exit 1
fi
