---
name: core
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
  - /schema/value.schema.json
emits:
  c:
    path: src-c-v2/core.h
    headers: []
  rust:
    path: src-rust-v2/core.rs
---

# Part: core

Shared primitive types used by multiple parts. This part has no
dependencies on other parts; every other part may `inherits:` it
to pin the canonical type shapes.

This was added at the first v2 pilot — the initial opcodes-core
regeneration worked around the absence of a shared-types owner
by importing from a stubbed `crate::core`. That hack is resolved
here: `parts/core/` is the owner.

## Types owned here (language-neutral declaration)

### `Value<'src>`

Runtime value. Carries an optional source-buffer lifetime for
borrowed text/blob payloads — though most sites hold owned data
because values cross row-emission boundaries.

Variants:
- **`Null`** — SQL NULL.
- **`Integer(i64)`** — 64-bit signed integer.
- **`Real(f64)`** — IEEE-754 double-precision float.
- **`Text(Text<'src>)`** — UTF-8 string; may be borrowed (source
  buffer) or owned (cross-boundary).
- **`Blob(Blob<'src>)`** — byte sequence; same borrow/own choice.

`Text<'src>` and `Blob<'src>` are each a "may-own-or-borrow" wrapper
— in Rust idiomatic form this is `Cow<'src, str>` and
`Cow<'src, [u8]>`; in C it is a struct `{ is_owned: bool, ptr, len }`
with a destructor that frees only when `is_owned`.

### `Register`

A VDBE register index. Opaque integer type (`u32`-equivalent) —
treat as `Copy`/value semantics. Range is implicit: any value in
`[0, num_registers)` for a given program is valid.

### `CursorId`

A VDBE cursor slot index. Opaque integer. Range: `[0, num_cursors)`.
Distinct type from `Register` — the compiler must not confuse
cursor slots and register slots.

### `OpcodeOutcome`

Single-opcode execution result. Returned from every `execute_*`
opcode function:

- **`Continue`** — advance program counter by 1.
- **`Jump(target)`** — set program counter to `target` (`usize`-like).
- **`Halt(status)`** — terminate execution; `status` is `HaltStatus`.
- **`EmitRow { start, count }`** — signal outer loop to emit a row
  from registers `[start .. start+count)`. Also advance pc by 1.

Variant shape is **struct-like for `EmitRow`** (named fields) and
**tuple-like for `Jump` and `Halt`** (positional). Every generator
must match this shape.

### `HaltStatus`

Why execution stopped.

- **`Ok`** — normal completion.
- **`Error(RuntimeCondition)`** — runtime fault; carries the
  structured condition.

Tuple-variant shape.

### `RuntimeCondition`

The closed set of runtime faults. Every generator emits the same
condition names for the same faults. Rust generators map to
`enum RuntimeCondition { ... }`; C generators to an integer enum
with matching names.

```
OpcodeIllegal             — program violated well-formedness
CursorClosed              — opcode touched a closed cursor slot
CursorNotWritable         — write op on a read-only cursor
TableNotFound             — OpenRead/OpenWrite on a missing table
TypeMismatch              — operand type invalid for opcode
ArithOverflow             — integer overflow
DivZero                   — only when the caller prefers error over NULL (SQLite default is NULL; this variant exists for diagnostics)
ConstraintNotNull
ConstraintUnique
ConstraintCheck
ConstraintType            — STRICT-table affinity violation
RecursiveCteLimit
SubqueryMoreThanOneRow    — scalar subquery returned > 1 row
IoError                   — passthrough from io-backend
```

Enum is closed — adding a new condition is a spec change, not a
local decision.

## Types NOT owned here

For clarity, these types are declared by OTHER parts and imported
where needed via `inherits:` of the owning part:

- `Opcode<'src>` — union enum of all opcode families. Owner:
  `parts/vdbe/master.md`. Each opcode-family leaf declares its own
  sub-enum (`OpcodeCore`, `OpcodeRows`, etc.), and `parts/vdbe/`
  composes them.
- `VdbeState<'src>` — the execution state (registers + cursors +
  pc). Owner: `parts/vdbe/master.md`.
- `Program<'src>` — compiled VDBE program. Owner:
  `parts/compiler/master.md`.
- `Ast<'src>`, `Expression<'src>`, etc. — AST node types. Owner:
  `parts/parser/master.md`.
- `Token<'src>`, `TokenStream<'src>` — lexer types. Owner:
  `parts/tokenizer/master.md`.
- `Database`, `TableSchema`, `CursorHandle` — storage types. Owner:
  `parts/storage/master.md`.
- `CompileError`, `ParseError`, `TokenizerError`, `StorageError`
  — structured error types per sub-system. Each system's
  top-level part owns its error enum.

## Cross-target conventions

### Rust emission

```rust
// src-rust-v2/core.rs
#[derive(Clone, Debug)]
pub enum Value<'src> {
    Null,
    Integer(i64),
    Real(f64),
    Text(Text<'src>),
    Blob(Blob<'src>),
}

pub type Text<'src> = std::borrow::Cow<'src, str>;
pub type Blob<'src> = std::borrow::Cow<'src, [u8]>;

pub type Register = u32;
pub type CursorId = u32;

#[derive(Debug)]
pub enum OpcodeOutcome {
    Continue,
    Jump(usize),
    Halt(HaltStatus),
    EmitRow { start: Register, count: u32 },
}

#[derive(Debug, Clone)]
pub enum HaltStatus {
    Ok,
    Error(RuntimeCondition),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RuntimeCondition {
    OpcodeIllegal,
    CursorClosed,
    CursorNotWritable,
    TableNotFound,
    TypeMismatch,
    ArithOverflow,
    DivZero,
    ConstraintNotNull,
    ConstraintUnique,
    ConstraintCheck,
    ConstraintType,
    RecursiveCteLimit,
    SubqueryMoreThanOneRow,
    IoError,
}
```

### C emission

```c
// src-c-v2/core.h
typedef enum LeapValueKind {
    LEAP_VALUE_NULL = 0,
    LEAP_VALUE_INTEGER,
    LEAP_VALUE_REAL,
    LEAP_VALUE_TEXT,
    LEAP_VALUE_BLOB,
} LeapValueKind;

typedef struct LeapText { bool is_owned; const char* ptr; size_t len; } LeapText;
typedef struct LeapBlob { bool is_owned; const uint8_t* ptr; size_t len; } LeapBlob;

typedef struct LeapValue {
    LeapValueKind kind;
    union {
        int64_t i;
        double  r;
        LeapText t;
        LeapBlob b;
    } as;
} LeapValue;

typedef uint32_t LeapRegister;
typedef uint32_t LeapCursorId;

typedef enum LeapOpcodeOutcomeKind {
    LEAP_OC_CONTINUE = 0,
    LEAP_OC_JUMP,
    LEAP_OC_HALT,
    LEAP_OC_EMIT_ROW,
} LeapOpcodeOutcomeKind;

typedef struct LeapOpcodeOutcome {
    LeapOpcodeOutcomeKind kind;
    union {
        size_t jump_target;
        struct { bool is_error; LeapRuntimeCondition err; } halt;
        struct { LeapRegister start; uint32_t count; } emit_row;
    } as;
} LeapOpcodeOutcome;

typedef enum LeapRuntimeCondition {
    LEAP_RC_OPCODE_ILLEGAL = 0,
    LEAP_RC_CURSOR_CLOSED,
    LEAP_RC_CURSOR_NOT_WRITABLE,
    LEAP_RC_TABLE_NOT_FOUND,
    LEAP_RC_TYPE_MISMATCH,
    LEAP_RC_ARITH_OVERFLOW,
    LEAP_RC_DIV_ZERO,
    LEAP_RC_CONSTRAINT_NOT_NULL,
    LEAP_RC_CONSTRAINT_UNIQUE,
    LEAP_RC_CONSTRAINT_CHECK,
    LEAP_RC_CONSTRAINT_TYPE,
    LEAP_RC_RECURSIVE_CTE_LIMIT,
    LEAP_RC_SUBQUERY_MORE_THAN_ONE_ROW,
    LEAP_RC_IO_ERROR,
} LeapRuntimeCondition;
```

These are the canonical emissions. Other parts MUST match the
names and shapes — if a generator invents a different shape,
the resulting src-* will not compose with siblings.

## Regeneration envelope

- Target leaf size per target: ~100–200 lines. This is a pure
  types file — no logic.
- Spec size budget: this file < 400 lines.
- Test ownership: none. Types are validated by compilation of
  dependent parts.
