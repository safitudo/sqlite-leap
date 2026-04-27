---
name: prepared-statement/targets/c
kind: mapping
inherits:
  - /parts/targets/c/mapping.md
---

# C mapping — prepared-statement

## Toolchain

- **C standard**: C11.
- **Compiler**: gcc 11.4 / clang 14+.
- **stdlib**: `<stdbool.h>`, `<stddef.h>`, `<stdint.h>`, `<stdlib.h>`,
  `<string.h>`.

## Type rendering

| Shape | C |
|---|---|
| `PreparedStatement` | `typedef struct { program_t program; uint32_t arity; } prepared_statement_t;` |
| `BoundParams` | `typedef struct { value_t* values; uint32_t values_len; } bound_params_t;` |
| `StepResult` | `typedef struct { enum { STEP_RESULT_ROW, STEP_RESULT_DONE, STEP_RESULT_ERROR } tag; runtime_condition_t error; } step_result_t;` |
| `PrepareError` | `typedef struct { enum { PREPARE_ERROR_PARSE, PREPARE_ERROR_COMPILE } tag; parse_error_t parse; compile_error_t compile; } prepare_error_t;` |
| `BindError` | `typedef struct { uint32_t slot; uint32_t arity; } bind_error_t;` (single-case; tag implicit) |

## Function signatures

```c
typedef enum { OK, ERR } status_t;

status_t prepare(const database_t* db, const char* sql,
                 prepared_statement_t* out_stmt, prepare_error_t* out_err);

status_t bind(const prepared_statement_t* stmt, bound_params_t* params,
              uint32_t slot, value_t value, bind_error_t* out_err);

step_result_t step(const prepared_statement_t* stmt,
                   const bound_params_t* params, const database_t* db);

void reset(prepared_statement_t* stmt);

bound_params_t bound_params_for_arity(uint32_t arity);
void bound_params_free(bound_params_t* p);
```

## Notes

- Memory: `BoundParams.values` is heap-allocated; caller frees via
  `bound_params_free`. `value_t` payloads (Text/Blob) are owned by
  the slot and freed when the slot is overwritten or the params
  vector is freed. No malloc-as-spec — the spec describes ownership
  in §"Generation scope"; the C target picks malloc/free as the
  idiomatic implementation.
- The `prepared_statement_t.program` field owns the opcode list and
  any string payloads inside opcodes (matches the existing C
  Program-disposal convention).
