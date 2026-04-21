# CI infrastructure — language-neutral spec

## Why this exists

The stunt's credibility depends on reproducible benchmark numbers on Linux + macOS, and on "zero-warning clean build" as a Done criterion. Without a CI substrate, we are hand-publishing numbers. This spec defines the CI + sanitizer substrate language-neutrally — the same lanes run the C build, the Rust build, and (for perf-publication) a Linux-hosted benchmark harness.

## Platforms

1. **Linux x86_64** — canonical perf-publication platform. Ubuntu 24.04 LTS (glibc 2.39). Kernel ≥ 6.8 (required for io_uring features enumerated in `io-backend.spec.md` § Phase 5b).
2. **macOS arm64 (Apple Silicon)** — developer-loop platform. macOS 15+ (Darwin 24+). Used for correctness runs; benchmark numbers on macOS are INFORMATIONAL, not published.

Windows is not a target in v1.

## Lanes

Each lane is a reproducible pipeline that can be run locally via `make ci-<lane>` and runs automatically in CI. Local and CI runs must produce identical verdicts (no environment-specific variance).

### Lane 1: `build-c`

1. Invoke the C generator (see `generators/c/`) to produce `src-c/`.
2. Compile `src-c/` with `clang -O2 -Wall -Wextra -Werror -pedantic -std=c17`.
3. Also compile under `clang -O0 -g -fsanitize=address,undefined` (ASan + UBSan).
4. Also compile under `clang -O0 -g -fsanitize=memory -fsanitize-memory-track-origins` (MSan) — Linux only; Apple clang does not ship MSan.

Pass criteria: zero warnings, zero errors, sanitizer binaries produced.

### Lane 2: `build-rust`

1. Invoke the Rust generator to produce `src-rust/`.
2. `cargo build --release` — release binaries.
3. `cargo build` — debug binaries.
4. `cargo clippy -- -D warnings` — every clippy lint at error level.
5. `cargo fmt --check` — rustfmt-canonical formatting.

Pass criteria: zero warnings, zero clippy findings, formatting clean.

### Lane 3: `build-wasm`

1. Invoke the WASM generator (thin wrapper over Rust target).
2. `cargo build --release --target wasm32-unknown-unknown`.
3. `wasm-opt -O3` the resulting `.wasm`.
4. `wasm2wat` and verify imports are limited to the FFI surface declared in `spec/wasm-ffi.spec.md`.

Pass criteria: `.wasm` produced, size ≤ declared budget (see `bench/` spec once authored), FFI surface matches declaration.

### Lane 4: `test-cross-build-c`

Runs every `tests/cross-build/phase*.json` fixture through the C build's phase-specific harness binaries.

Pass criteria: `failed=0` on every harness run.

### Lane 5: `test-cross-build-rust`

Same as Lane 4 but against the Rust build.

Pass criteria: identical — and importantly, the per-fixture output (where the harness emits result bytes) must be byte-identical to Lane 4's output. Byte-identical cross-build output is the core LEAP invariant.

### Lane 6: `test-sqllogictest`

Runs the sqllogictest runner (see `sqllogictest-runner.spec.md`) against both the C and Rust builds, over the full in-repo `.test` suite.

Pass criteria: combined pass rate ≥ mainline SQLite's pass rate on the SAME files (measured by the reference harness in the same run). Reference baseline captured once per mainline-version-bump.

### Lane 7: `test-fuzz-smoke`

Runs each of the four fuzz harnesses (`parse-only`, `exec-only`, `roundtrip-db`, `roundtrip-sql`) for a short duration (5 minutes each) against the curated seed corpus. Long campaigns (24+ hours) run out-of-band on a fuzz-host and push any new findings back into the corpus as regression inputs.

Pass criteria: zero crashes, zero hangs, zero roundtrip diffs over the curated corpus.

### Lane 8: `bench-publish` (Linux-only)

Runs the six benchmark lanes (cold-start, parse, SELECT, INSERT, binary-size, memory-footprint) against:

- Current leap build (C, Rust, WASM as applicable)
- Mainline SQLite at the currently-pinned version (as recorded in `bench/baselines.json`)
- Turso at currently-pinned version

Produces CSV + graphs into `bench/results/<YYYY-MM-DD-<git-sha>>/`. Does NOT gate CI (benchmark variance makes pass/fail infeasible in CI) — instead flags "regression suspected" if any lane is > 10% worse than the last green run.

Pass criteria: artifact produced, no lane's regression flag triggered.

### Lane 9: `bench-compare-cross-build`

Runs the six benchmarks on the C and Rust builds side-by-side. Produces a delta report. Gating criterion (soft): neither build is more than 2× slower than the other on any lane. Hard-gated: both builds complete all benchmarks without error.

## Sanitizer discipline

The C build is tested under:

- **ASan + UBSan** (Linux + macOS): every CI run.
- **MSan** (Linux only): every CI run.
- **TSan** (Linux only): Phase 4b / 5b onward — not useful for single-threaded phases.
- **Valgrind** (Linux only): release-candidate runs only, not every CI run. Slow; ASan covers most of the same ground.

Sanitizer findings are treated identically to compiler warnings: zero tolerance. A finding either represents a real defect (fix it) or a deliberate pattern the sanitizer misinterprets (narrowly suppress with a documented rationale; never blanket-suppress).

The Rust build relies on the compiler's own guarantees (borrow checker + panic-on-UB) and clippy for style; no external sanitizer substrate in v1. `cargo +nightly miri` may be added later for unsafe blocks.

## Reproducibility

Every CI run records:

- The exact toolchain version (`clang --version`, `rustc --version`, `wasm-opt --version`).
- The exact seed corpus content-hash for Lane 7.
- The exact mainline-SQLite version for Lanes 6, 7, 8.
- The exact Turso version for Lane 8.
- The full environment variable set.
- The git SHA of the leap commit.

Locally, `make ci-<lane>` reads the same pinned versions from `tools/toolchain.lock` and refuses to run if the local tools drift. This is what "reproducible" means: two developers running `make ci-bench-publish` on comparable hardware produce numerically comparable outputs.

## Docker / dev-container

A single `Dockerfile` at repo root produces a container image that:

- Has every toolchain version pinned in `tools/toolchain.lock` installed.
- Runs as a non-root user with the repo bind-mounted at `/workspace`.
- Exposes every `make ci-<lane>` target.

This is the canonical way to reproduce a Linux CI run from a macOS dev loop. `docker compose run --rm ci make ci-bench-publish` on a Mac produces the same numbers as the Linux CI (modulo hardware; the point is toolchain reproducibility, not hardware reproducibility).

## CI orchestration (non-normative note)

Implementation of the orchestrator (GitHub Actions workflow, self-hosted runner, etc.) is NOT specified here. The spec defines the lanes; the orchestrator wires them to triggers (push, PR, nightly cron). Choice of orchestrator is ops, not architecture.

## Non-goals

- Multi-arch Linux (ARM Linux, POWER, RISC-V). v1 is x86_64 Linux + arm64 macOS only. Adding arches later is a matter of adding CI lanes; no spec surface to change.
- Code coverage targeting. Useful eventually but not gating in v1.
- Mutation-testing coverage metrics. Adds signal but not a ship-gate in v1.
