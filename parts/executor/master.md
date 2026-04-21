# Part: executor

Top-level pipeline step. Compiles an AST to a VDBE Program and runs it against storage.

## Contract

- **Inputs:**
  - `ast` — an AST node (`schema/ast.schema.json`)
  - `storage_handle` — mutable reference to a Database
- **Output on success:** a Result (`schema/result.schema.json`)
- **Output on failure:** one of the `STORAGE_*` errors, propagated from either the compiler (schema-lookup failures) or the VDBE (storage-op failures during execution).

## Required behaviour (Phase 2b)

The executor MUST implement, at the level of observable behaviour:

```
execute(ast, storage_handle) := vdbe.run(compiler.compile(ast, storage_handle), storage_handle)
```

or an equivalent expression. **Direct AST interpretation — bypassing either the compiler or the VDBE — is explicitly retired in Phase 2b and is a spec-discipline violation.**

Error propagation:

- If `compiler.compile(...)` fails with a `STORAGE_*` condition, `execute` returns that condition unchanged.
- If `vdbe.run(...)` fails with a `STORAGE_*` condition, `execute` returns that condition unchanged.
- The executor does NOT introduce new error names, does NOT wrap errors, and does NOT annotate them.

## Per-AST-kind behaviour

All four AST kinds (`CreateTable`, `Insert`, `SelectLiteral`, `SelectFrom`) flow through the same `compile → run` pipeline. There is no AST-kind-specific branching at the executor level in Phase 2b — all dispatch happens in the compiler (via AST kind) and in the VDBE (via opcode dispatch).

## Required behaviour (continued)

The executor MUST:

- Be a pure function of `(AST, storage_handle)` as far as observable behaviour is concerned. Any internal caching (e.g. memoising compiled programs by AST) is target-defined and not required.
- Preserve the Phase 2a observable semantics (row order, column order, error names + fields) exactly.

The executor MUST NOT:

- Read from or write to storage directly (only via compiler and VDBE)
- Inspect the Program between compile and run for observable purposes (no program-conditional behaviour)
- Introduce any new error names

## Part independence

Depends on:

- The compiler part (`parts/compiler/`)
- The vdbe part (`parts/vdbe/`)
- `schema/ast.schema.json`, `schema/result.schema.json`

Does NOT depend on the tokenizer, parser, or storage directly.

## Output location

Generated code lives in `src-{lang}/executor/`. Exposes exactly one public entry point that accepts `(AST, storage_handle)` and returns a Result or a propagated `STORAGE_*` error.
