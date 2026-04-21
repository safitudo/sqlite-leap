# Linux x86_64 cross-validation bench run — 2026-04-20

Numbers committed alongside this file are produced on Linux x86_64 inside a
Docker image, as required by `CLAUDE.md` ("benchmark claims require Linux
cross-validation before publication") and the external reviewer's action
item #4.

## Image + invocation

- Dockerfile: `bench/Dockerfile.linux-x86`
- Build:
  ```
  docker build --platform=linux/amd64 \
      -f bench/Dockerfile.linux-x86 \
      -t sqlite-leap-bench:linux-amd64 .
  ```
- Run (from repo root on the host):
  ```
  docker run --rm --platform=linux/amd64 \
      -v "$PWD":/repo \
      -e BENCH_DATE="$(date -u +%Y-%m-%d)" \
      sqlite-leap-bench:linux-amd64 \
      bash /repo/bench/run-linux-bench.sh
  ```
- If the Docker credential helper hangs (common on this mac), bypass it
  with a scratch DOCKER_CONFIG:
  ```
  mkdir -p /tmp/docker-no-creds
  echo '{}' > /tmp/docker-no-creds/config.json
  DOCKER_CONFIG=/tmp/docker-no-creds docker build …
  DOCKER_CONFIG=/tmp/docker-no-creds docker run …
  ```

## In-container environment

| thing    | value                                 |
|----------|---------------------------------------|
| kernel   | `Linux c108c2942556 6.6.12-linuxkit #1 SMP Fri Jan 19 08:53:17 UTC 2024 x86_64 GNU/Linux` |
| glibc    | `ldd (Debian GLIBC 2.36-9+deb12u13) 2.36` |
| cc       | `cc (Debian 12.2.0-14+deb12u1) 12.2.0` |
| rustc    | `rustc 1.82.0 (f6e511eec 2024-10-15)` |
| hyperfine| `hyperfine 1.18.0` |
| sqlite3  | `3.40.1 2022-12-28 14:03:47 df5c253c0b3dd24916e4ec7cf77d3db5294cc9fd45ae7b9c5e82ad8197f3alt1` |

## Build outcomes

- src-c build:    OK
- src-rust build: OK
- mainline baseline: OK

### Generator gaps discovered during cross-validation

Both gaps are in the **generators**, not the specs; they don't invalidate
the spec but they block a clean Linux build without the workarounds in
`run-linux-bench.sh`.

1. **C target — generator omits `-lm` on link.** The generated
   `src-c/Makefile` link recipe is `$(CC) $(CFLAGS) $(CORE_OBJS) main.o -o $@`
   with no trailing LDLIBS / `-lm`. On macOS libSystem provides floor /
   round / fmod implicitly; on Linux glibc they live in libm and the link
   fails with `undefined reference to floor/round/fmod`. Workaround: a
   `cc` shim on PATH that appends `-lm` to link invocations. The proper
   fix is in the C-Makefile generator (add `LDLIBS`).

2. **Rust target — `lto = "fat"` + debian 12 linker = LTO bitcode error.**
   Cargo.toml pins `lto = "fat"`, which the bench image's rustc 1.82 +
   ld 2.40 chain rejects with
   `failed to get bitcode from object file for LTO (could not find
   requested section)`. Workaround: set
   `CARGO_PROFILE_RELEASE_LTO=off CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16`
   at build time. The proper fix is either pin a bintuils combo in the
   generator or soften the default.

3. **Bench harness — Python 3.11 f-string, hyperfine 1.18 arg parsing.**
   `bench/lanes/_lib.sh` had a backslash inside f-string expressions
   (banned in py3.11) and passed `--` + multi-arg command to hyperfine
   (which silently drops args after the first). Both fixed in place. The
   fix is portable and applies to every host.

4. **Parallel agent tree race.** When another agent is rebuilding
   `src-c/` or `src-rust/` on the host while the container is running,
   the bind-mounted tree's objects can flip arch mid-build (macOS arm64
   Mach-O appearing during an x86_64 link). The driver defends by
   rsync-ing the repo into `/tmp/sqlite-leap-bench-$$` inside the
   container and building there. Results are written back to
   `/repo/bench/results/`.

## sqllogictest smoke (203 cases)

- C target:    **pass**
- Rust target: **fail**

Corpus: `tests/sqllogictest/smoke` (the committed 203-case set, not the
full 622-case or upstream 6M corpus). Full details in the run log:
`bench/results/2026-04-20-linux-x86_64.log`.

### Rust smoke regression — Linux-specific segfault (action item)

On Linux x86_64, the Rust `sqllogictest` binary **segfaults** during the
smoke pass after completing a handful of tests — reliably, but only when
its stdout+stderr are redirected to a regular file (the form the driver
uses). When running with stdout attached to a TTY the same invocation
prints output up through `02-create-insert-select.test:15` then exits 0
with truncated output. C target passes 203/203 on the same corpus in the
same container.

- This is not reproduced on macOS arm64 (Rust smoke is 203/203 there per
  project memory 2026-04-20).
- Hypothesis: Rust generator's stdout-write path has an unflushed-buffer
  or pointer-aliasing bug that only surfaces under glibc + fully-buffered
  stdout (`stdout not a tty ⇒ \_IOFBF` by default).
- Filed here as a finding, NOT a bench blocker. Lanes 1/5/6 run against
  single-test invocations that don't trip this path.

## Results

Lanes 1, 5, 6 only. Lanes 2/3/4 emit `NA,pending-harness-fix` per the
project memory note on the broken parse/select/insert harness; they'll
populate once the harness-fix agent lands.

### Lane 1 — cold start (seconds, lower = better)

| target | seconds |
|---|---:|
| sqlite-leap-c | 0.025044232 |
| sqlite-leap-rust | 0.032487815 |
| sqlite-mainline | 0.121704597 |

### Lane 5 — binary size (bytes, lower = better)

| target | bytes |
|---|---:|
| sqlite-leap-c | 424536 |
| sqlite-leap-rust | 1346016 |
| sqlite-mainline | 1233632 |

### Lane 6 — memory footprint (peak RSS bytes, lower = better)

| target | bytes |
|---|---:|
| sqlite-leap-c | 5033984 |
| sqlite-leap-rust | 5672960 |
| sqlite-mainline | 6057984 |

## Caveats (READ BEFORE QUOTING NUMBERS)

1. **Emulation slowdown (if host is arm64).** On macOS arm64 hosts this
   container runs under Rosetta/QEMU linux-amd64 emulation. Numbers are
   valid for **correctness cross-validation** (same test passes, same
   binary builds, glibc vs macOS libc doesn't break anything, file sizes
   are real) but the speed lanes (1, 3, 4) have emulation overhead on
   top. The ratios between targets are still directionally meaningful
   because all three targets are emulated equally. Publication numbers
   require a native Linux x86_64 host (GitHub Actions `ubuntu-latest`
   via the `ci-linux` workflow is the canonical source).

2. **Lanes 2/3/4 disabled — project memory 2026-04-20.** The
   parse-speed / in-memory-SELECT / INSERT-throughput lanes feed
   malformed sqllogictest input to the leap binary and therefore measure
   rejection speed, not the real work. Those rows are emitted as
   `NA,pending-harness-fix`. Do NOT cite them. Lanes 1, 5, 6 are valid.

3. **src-c / src-rust are rebuilt fresh in-container.** Host-produced
   binaries (wrong arch) are isolated via rsync into a scratch dir before
   build. If the in-container build fails, the corresponding lane rows
   will be `NA,lane-error`.

4. **Stripped binaries.** Lane 5 (binary size) strips our release
   binaries (via `strip`) and the mainline baseline uses
   `fetch-baselines.sh`'s strip step. Release builds only.

5. **Rust build used `lto=off`.** As noted above, fat LTO didn't work in
   this image's toolchain. This is worth maybe 5–10% on Rust hot paths
   vs. a native host build where fat LTO succeeds. The macOS numbers in
   `2026-04-20-Stanislavs-Mac-Studio-validated.csv` use fat LTO.

## Related files

- CSV:       `bench/results/2026-04-20-linux-x86_64.csv`
- Full log:  `bench/results/2026-04-20-linux-x86_64.log`
- Dockerfile: `bench/Dockerfile.linux-x86`
- Driver:    `bench/run-linux-bench.sh`
- macOS pair: `bench/results/2026-04-20-Stanislavs-Mac-Studio-validated.csv`
