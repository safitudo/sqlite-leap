#!/bin/bash
# Run all phase test binaries in src-rust/target/release
set -u
cd "$(dirname "$0")"
RELEASE=src-rust/target/release
CROSS=tests/cross-build
FAILED=0
TOTAL=0
for bin in "$RELEASE"/phase*-test; do
    name=$(basename "$bin")
    phase=${name#phase}
    phase=${phase%-test}
    json="$CROSS/phase${phase}.json"
    if [ ! -f "$json" ]; then
        continue
    fi
    TOTAL=$((TOTAL + 1))
    output=$("$bin" "$json" 2>&1)
    summary=$(echo "$output" | grep "^SUMMARY" | tail -1)
    if echo "$summary" | grep -q "failed=0"; then
        echo "OK phase${phase}: $summary"
    else
        echo "FAIL phase${phase}: $summary"
        FAILED=$((FAILED + 1))
    fi
done
echo ""
echo "=== Regression: $((TOTAL - FAILED))/$TOTAL pass ==="
exit $FAILED
