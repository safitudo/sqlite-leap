#!/usr/bin/env bash
# Regenerate the WASM target.
#
# Unlike generators/c and generators/rust, the wasm "generation" step is just a
# compile of src-rust/ to wasm32-unknown-unknown with a JS-facing wrapper. The
# actual work lives in build.sh; this script exists so generators/all.sh can
# call every target through a uniform `generate.sh` entry point.
#
# If you're iterating on wasm specifically, call ./build.sh directly — it
# accepts PROFILE=dev for faster rebuilds.

set -euo pipefail
exec "$(dirname "$0")/build.sh" "$@"
