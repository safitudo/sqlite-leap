#!/usr/bin/env bash
# Regenerate one part for the C target.
#
# Usage:
#   generators/c/generate.sh <part-path>
#
# Example:
#   generators/c/generate.sh storage/btree-write
#
# This script is the per-target entry point; the actual brief assembly
# lives in generators/leapgen.py (--target c). The emission step itself
# is an LLM agent run, not a deterministic compiler — that is the honest
# state of the LEAP pipeline as of 2026-04-28. See docs/DASHBOARD.md for
# regen envelope notes (some monolithic files exceed agent regen reliability).

set -euo pipefail

cd "$(dirname "$0")/../.."
REPO_ROOT="$(pwd)"

if [ $# -lt 1 ]; then
  cat >&2 <<'EOF'
usage: generators/c/generate.sh <part-path>

Examples:
  generators/c/generate.sh vdbe/opcodes-rows
  generators/c/generate.sh storage/btree-write
  generators/c/generate.sh parser/tokenizer

The script prints the universal LEAP build brief for <part-path> × C target
to stdout. Pipe it to your agent harness (Claude Code Agent tool, Anthropic
API, etc.) to produce src-c/ output.

The emission is NOT deterministic; it is an LLM agent run. Inspect the
brief, run the agent, then diff its output against the existing src-c/
tree to evaluate the regeneration.
EOF
  exit 2
fi

PART="$1"

exec python3 "$REPO_ROOT/generators/leapgen.py" --part "$PART" --target c
