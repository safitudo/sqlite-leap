#!/usr/bin/env bash
# Download + build baseline SQL engines we compare against.
#
# Default: mainline SQLite from sqlite.org (amalgamation). Pinned version
# so every host builds the same bytes. If a newer version is desired, bump
# SQLITE_YEAR / SQLITE_TARBALL together and commit the pin.
#
# With --turso: additionally clone tursodatabase/turso and `cargo build
# --release` its CLI. Turso is optional because (a) it's a big pull and
# (b) we mark it in the public comparison as "rust-native baseline, built
# from current HEAD" rather than "released version" — commit SHA is
# captured in a sidecar file.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/src"
BIN_DIR="$SCRIPT_DIR/bin"
mkdir -p "$SRC_DIR" "$BIN_DIR"

# Pin: sqlite-amalgamation-3450300 (SQLite 3.45.3, 2024-04-15).
SQLITE_YEAR=2024
SQLITE_TARBALL="sqlite-amalgamation-3450300.zip"
SQLITE_URL="https://sqlite.org/${SQLITE_YEAR}/${SQLITE_TARBALL}"
SQLITE_DIR="$SRC_DIR/sqlite-amalgamation-3450300"

WANT_TURSO=0
for arg in "$@"; do
    case "$arg" in
        --turso) WANT_TURSO=1 ;;
        -h|--help)
            cat <<EOF
Usage: $0 [--turso]

Fetches + builds baselines into bench/baselines/bin/.

Without flags:
    mainline SQLite amalgamation (pinned, see top of script)

--turso:
    ALSO clone tursodatabase/turso and cargo build --release its CLI.
EOF
            exit 0
            ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

# --- mainline SQLite -------------------------------------------------------
if [[ ! -d "$SQLITE_DIR" ]]; then
    echo "[baselines] downloading $SQLITE_URL" >&2
    curl -fsSL -o "$SRC_DIR/$SQLITE_TARBALL" "$SQLITE_URL"
    (cd "$SRC_DIR" && unzip -q "$SQLITE_TARBALL")
fi

CC="${CC:-cc}"
echo "[baselines] building mainline SQLite with $CC -O2" >&2
(cd "$SQLITE_DIR" && \
    "$CC" -O2 -DSQLITE_THREADSAFE=0 -DSQLITE_OMIT_LOAD_EXTENSION \
        sqlite3.c shell.c -o "$BIN_DIR/sqlite-mainline" \
        -lpthread -lm 2>/dev/null || \
    "$CC" -O2 -DSQLITE_THREADSAFE=0 -DSQLITE_OMIT_LOAD_EXTENSION \
        sqlite3.c shell.c -o "$BIN_DIR/sqlite-mainline" \
        -lpthread -ldl -lm)

# Strip for fair size comparison with our stripped-release binaries.
strip "$BIN_DIR/sqlite-mainline" 2>/dev/null || true

echo "[baselines] built $BIN_DIR/sqlite-mainline ($(stat -f "%z" "$BIN_DIR/sqlite-mainline" 2>/dev/null || stat -c "%s" "$BIN_DIR/sqlite-mainline") bytes)" >&2

# --- turso (optional) ------------------------------------------------------
# Pin: v0.5.3 (latest non-prerelease as of 2026-04-20), commit
#   09c149a776b5140bfff3e3dee1dc786177d2615a
# CLI binary name at this tag: `tursodb` (see cli/Cargo.toml default-run).
TURSO_TAG="v0.5.3"
TURSO_COMMIT="09c149a776b5140bfff3e3dee1dc786177d2615a"

if [[ "$WANT_TURSO" -eq 1 ]]; then
    if ! command -v cargo >/dev/null 2>&1; then
        echo "[baselines] --turso requested but cargo not on PATH — skipping" >&2
    else
        TURSO_DIR="$SRC_DIR/turso"
        if [[ ! -d "$TURSO_DIR" ]]; then
            echo "[baselines] cloning tursodatabase/turso @ $TURSO_TAG" >&2
            git clone --depth 1 --branch "$TURSO_TAG" \
                https://github.com/tursodatabase/turso.git "$TURSO_DIR"
        else
            # Ensure the existing clone is parked on the pinned tag.
            echo "[baselines] ensuring turso clone at $TURSO_TAG" >&2
            (cd "$TURSO_DIR" && \
                git fetch --depth 1 origin "refs/tags/${TURSO_TAG}:refs/tags/${TURSO_TAG}" && \
                git checkout --quiet "$TURSO_TAG")
        fi
        (cd "$TURSO_DIR" && git rev-parse HEAD > "$BIN_DIR/turso.commit")
        actual_commit="$(cat "$BIN_DIR/turso.commit")"
        if [[ "$actual_commit" != "$TURSO_COMMIT" ]]; then
            echo "[baselines] WARN: turso commit $actual_commit != pinned $TURSO_COMMIT" >&2
        fi
        echo "$TURSO_TAG" > "$BIN_DIR/turso.version"
        echo "[baselines] cargo build --release --bin tursodb (turso $TURSO_TAG)" >&2
        # Build only the CLI binary (workspace has 40+ members; building
        # everything is wasteful for a baseline). Use an out-of-tree target
        # dir so the clone stays clean.
        TURSO_TARGET_DIR="${TURSO_TARGET_DIR:-$TURSO_DIR/target}"
        (cd "$TURSO_DIR" && CARGO_TARGET_DIR="$TURSO_TARGET_DIR" \
            cargo build --release --bin tursodb)

        # v0.5.3 ships the CLI as `tursodb`. Probe for historical names too.
        for name in tursodb limbo turso; do
            if [[ -x "$TURSO_TARGET_DIR/release/$name" ]]; then
                cp -f "$TURSO_TARGET_DIR/release/$name" "$BIN_DIR/turso"
                strip "$BIN_DIR/turso" 2>/dev/null || true
                echo "[baselines] installed $BIN_DIR/turso (from $name, $(stat -f "%z" "$BIN_DIR/turso" 2>/dev/null || stat -c "%s" "$BIN_DIR/turso") bytes)" >&2
                break
            fi
        done
        if [[ ! -x "$BIN_DIR/turso" ]]; then
            echo "[baselines] WARN: could not find a turso CLI binary under $TURSO_TARGET_DIR/release/" >&2
        fi
    fi
fi

echo "[baselines] done" >&2
