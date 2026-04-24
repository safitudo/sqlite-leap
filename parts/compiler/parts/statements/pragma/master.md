---
name: compiler/statements/pragma
kind: leaf
inherits:
  - /parts/storage/master.md
emits:
  c: { path: src-c/compiler/statements/pragma.c, headers: [src-c/compiler/statements/pragma.h] }
  rust: { path: src-rust/src/compiler/statements/pragma.rs }
---

# Part: compiler/statements/pragma

Compiles `PRAGMA name [= value] | (arg)`. Recognizes the v2 core
subset; unknown pragmas are silently no-op (mainline-compatible).

## Supported pragmas (Phase 6aw)

| Pragma | Semantics |
|---|---|
| `journal_mode [= ... ]` | Getter returns `wal`/`memory`. Setter accepts `WAL`, `MEMORY`, other values rejected silently. |
| `synchronous [= ... ]` | Getter returns integer (0=OFF, 1=NORMAL, 2=FULL). Setter accepts those values. |
| `foreign_keys` | Getter/setter boolean (advisory — FK enforcement out of scope). |
| `table_info(name)` | Returns one row per column with `{cid, name, type, notnull, dflt_value, pk}`. |
| `index_list(table)` | Returns rows `{seq, name, unique, origin, partial}`. |
| `page_size` | Fixed at 4096 in v2. Setter is no-op. |
| `user_version [= N]` | Integer stored in header. |
| `application_id [= N]` | Integer stored in header. |

Unknown pragma → emit a zero-row empty-columns program, no error.

## Phase pins

- **Phase 6aw** — PRAGMA core subset.

## Regeneration envelope

- Target leaf size: 300–500 lines per target.
- Spec < 100 lines.
