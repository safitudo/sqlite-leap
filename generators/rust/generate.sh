#!/usr/bin/env bash
# Generate the Rust implementation of sqlite-leap into ../../src-rust/
#
# Inputs (read-only):
#   CLAUDE.md, master.md, spec/**, schema/**, parts/**, tests/**
# Output:
#   src-rust/**  — self-contained cargo crate
#
# Forbidden sources: mainline SQLite source, Turso source, rusqlite, sqlx internals,
# `_original/`. See CLAUDE.md for the full list.
#
# This stub exists so the generator contract is visible from day one. Phase 1
# replaces the body with a real AI-agent invocation.

set -euo pipefail

cd "$(dirname "$0")/../.."
REPO_ROOT="$(pwd)"

echo "[generators/rust] Target: $REPO_ROOT/src-rust/"
echo "[generators/rust] Inputs: CLAUDE.md, master.md, spec/, schema/, parts/, tests/"
echo "[generators/rust] NOT IMPLEMENTED YET — wire up in Phase 1."
exit 2
