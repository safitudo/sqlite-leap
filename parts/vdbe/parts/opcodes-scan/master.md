---
name: vdbe/opcodes-scan
kind: leaf
inherits:
  - /schema/opcode.schema.json
  - /parts/storage/master.md
  - /parts/vdbe/parts/opcodes-rows/master.md
emits:
  c: { path: src-c/vdbe/opcodes_scan.c, headers: [src-c/vdbe/opcodes_scan.h] }
  rust: { path: src-rust/src/vdbe/opcodes_scan.rs }
---

# Part: vdbe/opcodes-scan

Index-driven scan opcodes. The non-index scan is just
`Rewind`+`Next` from `parts/opcodes-rows/`. This sub-part owns the
index-seek primitives.

## Opcodes owned here

| Name | Semantics |
|---|---|
| `OpenIdxRead(cursor, index_name)` | Open a read cursor on an index. |
| `SeekGE(cursor, key_reg, jump_if_miss)` | Position cursor at the smallest key ≥ `regs[key_reg]`. Jump if no such key. |
| `SeekGT(cursor, key_reg, jump_if_miss)` | Strict greater-than variant. |
| `SeekLE(cursor, key_reg, jump_if_miss)` | Smallest key ≤. |
| `SeekLT(cursor, key_reg, jump_if_miss)` | Strict less-than. |
| `IdxNext(cursor, jump_if_eof)` | Advance index cursor; jump on EOF. |
| `IdxRowid(cursor, dest_reg)` | Read the rowid pointed to by the current index entry. |

## Phase pins

- **Phase 9d** — range + ORDER BY via index + multi-col WHERE +
  index splits.
- **Phase 9f** — PRIMARY KEY auto-index + DROP INDEX.
- **Phase 6bb** — ASC/DESC in CREATE INDEX affects scan direction.
- **#129** — C planner index utilization (compiler responsibility,
  opcode-scan is the execution primitive).

## Regeneration envelope

- Target leaf size: 300–500 lines per target.
- Spec < 100 lines.
