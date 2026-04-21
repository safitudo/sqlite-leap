#!/usr/bin/env bash
# Regenerate every build target from scratch. Fails fast on the first generator
# that errors so we surface problems early.

set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

echo "[generators/all] Regenerating all three targets from spec/ + schema/ + parts/ + tests/"
echo ""

"$REPO_ROOT/generators/c/generate.sh"
"$REPO_ROOT/generators/rust/generate.sh"
"$REPO_ROOT/generators/wasm/generate.sh"

echo ""
echo "[generators/all] All three generators succeeded."
