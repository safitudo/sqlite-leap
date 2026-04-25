#!/usr/bin/env bash
# Cross-target equivalence harness — top-level driver.
#
# Builds (or rebuilds) the per-target eq_runner binaries, runs each one
# against every corpus file under parts/eq-harness/corpus/, and verifies
# that the canonical-JSON line each runner prints to stdout is byte-
# identical across all 5 targets.
#
# Per-target runner contract (parts/eq-harness/master.md):
#   * argv[1] is the corpus JSON path
#   * stdout is exactly one line of canonical JSON:
#       {"name":"<name>","observed":[<rows>]}
#     with keys alphabetically sorted, no whitespace, NaN/Inf as quoted
#     strings.
#   * stderr carries diagnostics; exit 0 on success, non-zero on error.
#
# Exit 0 iff every corpus file produced byte-identical output across
# every target that built. Targets that fail to build are reported but
# do not silently mask divergence.
set -o pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

CORPUS_DIR="$ROOT/parts/eq-harness/corpus"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ----- Build phase --------------------------------------------------------

BUILD_FAIL=""    # space-separated list of failed targets

build_rust() {
    (cd src-rust && cargo build --release --quiet --example eq_runner) \
        > "$TMP/build.rust.log" 2>&1
}
build_python() { :; }   # no build step
build_go() {
    (cd src-go && go build -o "$TMP/eq_runner_go" ./cmd/eq_runner) \
        > "$TMP/build.go.log" 2>&1
}
build_zig() {
    (cd src-zig && zig build install) > "$TMP/build.zig.log" 2>&1
}
build_c() {
    bash src-c/build_eq_runner.sh > "$TMP/build.c.log" 2>&1
}

for t in rust python go zig c; do
    printf "build %-6s ... " "$t"
    if build_$t; then
        echo "ok"
    else
        echo "FAIL (see $TMP/build.$t.log)"
        BUILD_FAIL="$BUILD_FAIL $t"
    fi
done

build_failed() { case " $BUILD_FAIL " in *" $1 "*) return 0;; *) return 1;; esac; }

run_rust()   { src-rust/target/release/examples/eq_runner "$1"; }
run_python() { PYTHONPATH=src-python python3 src-python/eq_runner.py "$1"; }
run_go()     { "$TMP/eq_runner_go" "$1"; }
run_zig()    { src-zig/zig-out/bin/eq_runner "$1"; }
run_c()      { src-c/build/eq_runner "$1"; }

# ----- Run phase ----------------------------------------------------------

shopt -s nullglob
CORPUS_FILES=("$CORPUS_DIR"/*.json)
shopt -u nullglob

if [ "${#CORPUS_FILES[@]}" -eq 0 ]; then
    echo "no corpus files in $CORPUS_DIR" >&2
    exit 2
fi

OVERALL=0

for corpus in "${CORPUS_FILES[@]}"; do
    name="$(basename "$corpus" .json)"
    echo
    echo "== $name =="

    REF=""
    REF_TARGET=""
    for t in rust python go zig c; do
        out_file="$TMP/$name.$t.out"
        err_file="$TMP/$name.$t.err"
        if build_failed "$t"; then
            printf "  %-6s SKIP (build failed)\n" "$t"
            continue
        fi
        run_$t "$corpus" > "$out_file" 2> "$err_file"
        rc=$?
        if [ $rc -ne 0 ]; then
            printf "  %-6s FAIL (exit %d)\n" "$t" "$rc"
            sed -n '1,3p' "$err_file" | sed 's/^/         | /'
            OVERALL=1
            continue
        fi
        if [ -z "$REF" ]; then
            REF="$out_file"
            REF_TARGET="$t"
            printf "  %-6s OK   (reference)\n" "$t"
        else
            if diff -q "$REF" "$out_file" > /dev/null; then
                printf "  %-6s OK   (matches %s)\n" "$t" "$REF_TARGET"
            else
                printf "  %-6s DIVERGE vs %s\n" "$t" "$REF_TARGET"
                echo "    --- $REF_TARGET" ; sed 's/^/    /' "$REF"
                echo "    --- $t"          ; sed 's/^/    /' "$out_file"
                diff -u "$REF" "$out_file" | sed 's/^/    /'
                OVERALL=1
            fi
        fi
    done
done

echo
if [ $OVERALL -eq 0 ]; then
    echo "RESULT: all targets agree on canonical output across ${#CORPUS_FILES[@]} corpus file(s)"
else
    echo "RESULT: divergence detected (see above)"
fi
exit $OVERALL
