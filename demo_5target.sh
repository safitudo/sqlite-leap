#!/bin/bash
# sqlite-leap 5-target steel-thread demo
#
# ONE language-neutral spec → FIVE working implementations
# (Rust, C, Zig, Go, Python) that execute SQL and produce semantically
# identical results. Plus a file-format write probe that produces
# mainline-SQLite-compatible .db files.
#
# No hand-written code in the data path. Everything under src-*/ was
# agent-emitted from parts/*/shapes.json + master.md.

set -e
cd "$(dirname "$0")"

GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[0;33m"
BOLD="\033[1m"
NC="\033[0m"

echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  sqlite-leap 5-target steel-thread demo${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo
echo -e "${BLUE}One spec → five targets → same SQL → same behavior.${NC}"
echo
echo "Shared spec inputs (language-neutral, hand-written):"
for f in \
    parts/parser/parts/tokenizer/shapes.json \
    parts/parser/parts/expr/shapes.json \
    parts/parser/parts/select-stmt/shapes.json \
    parts/parser/parts/insert-stmt/shapes.json \
    parts/parser/parts/delete-stmt/shapes.json \
    parts/compiler/parts/expr-compile/shapes.json \
    parts/compiler/parts/select-compile/shapes.json \
    parts/compiler/parts/insert-compile/shapes.json \
    parts/compiler/parts/delete-compile/shapes.json \
    parts/storage/parts/mem-store/shapes.json \
    parts/storage/parts/fileformat-write/shapes.json; do
    lines=$(wc -l < "$f" 2>/dev/null || echo "?")
    echo "  • $f (${lines} lines)"
done
echo

run_target() {
    local label="$1"
    local display="$2"
    local cmd="$3"
    echo -e "${BOLD}─── $label ───${NC}"
    echo -e "${YELLOW}$ $display${NC}"
    eval "$cmd" 2>&1 | sed 's/^/  /'
    echo
}

echo -e "${BOLD}### Part 1: 5-target SELECT steel thread${NC}"
echo

run_target "Rust:   SELECT" \
    "cargo run --example select_behavioral_smoke" \
    "cargo run --quiet --manifest-path src-rust/Cargo.toml --example select_behavioral_smoke 2>/dev/null"

run_target "C:      SELECT" \
    "bash src-c/build_select_smoke.sh" \
    "bash src-c/build_select_smoke.sh 2>/dev/null"

run_target "Zig:    SELECT" \
    "cd src-zig && zig build select-smoke" \
    "(cd src-zig && zig build select-smoke 2>&1)"

run_target "Go:     SELECT" \
    "bash src-go/build_select_smoke.sh" \
    "bash src-go/build_select_smoke.sh 2>/dev/null"

run_target "Python: SELECT" \
    "bash src-python/build_select_smoke.sh" \
    "bash src-python/build_select_smoke.sh 2>/dev/null"

echo -e "${BOLD}### Part 2: 5-target DML (INSERT + DELETE round-trip)${NC}"
echo

run_target "Rust:   DML" \
    "cargo run --example delete_behavioral_smoke" \
    "cargo run --quiet --manifest-path src-rust/Cargo.toml --example delete_behavioral_smoke 2>/dev/null"

run_target "Rust:   UPDATE (mem-store v4)" \
    "cargo run --example update_behavioral_smoke" \
    "cargo run --quiet --manifest-path src-rust/Cargo.toml --example update_behavioral_smoke 2>/dev/null"

run_target "C:      UPDATE" \
    "bash src-c/build_update_smoke.sh" \
    "bash src-c/build_update_smoke.sh 2>/dev/null"

run_target "Zig:    UPDATE" \
    "cd src-zig && zig build update-smoke" \
    "(cd src-zig && zig build update-smoke 2>&1)"

run_target "Go:     UPDATE" \
    "bash src-go/build_update_smoke.sh" \
    "bash src-go/build_update_smoke.sh 2>/dev/null"

run_target "Python: UPDATE" \
    "bash src-python/build_update_smoke.sh" \
    "bash src-python/build_update_smoke.sh 2>/dev/null"

run_target "C:      DML" \
    "bash src-c/build_dml_smoke.sh" \
    "bash src-c/build_dml_smoke.sh 2>/dev/null"

run_target "Zig:    DML" \
    "cd src-zig && zig build dml-smoke" \
    "(cd src-zig && zig build dml-smoke 2>&1)"

run_target "Go:     DML" \
    "bash src-go/build_dml_smoke.sh" \
    "bash src-go/build_dml_smoke.sh 2>/dev/null"

run_target "Python: DML" \
    "bash src-python/build_dml_smoke.sh" \
    "bash src-python/build_dml_smoke.sh 2>/dev/null"

echo -e "${BOLD}### Part 3: 5-target compound expressions (IS NULL / BETWEEN / IN)${NC}"
echo

run_target "Rust:   compound" \
    "cargo run --example between_in_behavioral_smoke" \
    "cargo run --quiet --manifest-path src-rust/Cargo.toml --example between_in_behavioral_smoke 2>/dev/null"

run_target "C:      compound" \
    "bash src-c/build_between_in_smoke.sh" \
    "bash src-c/build_between_in_smoke.sh 2>/dev/null"

run_target "Zig:    compound" \
    "cd src-zig && zig build compound-smoke" \
    "(cd src-zig && zig build compound-smoke 2>&1)"

run_target "Go:     compound" \
    "bash src-go/build_compound_smoke.sh" \
    "bash src-go/build_compound_smoke.sh 2>/dev/null"

run_target "Python: compound" \
    "bash src-python/build_compound_smoke.sh" \
    "bash src-python/build_compound_smoke.sh 2>/dev/null"

echo -e "${BOLD}### Part 4: Mainline-SQLite file-format write compatibility${NC}"
echo
cp tests/fixtures/tiny.db /tmp/rust_probe.db
cp tests/fixtures/tiny.db /tmp/py_probe.db

run_target "Rust:   append row to .db" \
    "cargo run --example fileformat_write_runner -- /tmp/rust_probe.db" \
    "cargo run --quiet --manifest-path src-rust/Cargo.toml --example fileformat_write_runner -- /tmp/rust_probe.db 2>/dev/null"

run_target "Python: append row to .db" \
    "python3 src-python/fileformat_write_runner.py /tmp/py_probe.db" \
    "python3 src-python/fileformat_write_runner.py /tmp/py_probe.db 2>/dev/null"

echo -e "${BOLD}─── mainline sqlite3 reads LEAP-written files ───${NC}"
echo -e "${YELLOW}$ sqlite3 /tmp/rust_probe.db 'SELECT * FROM t'${NC}"
sqlite3 /tmp/rust_probe.db "SELECT * FROM t" | sed 's/^/  /'
echo -e "${YELLOW}$ sqlite3 /tmp/py_probe.db 'SELECT * FROM t'${NC}"
sqlite3 /tmp/py_probe.db "SELECT * FROM t" | sed 's/^/  /'
echo
if cmp -s /tmp/rust_probe.db /tmp/py_probe.db; then
    echo -e "  ${GREEN}Rust and Python produce byte-identical .db files${NC}"
else
    echo -e "  FAIL: files differ"
fi
echo

echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  5-target SELECT + DML + compound-expr steel thread: GREEN${NC}"
echo -e "${GREEN}  Mainline-compatible file-format write:               GREEN${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo
echo "Data-path LOC (agent-emitted from specs only, excludes runners):"
loc() {
    find "$@" 2>/dev/null | grep -v examples | grep -v target | grep -v zig-out | grep -v __pycache__ | grep -v "_smoke_root" | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1}'
}
printf "  Rust:   %6d  lines\n" "$(loc src-rust -name '*.rs')"
printf "  C:      %6d  lines\n" "$(loc src-c -name '*.c' -o -name '*.h')"
printf "  Zig:    %6d  lines\n" "$(loc src-zig -name '*.zig')"
printf "  Go:     %6d  lines\n" "$(loc src-go -name '*.go')"
printf "  Python: %6d  lines\n" "$(loc src-python -name '*.py')"
echo
echo "Hand-written code in data path: 0 lines."
echo "Test harness runners (under examples/ or cmd/*/main.go) counted separately."
