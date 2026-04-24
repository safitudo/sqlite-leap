# sqlite-leap v2 — recursive parts architecture

Status: **proposal, branch `v2-recursive-parts`**. v1 is frozen at
commit `9877a7e` on `main`. This document is the authoritative
contract for v2. If any spec file contradicts this document, this
document wins (v2's test of its own language-neutral discipline).

## Motivation — the v1 structural gap

v1 divided the engine into six top-level parts (tokenizer, parser,
compiler, vdbe, storage, executor). Each part generated one monolithic
file per target. At the end of v1:

- `src-rust/src/compiler.rs` — 19,618 lines
- `src-c/compiler.c` — 17,578 lines
- Both written by ~100 phase-pin additive patches, never cleanly
  regenerated from spec.

The monolith broke three LEAP invariants in practice, even though
tests stayed green:

1. **Regeneration is not atomic.** No sub-agent regenerates 19k lines
   in one round. So every phase pin landed as an additive patch to
   the existing file, making the file a layered sediment — not a
   clean emission from spec.
2. **Hand-edit vs generator-edit is indistinguishable.** A 30-line
   surgical edit in compiler.rs looks identical in git whether an
   agent regenerated it or a human patched it. Discipline was
   enforced by social convention, not by structure.
3. **Cross-target parity drifts silently.** Spec changes that land on
   one target's 17k-line file may take weeks to reach the other
   target's 19k-line file; by then the spec has likely moved again.
   The file size made audits costly.

The Phase 9h hand-edit (`src-rust/src/compiler.rs`, three `.expect()`
panic sites replaced by structured-error returns, 2026-04-21) was
the canary: the fix was small, correct, and spec-pinned, but the
generator could not produce it on a second pass because the spec's
single flat grammar file had grown past an agent's reliable
regeneration envelope. v2 exists to fix that.

## The recursive parts model

A **part** is any directory under the project root that contains a
`master.md`. The model is single-rule and recursive:

```
part-name/
  master.md         # required — contract + recipes + phase pins + front-matter
  schema.json       # optional — typed interface if the part emits structured data
  tests/            # optional — fixtures owned by this part
  parts/            # optional — if this part decomposes further
```

Every directory is a part. Parts may contain `parts/`. There is
**no second-level naming ceremony** — sub-parts are just parts
inside a parent's `parts/` directory. Depth is decided per-part,
not by the framework.

### Leaf vs inner

- **Leaf part** = `parts/` absent or empty. Emits code directly into
  `src-{c,rust}/` via the generator. Owns ~500–1500 lines of
  generated code per target.
- **Inner part** = `parts/` present and non-empty. Composes children.
  Does not emit code of its own beyond module/include glue. Declares
  the interface children must honor.

If an inner part's `master.md` exceeds ~1500 lines of spec content,
or a leaf's spec exceeds ~2000 lines, the part should be split —
either promoted (moved up the tree) or decomposed (its children
grow their own `parts/`). Oversized specs are the anti-pattern this
architecture exists to kill.

### Directory tree

```
sqlite-leap/
├── master.md                # root part — orchestration
├── ARCHITECTURE-v2.md       # this file
├── CLAUDE.md                # agent instructions (v1 content applies)
├── spec/                    # CROSS-CUTTING specs ONLY — see below
│   ├── memory-discipline.spec.md
│   ├── durability.spec.md
│   ├── sqllogictest-runner.spec.md
│   ├── bench-lanes.spec.md
│   ├── fuzz-corpus.spec.md
│   ├── ci-infra.spec.md
│   ├── cli.spec.md
│   └── wasm-ffi.spec.md
├── schema/                  # shared JSON schemas (cross-part contracts)
├── parts/                   # top-level parts
│   ├── tokenizer/           # leaf
│   ├── parser/
│   ├── compiler/
│   ├── vdbe/
│   ├── storage/
│   ├── io-backend/
│   ├── executor/            # leaf
│   └── harness/
├── generators/              # per-target generators — recurse parts/
├── tests/                   # language-neutral test suites
│   ├── sqllogictest/
│   ├── cross-build/
│   ├── fuzz/
│   └── tcl/
├── bench/                   # reproducible benchmark harness
└── src-{c,rust,wasm}/       # GITIGNORED — generated output
```

## Front-matter contract

Every `master.md` begins with YAML front-matter declaring four
things:

```yaml
---
name: compiler/expressions
kind: leaf                    # leaf | inner
inherits:
  - /spec/memory-discipline.spec.md
  - /schema/ast.schema.json
  - /schema/program.schema.json
  - /parts/vdbe/parts/opcodes-expr/master.md
emits:
  c:
    path: src-c/compiler/expressions.c
    headers: [src-c/compiler/expressions.h]
  rust:
    path: src-rust/src/compiler/expressions.rs
---
```

Keys:

- **`name`** — path-like identifier, matches directory position
  under `parts/`. Required. Unique across the tree.
- **`kind`** — `leaf` or `inner`. Required. Must match presence of
  non-empty `parts/` subdirectory. The generator validates.
- **`inherits`** — list of absolute repo-root-relative paths to files
  the generator MUST load into an agent's context before spawning a
  sub-agent scoped to this part. Front-matter-declared so loading is
  machine-mechanical, not prose-trust.
- **`emits`** — per-target output descriptor. Leaf parts declare
  explicit file paths; inner parts may declare none (composition is
  automatic) or declare a wrapper path (e.g. `mod.rs`). Absent
  `emits` on an inner part means "the parent's generator composes
  children automatically with default module glue."

### `inherits:` semantics

When a generator spawns a sub-agent for part `P`:

1. The loader resolves `P.inherits` → list of files.
2. The loader walks `P`'s parent chain, collecting each ancestor's
   `master.md` (implicit inheritance from the enclosing context).
3. Prepends all collected files to the sub-agent's prompt.
4. Invokes the sub-agent with `P/master.md` + `P/schema.json` (if
   present) + `P/tests/` (if present) as the primary input, and
   instructs it to emit code matching `P.emits` for the target
   language.

Parent chain is walked automatically; a part does not need to list
its own ancestors in `inherits:`. Cross-tree references (e.g.
compiler/expressions inheriting from vdbe/opcodes-expr) must be
explicit.

### What goes in `/spec/` vs in a part's `master.md`

`/spec/` holds ONLY cross-cutting specs — constraints that apply to
multiple parts and are owned by no single part. A spec is
cross-cutting if any two of:

- It describes an invariant that must hold in ≥2 unrelated parts
- It describes methodology (benchmark, test, CI), not engine
  behavior
- Removing it from the project removes discipline, not
  functionality

Specs that fail this test belong inside their owning part's
`master.md`. v1's `sql-grammar.spec.md`, `vdbe-opcodes.spec.md`,
`file-format.spec.md`, `wal.spec.md`, `pager-async.spec.md`,
`storage.spec.md`, `io-backend*.spec.md`, and
`vdbe-interpreter.spec.md` all move into their owning parts in v2.

## Composition rules

### Leaf emission

A leaf part's sub-agent produces exactly the files listed in
`emits.<target>`. The sub-agent's context is the concatenation of:

1. Root `master.md` + `ARCHITECTURE-v2.md` + `CLAUDE.md`
2. Every ancestor part's `master.md` (walked from root → parent)
3. All files in `inherits:`
4. The part's own `master.md`, `schema.json`, `tests/`

The sub-agent must not read or reference any other file. This is
the discipline boundary — a leaf regeneration is atomic and
reproducible with a fixed input set.

### Inner composition

An inner part's generator runs one of two protocols:

**Default (no `emits`):** the parent assumes its children emit
sibling modules. For Rust, it emits a `mod.rs` that `pub mod`s each
child by its directory name. For C, it emits a header aggregating
child headers and a build-manifest fragment listing child .c files.
No spec content, no logic.

**Explicit (with `emits`):** the parent declares a wrapper. The
wrapper's sub-agent receives the children's `emits` paths as
context and produces the wrapper (e.g. a dispatch table or a public
facade). The wrapper sub-agent does NOT receive children's
`master.md` content — composition is interface-level, not
spec-level. This keeps children hidden from parent regenerations
and vice versa.

### Cross-part communication

Parts communicate exclusively through:

1. **Schemas** (`schema/` at root, or `schema.json` inside a part)
   — typed data contracts.
2. **Inherits-declared references** — one part explicitly inherits
   another's master.md for interface knowledge.
3. **Generated code** — parts that appear together in the final
   build can call each other's emitted symbols. The call surface is
   declared in the callee's `master.md` "Public interface" section.

A part's sub-agent MUST NOT read another part's `master.md` unless
that file appears in its resolved `inherits` chain. Silent reach-
around breaks the regeneration envelope.

## Regeneration envelope

The core v2 invariant: a leaf part is regenerable in one agent round.
"One agent round" means:

- Single sub-agent spawn
- Bounded context (all inputs fit comfortably in one prompt)
- Deterministic output path (`emits.<target>.path`)
- Atomic test pass (the part's own `tests/` + any cross-build
  fixture naming it as primary owner)

If a leaf's regeneration requires two rounds (agent emits partial
output, second agent fills in gaps), the leaf is too big — split it.
If it requires reading another part's source to succeed, its
`inherits:` is incomplete — add the missing reference.

Inner parts don't have a regeneration envelope of their own — they
regenerate by regenerating their children.

## Test ownership

Tests live in two places:

- **Part-owned tests** (`parts/X/tests/`) — fixtures that exercise
  only part X. Owned by X's `master.md` as required behavior. Run
  by the generator immediately after X regenerates.
- **Cross-build tests** (`tests/cross-build/`) — fixtures that
  validate C↔Rust equivalence OR that span multiple parts. Each
  fixture names a primary part in its own front-matter; when that
  part regenerates, its cross-build fixtures run too.

The sqllogictest corpus (`tests/sqllogictest/`) is external ground
truth — ported verbatim from upstream, never owned by a single
part, always runs against a full build.

## Migration policy (v1 → v2)

v1 content migrates into v2 in three shapes:

1. **Cross-cutting v1 specs stay** — `memory-discipline`, `durability`,
   `sqllogictest-runner`, `bench-lanes`, `fuzz-corpus`, `ci-infra`,
   `cli`, `wasm-ffi`.
2. **Part-scoped v1 specs absorb into their part's `master.md`** — no
   new file, content relocates. `sql-grammar.spec.md` shatters
   across parser/parts/* and compiler/parts/*; other part-scoped
   specs each go into a single new home.
3. **Schemas stay** — `schema/` at repo root keeps the shared data
   contracts (AST, Program, Value, etc.). Parts may add their own
   `schema.json` for private contracts.

During the v2 branch lifetime:

- v1 `src-*/` stay gitignored; they remain buildable from v1 spec
  on `main`.
- v2 generators will be authored as part of branch work; they read
  the recursive parts tree, not the v1 flat spec.
- Cross-build equivalence must survive the transition — the 588/622
  PASS-both bar on `main` is the floor for v2 release.

## Open questions (deliberately unresolved)

These are decisions the v2 branch surfaces but does not pre-answer.
Each will land as it becomes concrete:

1. **Sub-part interface language.** When `compiler/statements/select`
   calls `compiler/expressions`, how is the call signature declared
   in the spec so both C and Rust generators produce compatible
   function signatures? Options: JSON Schema for signatures;
   pseudo-code with typed slots; per-target appendix. Defer until
   the first cross-sub-part regeneration hits the problem.
2. **Dependency DAG inside an inner part.** Inner parts declare
   children but not order. When regen order matters (e.g.,
   `expressions` before `select`), how is it declared? Candidate:
   optional `depends_on:` in child front-matter. Defer until
   first collision.
3. **WASM target surface.** v1 built WASM by compiling Rust to
   wasm32. v2 could keep that, or promote `harness/wasm-bridge` to
   its own part, or keep it in `generators/wasm/`. Defer.
4. **Grandchild regeneration.** If `compiler/statements/select/parts/`
   ever gets children, is the regeneration envelope still atomic?
   Current answer: yes, same rules recurse. Revisit if grandchildren
   materialize and the envelope strains.

## Convergence test — what "v2 works" means

v2 is judged on three criteria, in order:

1. **Structural.** Every part has a master.md with conformant
   front-matter. `kind` matches directory shape. No circular
   `inherits`. No part exceeds size limits.
2. **Generator.** A fresh sub-agent scoped to any leaf part, given
   only its resolved context, produces code that compiles and
   passes the part's tests, on both targets.
3. **System.** The full generator run from v2 specs produces
   src-{c,rust}/ trees that pass the upstream sqllogictest corpus at
   ≥ the v1 bar (C 588/622, Rust 620/622, cross-build PASS-both
   588/622).

If criterion 3 fails but criteria 1 and 2 hold, v2 still won — the
regeneration envelope is proven, and missing coverage is a spec-
authoring debt measured in known sub-parts, not a structural bug.

If criterion 2 fails — an agent cannot regenerate a leaf cleanly —
v2 is wrong and the spec author got the sub-part boundary wrong.
Split or merge until criterion 2 holds.
