# sqlite-leap

A LEAP project. The flagship stunt: rewrite SQLite from a language-neutral spec that generates **both C and Rust** implementations. WASM via the Rust target is a third build. One spec, two languages, six benchmarks, all green.

**Stunt plan (source of truth for scope):** `L4-inbox/2026-04-17-stunt-sqlite.md` in the user's Obsidian vault (accessible via the `leapfrog-vault` / `mcpvault` MCP servers). Always read it before making scope decisions.

## You are operating in a LEAP project

LEAP = **LLM Engineered Application Pattern**. Code is a commodity. Guardrails (tests, schemas, prompts) are the product. Full methodology: https://github.com/safitudo/leap (read `MANIFESTO.md`, `SPEC.md`, `AGENTS.md` there if you need depth).

Condensed:

- **Prompts** describe intent. Declarative, disposable.
- **Schemas** are contracts. They ARE the architecture.
- **Tests** specify correctness. Human-authored. Most valuable artifact.
- **Code** is generated output. Lives in `src-*/`. Gitignored.

Guardrails hierarchy (most → least valuable): tests → schemas → prompts.
If a test contradicts a prompt, **the test wins**.

## What makes sqlite-leap different from standard LEAP

Standard LEAP targets one language per project. sqlite-leap targets **three builds from one spec**:

1. **C** — competes with mainline SQLite on its own turf (binary size, perf, deployability)
2. **Rust** — competes with Turso's hand-coded Rust rewrite
3. **WASM** — via the Rust target (`wasm32-unknown-unknown`), competes with `sql.js` / `sqlite-wasm`

This is the core claim: **Turso has one spec (their Rust code). We have a language-neutral spec that produces equivalent implementations in multiple languages, same tests pass on all.** That is the flex Turso structurally cannot match.

**Hardest discipline of the project:** specs must be strictly language-neutral. If a spec leaks a C idiom or a Rust idiom, the other build breaks. First time an idiom leaks = hardest failure mode to recover from.

## Directory layout

```
sqlite-leap/
├── CLAUDE.md                   # this file
├── master.md                   # REQUIRED — root orchestration prompt
├── spec/                       # language-neutral specs (Markdown + pseudo-code, grammars, state machines, opcode tables, page layouts)
│   ├── sql-grammar.spec.md
│   ├── vdbe-opcodes.spec.md
│   ├── file-format.spec.md
│   ├── pager.spec.md
│   ├── io-backend.spec.md
│   └── builtins.spec.md
├── schema/                     # neutral type definitions (JSON Schema + notes): AST nodes, opcode payloads, page layouts, planner IR, WAL frame headers
├── parts/                      # one folder per component (per LEAP spec)
│   └── {name}/
│       ├── master.md
│       └── schema.*
├── tests/                      # behavioral tests; language-neutral harness
│   ├── sqllogictest/           # ported verbatim from upstream
│   ├── tcl/                    # ported SQLite public tcl suite
│   ├── fuzz/                   # AFL-generated; results must match mainline byte-for-byte on deterministic ops
│   └── cross-build/            # C vs Rust equivalence: same query → identical results
├── generators/                 # one subdirectory per language target; invokes LEAP generation
│   ├── c/
│   ├── rust/
│   └── wasm/                   # thin wrapper: compiles the Rust generation to wasm32
├── bench/                      # reproducible harness for all 6 lanes
├── src-c/                      # GITIGNORED — generated C implementation
├── src-rust/                   # GITIGNORED — generated Rust implementation
└── src-wasm/                   # GITIGNORED — WASM artifact (built from src-rust)
```

`_original/` may temporarily exist during rewrite-mode setup (extracting test fixtures, porting sqllogictest). **Must not be read during code generation.** See "DO NOT CHEAT" below.

## DO NOT CHEAT — sqlite-leap specifics

The whole point of LEAP is that AI generates from specs + schemas + tests. Copying existing SQLite or Turso code invalidates the proof and kills the project's value.

**Forbidden sources when generating into `src-c/`, `src-rust/`, or `src-wasm/`:**

- ❌ Mainline SQLite source (`sqlite.c`, amalgamation, official repo at sqlite.org, mirror at github.com/sqlite/sqlite)
- ❌ Turso / Limbo source (github.com/tursodatabase/turso, previously `limbo`)
- ❌ Other SQLite-compatible implementations (sql.js, better-sqlite3, rusqlite, sqlx internals, etc.)
- ❌ `_original/` if present (it's the user's reference, NOT yours, during generation)
- ❌ Web search / fetch for implementation details
- ❌ Porting, translating, or "inspired by" the above

**Allowed inputs for generation:**

- ✅ `master.md`, `spec/`, `schema/`, `parts/`, `tests/` in this repo
- ✅ SQLite's **published file-format documentation** (sqlite.org/fileformat2.html, sqlite.org/lang.html) — these are specs, not implementation
- ✅ Published SQL standards, published `sqllogictest` format
- ✅ Language standard libraries (C stdlib, Rust std/core)
- ✅ Your own knowledge of how to implement a database engine from scratch

**Note on specs vs implementation:** SQLite's file format is a published specification and a design constraint — you can and must consult it to ensure bidirectional file-format compatibility. SQLite's *source code* is off-limits. The distinction matters: the file-format doc describes the frozen wire contract; the source code describes one implementation of it.

**If a spec is ambiguous:** make your best guess from the tests. If tests don't disambiguate, ask the user. Never resolve ambiguity by reading mainline SQLite.

## Dual-target spec discipline (the hardest rule)

Every file in `spec/` and `schema/` must be language-neutral. Concretely:

- **No Rust idioms.** No `Result<T, E>`, no lifetimes, no `Option<T>`, no traits-as-nouns, no `impl` blocks. Describe errors as named conditions; describe optionality as "present or absent."
- **No C idioms.** No raw pointer arithmetic in prose, no `void*`, no `malloc`/`free` mentions as part of the contract, no struct-field-offset-as-spec.
- **Express data shapes as abstract records.** Use JSON Schema for schemas; use English + pseudo-code for spec semantics.
- **Express control flow as state machines or pseudo-code**, not as functions with a specific calling convention.
- **Express errors as named conditions** ("raise `INVALID_OPCODE` if X") — each generator maps that to idiomatic error handling in its target language.

When a spec change is needed, ask: *can both a C generator and a Rust generator implement this without either language feeling forced?* If the answer is no, the spec is leaking. Fix the spec before fixing the generators.

## The six benchmark lanes (public commitments)

We publicly commit to beating mainline SQLite on all six. Match or beat Turso on every lane.

| # | Lane | Mainline baseline | Turso | LEAP-SQLite target |
|---|------|-------------------|-------|--------------------|
| 1 | Cold start (`open` → first query ready) | 130μs (wide schema: seconds) | 40μs | ≤ Turso, ≥ 4× SQLite |
| 2 | Parse speed | Lemon-generated | ~parity | Beat SQLite (spec-gen DFA) |
| 3 | In-memory SELECT | VDBE dispatch | ~20% faster | Beat both |
| 4 | INSERT throughput (WAL, single writer) | sync I/O | async (io_uring) | ≥ Turso |
| 5 | Binary size (core, no extensions) | ~600KB | Rust overhead | Beat SQLite (C build) |
| 6 | Memory footprint (RSS idle + small DB open) | lean | — | Beat SQLite |

Publication bar: reproducible harness, Linux x86_64 + macOS arm64 numbers, graphs + raw CSV in repo.

## Scope — v1

**In:**

- SQL parser (tokenizer + grammar → AST)
- Bytecode compiler (AST → VDBE-equivalent opcodes)
- VDBE interpreter
- B-tree page manager, mainline-SQLite on-disk format compatible
- Pager + WAL
- Async I/O backend (io_uring on Linux, kqueue on BSD/macOS)
- Core SQL: SELECT / INSERT / UPDATE / DELETE, JOINs, subqueries, CTEs, aggregates, transactions, indexes
- Bidirectional file-format compatibility (LEAP-SQLite reads mainline DBs, mainline reads LEAP-SQLite DBs, zero corruption)
- Two implementations from one spec: C and Rust
- WASM build via Rust

**Deferred to follow-up stunts:** FTS5, R-tree, JSON1 beyond minimal, session/changeset, encryption, shell ornaments beyond core.

**Non-goals:** feature parity with every corner of the SQLite CLI, beating Turso on every axis (different product).

## "Done" means

1. `sqllogictest` pass rate ≥ mainline SQLite's own pass rate on the same suite, on **both** C and Rust builds.
2. Reads/writes databases produced by mainline SQLite with zero corruption across fuzz corpus, both builds.
3. Cross-build equivalence: C and Rust builds produce identical results on the full test corpus.
4. All 6 benchmark lanes beating mainline, reproducible harness, Linux + macOS numbers.
5. Clean build on macOS arm64 + Linux x86_64, zero warnings.
6. WASM build passing I/O-constrained `sqllogictest` subset and beating `sql.js` on parse + SELECT.

## Current status — pre-commitment prototype first

Before committing to 150k LOC × 2, validate the dual-target spec discipline on a minimum slice:

- Parser + simplest SELECT against in-memory B-tree
- Spec written strictly language-neutral
- Both C and Rust generated from the same spec
- Ported test subset passing on both

If the prototype exposes a spec pattern that doesn't stay language-neutral cleanly, surface it and reshape the approach before scaling.

## Working norms

- **Read the stunt plan before scoping anything** (`L4-inbox/2026-04-17-stunt-sqlite.md` in the vault).
- **Specs first, schemas second, tests third, code never** (it's generated).
- **Never write code into `src-c/`, `src-rust/`, or `src-wasm/` manually.** Those are generator output.
- **When tests fail:** first ask if the spec was ambiguous. Fix the spec, regenerate, not the code directly.
- **Mac-native dev is fine for daily loop**, but benchmark claims require Linux cross-validation before publication.
- **Reputation asymmetry matters.** SQLite has a "bug-free" reputation. Ship as "compatibility implementation, not production drop-in" until confidence earned.
