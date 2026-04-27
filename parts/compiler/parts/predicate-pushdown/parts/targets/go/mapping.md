---
name: predicate-pushdown/targets/go
kind: mapping
inherits:
  - /parts/targets/go/mapping.md
---

# Go mapping — predicate-pushdown

## Toolchain

- **Go**: 1.23.4 (matches the rest of the repo).
- **stdlib surfaces**: `strings.EqualFold` for ASCII-case-insensitive
  identifier compare; no third-party deps.

Regenerate if the Go toolchain advances past 1.23.x in a way that
changes `strings.EqualFold` semantics.

## Type rendering

| Shape | Go |
|---|---|
| `PointFetchOk` | `type PointFetchOk struct { Opcodes []Opcode; NumRegisters uint32; NumCursors uint32; NumAggregates uint32; ResultCount uint32; OpcodeTemplateKind uint32 }` |
| `Option<PointFetchOk>` | `*PointFetchOk` (nil = None) |
| `PushdownTrigger` | `type PushdownTrigger int; const ( PushdownTriggerRowidPointFetch PushdownTrigger = iota )` |
| `EmitOp` | `type EmitOp int; const ( EmitOpOpenReadCursor EmitOp = iota; EmitOpKeyExprCompile; ... EmitOpEmitHalt )` |
| `RowidPointFetchTemplate` | `type RowidPointFetchTemplate struct { Trigger PushdownTrigger; Steps []EmitOp }` |

## Function signatures

```go
func TryCompilePointFetch(stmt *SelectStmt, schema *TableSchema) (*PointFetchOk, *CompileError)

func FindRowidIndex(schema *TableSchema) *IndexSpec

func IsRowIndependent(expr *Expr) bool
```

`(*PointFetchOk = nil, *CompileError = nil)` signals fall-through. A
non-nil error short-circuits to the caller's existing error path.

## Notes

- Go doesn't have algebraic Option; the canonical mapping is a
  nullable pointer. Same pattern used by sibling Go parts
  (mem-store, btree).
- Slice ownership: the GC owns the backing arrays. No manual
  free.
