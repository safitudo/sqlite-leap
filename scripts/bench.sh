#!/usr/bin/env bash
# Convenience wrapper: `scripts/bench.sh` == `bench/run-all.sh`.
# Kept so contributors who type `scripts/` muscle-memory first still find
# the harness entry point.
set -euo pipefail
REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$REPO/bench/run-all.sh" "$@"
