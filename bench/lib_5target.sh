#!/usr/bin/env bash
# Common helpers for the 5-target lane scripts (Lanes 1, 3, 6).
#
# Sourced by bench/cold_start_5target.sh, select_throughput_5target.sh,
# memory_footprint_5target.sh.
#
# Each lane script defines fixture paths, then calls run_target /
# run_mainline. The helpers shell out to /usr/bin/time -lp and parse
# wallclock + maximum-resident-set-size out of its output.
#
# macOS arm64 only — `/usr/bin/time -lp` line format differs on Linux.

set -euo pipefail

REPO_ROOT_LIB="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# Paths to the five target SLT runners.
RUST_SLT="$REPO_ROOT_LIB/src-rust/target/release/examples/slt_runner"
C_SLT="$REPO_ROOT_LIB/src-c/build/slt_runner"
ZIG_SLT="$REPO_ROOT_LIB/src-zig/zig-out/bin/slt_runner"
PY_DRIVER="$REPO_ROOT_LIB/tests/sqllogictest/5target_harness/driver_python.py"
GO_SLT_BIN="$REPO_ROOT_LIB/bench/results/.cache/go_slt_runner"

ensure_go_slt() {
    mkdir -p "$(dirname "$GO_SLT_BIN")"
    if [[ ! -x "$GO_SLT_BIN" ]] \
       || [[ "$REPO_ROOT_LIB/src-go/cmd/slt_runner/main.go" -nt "$GO_SLT_BIN" ]]; then
        ( cd "$REPO_ROOT_LIB/src-go" && \
          go build -o "$GO_SLT_BIN" ./cmd/slt_runner ) >&2
    fi
}

# Returns: real_seconds<TAB>peak_rss_bytes
# Args: out-file-for-time, command...
time_run() {
    local timefile="$1"; shift
    /usr/bin/time -lp "$@" >/dev/null 2>"$timefile" || true
    local real rss
    real="$(awk '/^real / {print $2; exit}' "$timefile")"
    rss="$(awk '/maximum resident set size/ {print $1; exit}' "$timefile")"
    if [[ -z "$real" || -z "$rss" ]]; then
        echo "NA	NA"
    else
        echo "$real	$rss"
    fi
}

# Run target SLT runner over a fixture file. Args: target, fixture
run_target() {
    local target="$1" fixture="$2" tmp
    tmp="$(mktemp)"
    case "$target" in
      rust)   time_run "$tmp" "$RUST_SLT"  "$fixture" ;;
      c)      time_run "$tmp" "$C_SLT"     "$fixture" ;;
      zig)    time_run "$tmp" "$ZIG_SLT"   "$fixture" ;;
      go)     time_run "$tmp" "$GO_SLT_BIN" "$fixture" ;;
      python) time_run "$tmp" python3      "$PY_DRIVER" "$fixture" ;;
      *) echo "NA	NA" ;;
    esac
    rm -f "$tmp"
}

# Run mainline sqlite3 over a .sql script (read from stdin).
run_mainline() {
    local sqlfile="$1" tmp
    tmp="$(mktemp)"
    /usr/bin/time -lp /usr/bin/sqlite3 ":memory:" >/dev/null 2>"$tmp" <"$sqlfile" || true
    local real rss
    real="$(awk '/^real / {print $2; exit}' "$tmp")"
    rss="$(awk '/maximum resident set size/ {print $1; exit}' "$tmp")"
    rm -f "$tmp"
    echo "$real	$rss"
}

# Run mainline with inline -cmd argument (cold-start path).
run_mainline_cmd() {
    local sql="$1" tmp
    tmp="$(mktemp)"
    /usr/bin/time -lp /usr/bin/sqlite3 ":memory:" "$sql" >/dev/null 2>"$tmp" || true
    local real rss
    real="$(awk '/^real / {print $2; exit}' "$tmp")"
    rss="$(awk '/maximum resident set size/ {print $1; exit}' "$tmp")"
    rm -f "$tmp"
    echo "$real	$rss"
}

# Median of N independent samples. Args: N, then a function name and
# its args. The function must echo "real<TAB>rss".
median_of() {
    local n="$1"; shift
    local fn="$1"; shift
    local reals=() rsses=() i out r s
    for ((i=0; i<n; i++)); do
        out="$("$fn" "$@")"
        r="${out%%	*}"
        s="${out##*	}"
        reals+=("$r"); rsses+=("$s")
    done
    # median via python
    python3 - "${reals[@]}" -- "${rsses[@]}" <<'PY'
import sys, statistics
args = sys.argv[1:]
sep = args.index("--")
reals = [float(x) for x in args[:sep] if x not in ("NA",)]
rsses = [int(x) for x in args[sep+1:] if x not in ("NA",)]
def med(xs):
    if not xs: return "NA"
    return statistics.median(xs)
mr = med(reals)
ms = med(rsses)
print(f"{mr}\t{int(ms) if ms != 'NA' else 'NA'}")
PY
}

fmt_ratio() {
    # ratio = mainline / leap (so >1.0 means leap is FASTER / LIGHTER)
    # for time / rss
    if [[ "$1" == "NA" || "$2" == "NA" || "$2" == "0" ]]; then
        echo "n/a"
    else
        python3 -c "import sys; a=float(sys.argv[1]); b=float(sys.argv[2]); print(f'{a/b:.2f}x' if b else 'inf')" "$1" "$2"
    fi
}
