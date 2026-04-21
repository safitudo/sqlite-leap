#!/usr/bin/env bash
# Generate the C implementation of sqlite-leap into ../../src-c/
#
# Inputs (read-only):
#   CLAUDE.md, master.md, spec/**, schema/**, parts/**, tests/**
# Output:
#   src-c/**  — self-contained C code + build files (CMakeLists or Makefile)
#
# Forbidden sources: mainline SQLite source, Turso source, other SQLite-compatible
# implementations, `_original/`. See CLAUDE.md for the full list.
#
# This stub exists so the generator contract is visible from day one. Phase 1
# replaces the body with a real AI-agent invocation.

set -euo pipefail

cd "$(dirname "$0")/../.."
REPO_ROOT="$(pwd)"

echo "[generators/c] Target: $REPO_ROOT/src-c/"
echo "[generators/c] Inputs: CLAUDE.md, master.md, spec/, schema/, parts/, tests/"
echo "[generators/c] NOT IMPLEMENTED YET — wire up in Phase 1."
exit 2
