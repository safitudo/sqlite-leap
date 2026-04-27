---
name: predicate-pushdown/targets/c
kind: mapping
inherits:
  - /parts/targets/c/mapping.md
---

# C mapping — predicate-pushdown

## Toolchain

- **C standard**: C11.
- **Compiler**: gcc 11.4 / clang 14+; Apple clang on macOS arm64.
- **stdlib**: `<stdbool.h>`, `<stddef.h>`, `<stdint.h>`, `<stdlib.h>`,
  `<string.h>`. No POSIX-only APIs.

If the toolchain pin shifts (any major libc change in `strncasecmp` /
`memcmp` semantics), regenerate.

## Type rendering

| Shape | C |
|---|---|
| `PointFetchOk` | `typedef struct { opcode_t* opcodes; size_t opcodes_len; uint32_t num_registers; uint32_t num_cursors; uint32_t num_aggregates; uint32_t result_count; uint32_t opcode_template_kind; } point_fetch_ok_t;` |
| `Option<PointFetchOk>` | `typedef struct { bool has_value; point_fetch_ok_t value; } point_fetch_ok_opt_t;` |
| `PushdownTrigger` | `typedef enum { PUSHDOWN_TRIGGER_ROWID_POINT_FETCH = 0 } pushdown_trigger_t;` |
| `EmitOp` | `typedef enum { EMIT_OP_OPEN_READ_CURSOR = 0, EMIT_OP_KEY_EXPR_COMPILE, EMIT_OP_SEEK_ROWID_BY_KEY, EMIT_OP_COLUMN_READ_ALL, EMIT_OP_PROJECTION_COMPILE, EMIT_OP_EMIT_RESULT_ROW, EMIT_OP_GOTO_HALT, EMIT_OP_BIND_MISS_LABEL, EMIT_OP_CLOSE_CURSOR, EMIT_OP_BIND_HALT_LABEL, EMIT_OP_EMIT_HALT } emit_op_t;` |
| `RowidPointFetchTemplate` | `typedef struct { pushdown_trigger_t trigger; emit_op_t* steps; size_t steps_len; } rowid_point_fetch_template_t;` |

## Function signatures

```c
typedef enum { PF_OK, PF_ERR } pf_status_t;

pf_status_t try_compile_point_fetch(
    const select_stmt_t* stmt,
    const table_schema_t* schema,
    point_fetch_ok_opt_t* out_opt,
    compile_error_t* out_err);

const index_spec_t* find_rowid_index(const table_schema_t* schema);

bool is_row_independent(const expr_t* expr);
```

`out_opt->has_value = false` signals the caller to fall through.

## Notes

- Memory: `opcodes` and `steps` are heap-allocated by the emitter;
  the caller owns them and frees via the existing program-disposal
  path in `src-c/compiler/select_compile.h`. No malloc-as-spec — the
  spec describes ownership in §"Generation scope" (caller frees).
- The C target represents `Option<&IndexSpec>` as a nullable raw
  pointer (`const index_spec_t*` returning `NULL` for None). This is
  the canonical C rendering; not a spec leak.
- `find_rowid_index` returns a pointer into the schema's `indexes`
  array; lifetime is the schema's. Caller must not free.
