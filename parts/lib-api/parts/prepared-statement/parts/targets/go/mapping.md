---
name: prepared-statement/targets/go
kind: mapping
inherits:
  - /parts/targets/go/mapping.md
---

# Go mapping — prepared-statement

## Toolchain

- **Go**: 1.23.4.
- **stdlib**: no third-party deps.

## Type rendering

| Shape | Go |
|---|---|
| `PreparedStatement` | `type PreparedStatement struct { Program Program; Arity uint32 }` |
| `BoundParams` | `type BoundParams struct { Values []Value }` |
| `StepResult` | `type StepResult struct { Tag StepResultTag; Error *RuntimeCondition }` with `StepResultTag` enum (`StepRow`, `StepDone`, `StepError`) |
| `PrepareError` | `type PrepareError struct { Tag PrepareErrorTag; Parse *ParseError; Compile *CompileError }` |
| `BindError` | `type BindError struct { Slot uint32; Arity uint32 }` (implements `error`) |

## Function signatures

```go
func Prepare(db *Database, sql string) (*PreparedStatement, *PrepareError)

func Bind(stmt *PreparedStatement, params *BoundParams,
          slot uint32, value Value) *BindError

func Step(stmt *PreparedStatement, params *BoundParams, db *Database) StepResult

func Reset(stmt *PreparedStatement)

func NewBoundParams(arity uint32) *BoundParams
```

## Notes

- Go's idiomatic error pairing is `(value, error)`; the lib-api
  follows the codebase convention of returning `*ErrorType` (nil ==
  no error) so the call sites stay consistent with sibling parts
  (mem-store, btree).
- Garbage collector owns slice backing; no manual `free`.
