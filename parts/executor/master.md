---
name: executor
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /parts/parser/master.md
  - /parts/compiler/master.md
  - /parts/vdbe/master.md
  - /parts/storage/master.md
emits:
  c:
    path: src-c/executor.c
    headers: [src-c/executor.h]
  rust:
    path: src-rust/src/executor.rs
---

# Part: executor

Top-level statement execution driver. The glue that ties parser →
compiler → vdbe → storage into a public `execute_sql(db, sql_text)
-> Results` entry point.

## Public interface

- **Input:** a `Database` handle and a SQL source string (which may
  contain multiple statements separated by `;`).
- **Output on success:** for each statement, either `no_rows`
  (DDL/DML) or a `rows` stream. In a batch, statements execute in
  order; a failure on statement N aborts N+1..end.
- **Output on failure:** the first error encountered, typed by the
  sub-part that raised it. Errors carry their originating condition
  unchanged — no re-wrapping that loses the named kind.

## Responsibilities

1. **Tokenize + parse.** Call `tokenizer::tokenize(sql)` → tokens →
   `parser::parse(tokens)` → `Ast`. Either step may raise a
   `TOKENIZER_*` or `PARSE_ERROR` — return it.
2. **Compile.** Call `compiler::compile(ast, &db)` → `Program` or
   a structured compile error. Return compile errors.
3. **Execute.** Call `vdbe::run(&program, &mut db)`. Consume its
   row stream; emit to caller's result sink.
4. **Transactional boundary.** Recognize `BEGIN` / `COMMIT` /
   `ROLLBACK` and delegate to `Database::begin/commit/rollback`.
   Implicit single-statement transactions wrap DML when no explicit
   transaction is active.
5. **Multi-statement batching.** Split on `;` at the top level
   (respecting string/comment boundaries — the tokenizer does this
   correctly). For each sub-statement, repeat steps 1–3.

## Error handling

Each sub-part raises its own named condition. The executor is a
pass-through: it does NOT rewrap. A caller (e.g., the sqllogictest
harness) examines the condition's `kind` field to classify
expected-fail vs unexpected-crash.

## Regeneration envelope

- Target size: 300–600 lines per target.
- No internal sub-parts; this is a leaf.
- Test ownership: smoke tests for batch parsing + error routing
  live here; per-feature tests live with their owning sub-part.
