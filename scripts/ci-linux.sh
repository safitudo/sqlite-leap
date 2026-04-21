#!/usr/bin/env bash
# ci-linux.sh — Linux cross-validation harness for sqlite-leap.
#
# Intended to run inside the Dockerfile.linux image. Builds the C and Rust
# targets, runs every phase*_test binary on its matching cross-build JSON
# fixture, runs a sqllogictest smoke pass, and prints a single-line
# CI-SUMMARY. Exits non-zero on any failure.
#
# Portable bash (no GNU-coreutils-only flags). Tested invocation:
#     docker run --rm -v "$PWD":/repo -w /repo sqlite-leap-ci \
#         /repo/scripts/ci-linux.sh

set -u
set -o pipefail

# --- repo root ---------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

RUST_DIR="$REPO_ROOT/src-rust"
C_DIR="$REPO_ROOT/src-c"
CROSS_DIR="$REPO_ROOT/tests/cross-build"
SMOKE_DIR="$REPO_ROOT/tests/sqllogictest/smoke"

RUST_RELEASE_DIR="$RUST_DIR/target/release"
C_BIN_DIR="$C_DIR/bin"

FAIL=0
STEP_FAILS=""

note() { printf '[ci-linux] %s\n' "$*"; }
fail_step() {
    FAIL=$((FAIL + 1))
    STEP_FAILS="${STEP_FAILS}${STEP_FAILS:+, }$1"
    note "STEP FAIL: $1"
}

# --- preflight ---------------------------------------------------------------
note "repo root: $REPO_ROOT"
note "rustc:    $(rustc --version 2>/dev/null || echo 'missing')"
note "cargo:    $(cargo --version 2>/dev/null || echo 'missing')"
note "cc:       $(cc --version 2>/dev/null | head -n1 || echo 'missing')"
note "make:     $(make --version 2>/dev/null | head -n1 || echo 'missing')"

if [ ! -d "$RUST_DIR" ]; then
    note "FATAL: $RUST_DIR missing (did generators run?)"
    echo "CI-SUMMARY linux RED phases=0/0 reason=no-src-rust"
    exit 2
fi
if [ ! -d "$C_DIR" ]; then
    note "FATAL: $C_DIR missing (did generators run?)"
    echo "CI-SUMMARY linux RED phases=0/0 reason=no-src-c"
    exit 2
fi

# --- build Rust target -------------------------------------------------------
note "=== cargo build --release (src-rust) ==="
if ( cd "$RUST_DIR" && cargo build --release ); then
    note "rust build OK"
else
    fail_step "rust-build"
fi

# --- build C target ----------------------------------------------------------
note "=== make (src-c) ==="
if ( cd "$C_DIR" && make ); then
    note "c build OK"
else
    fail_step "c-build"
fi

# If either build failed, phase-runs can't happen — bail with summary.
if [ "$FAIL" -ne 0 ]; then
    echo "CI-SUMMARY linux RED phases=0/0 failed_steps=$STEP_FAILS"
    exit 1
fi

# --- run Rust phase tests ----------------------------------------------------
# Each Rust bin is named phase<X>-test; cross-build fixture is phase<X>.json.
note "=== Rust phase tests ==="
RUST_TOTAL=0
RUST_PASS=0
RUST_FAILED_PHASES=""
for bin in "$RUST_RELEASE_DIR"/phase*-test; do
    [ -x "$bin" ] || continue
    name="$(basename "$bin")"                  # phase6bo-test
    phase="${name#phase}"                      # 6bo-test
    phase="${phase%-test}"                     # 6bo
    json="$CROSS_DIR/phase${phase}.json"
    if [ ! -f "$json" ]; then
        note "SKIP rust phase${phase} (no fixture $json)"
        continue
    fi
    RUST_TOTAL=$((RUST_TOTAL + 1))
    output="$("$bin" "$json" 2>&1)" || true
    summary="$(printf '%s\n' "$output" | grep '^SUMMARY' | tail -n1)"
    if [ -n "$summary" ] && printf '%s' "$summary" | grep -q 'failed=0'; then
        RUST_PASS=$((RUST_PASS + 1))
    else
        RUST_FAILED_PHASES="${RUST_FAILED_PHASES}${RUST_FAILED_PHASES:+,}${phase}"
        note "FAIL rust phase${phase}: ${summary:-<no-summary>}"
    fi
done
note "rust phases: $RUST_PASS/$RUST_TOTAL pass"
if [ "$RUST_PASS" -ne "$RUST_TOTAL" ] || [ "$RUST_TOTAL" -eq 0 ]; then
    fail_step "rust-phases($RUST_FAILED_PHASES)"
fi

# --- run C phase tests -------------------------------------------------------
note "=== C phase tests ==="
C_TOTAL=0
C_PASS=0
C_FAILED_PHASES=""
for bin in "$C_BIN_DIR"/phase*-test; do
    [ -x "$bin" ] || continue
    name="$(basename "$bin")"
    phase="${name#phase}"
    phase="${phase%-test}"
    json="$CROSS_DIR/phase${phase}.json"
    if [ ! -f "$json" ]; then
        note "SKIP c phase${phase} (no fixture $json)"
        continue
    fi
    C_TOTAL=$((C_TOTAL + 1))
    output="$("$bin" "$json" 2>&1)" || true
    summary="$(printf '%s\n' "$output" | grep '^SUMMARY' | tail -n1)"
    if [ -n "$summary" ] && printf '%s' "$summary" | grep -q 'failed=0'; then
        C_PASS=$((C_PASS + 1))
    else
        C_FAILED_PHASES="${C_FAILED_PHASES}${C_FAILED_PHASES:+,}${phase}"
        note "FAIL c phase${phase}: ${summary:-<no-summary>}"
    fi
done
note "c phases: $C_PASS/$C_TOTAL pass"
if [ "$C_PASS" -ne "$C_TOTAL" ] || [ "$C_TOTAL" -eq 0 ]; then
    fail_step "c-phases($C_FAILED_PHASES)"
fi

# --- sqllogictest smoke ------------------------------------------------------
# The sqllogictest binary consumes .test files (not the cross-build JSON
# fixtures). Run it against the committed smoke dir as a representative
# smoke pass — for both Rust and C builds. If the smoke dir is missing,
# the step is skipped (not failed).
note "=== sqllogictest smoke ==="
SLT_RUST_BIN="$RUST_RELEASE_DIR/sqllogictest"
SLT_C_BIN="$C_BIN_DIR/sqllogictest"

if [ ! -d "$SMOKE_DIR" ]; then
    note "SKIP sqllogictest smoke (no $SMOKE_DIR)"
else
    if [ -x "$SLT_RUST_BIN" ]; then
        note "--- rust sqllogictest smoke ---"
        if "$SLT_RUST_BIN" "$SMOKE_DIR"; then
            note "rust sqllogictest smoke OK"
        else
            fail_step "rust-sqllogictest-smoke"
        fi
    else
        note "SKIP rust sqllogictest (bin missing: $SLT_RUST_BIN)"
    fi

    if [ -x "$SLT_C_BIN" ]; then
        note "--- c sqllogictest smoke ---"
        if "$SLT_C_BIN" "$SMOKE_DIR"; then
            note "c sqllogictest smoke OK"
        else
            fail_step "c-sqllogictest-smoke"
        fi
    else
        note "SKIP c sqllogictest (bin missing: $SLT_C_BIN)"
    fi
fi

# --- final summary -----------------------------------------------------------
TOTAL_PHASES=$((RUST_TOTAL + C_TOTAL))
PASS_PHASES=$((RUST_PASS + C_PASS))
if [ "$FAIL" -eq 0 ]; then
    echo "CI-SUMMARY linux green phases=${PASS_PHASES}/${TOTAL_PHASES}"
    exit 0
else
    echo "CI-SUMMARY linux RED phases=${PASS_PHASES}/${TOTAL_PHASES} failed_steps=${STEP_FAILS}"
    exit 1
fi
