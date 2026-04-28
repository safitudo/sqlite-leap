---
name: vdbe/opcodes-expr
---

# Part: vdbe/opcodes-expr

Expression evaluation opcodes: arithmetic, comparison, logical,
bitwise, type, string ops, scalar function dispatch. The largest
opcode family — ~40 ops collapsed into 8 variants of `OpcodeExpr`
keyed on a kind enum.

Declarations live in `shapes.json`; this file carries semantic
intent + the load-bearing per-op rules.

## Semantic contract

Every opcode writes its result to `regs[dest_reg]` and returns
`OpcodeOutcome::Continue`. The only Halt path is
`Halt(Error(OpcodeIllegal))` on unknown collation name (structural
faults from bounds checks are unreachable in well-formed code).

### `BinOp { kind, lhs, rhs, dest_reg }`

Read `a = regs[lhs]`, `b = regs[rhs]` (borrow). Dispatch on kind.

#### Arithmetic: `Add`, `Subtract`, `Multiply`, `Divide`, `Modulo`

- NULL-in-NULL-out: if `a` or `b` is `Null`, result is `Null`.
- Numeric affinity: coerce `Text` to number if it parses as one;
  coerce `Blob` to number by its bytewise interpretation as text.
  Non-numeric `Text` → `0` (SQLite semantics).
- Integer⊕Integer promotes to Real on overflow (Add/Subtract/
  Multiply).
- **`Divide` Integer/Integer = Integer division with truncation
  toward zero** (Pin 82). `7/2 → 3`, `(-7)/2 → -3`, `7/(-2) → -3`,
  `(-7)/(-2) → 3`. The result is Integer, never Real, regardless of
  whether the division is exact. To get a Real result, at least one
  operand must already be Real (e.g. `7.0/2 → 3.5`). This matches
  SQLite mainline semantics; the prior LEAP rule "exact stays
  Integer; otherwise Real" promoted int-by-int divisions to Real
  on inexact results, which is a divergence caught by corpus probe
  2026-04-25.
- **`Modulo` Integer/Integer = Integer remainder with sign of the
  dividend** (Pin 82 cont.). `7 % 2 → 1`, `(-7) % 2 → -1`,
  `7 % (-2) → 1`, `(-7) % (-2) → -1`. Matches C99/Rust `%`
  semantics for signed integers.
- **`Divide`/`Modulo` by zero → `Null`** (NOT
  `RuntimeCondition::DivZero`; pin Phase 6l / #120 / #121). The
  DivZero condition exists for diagnostics but is not raised
  under default execution.

#### Bitwise: `BitAnd`, `BitOr`, `Shl`, `Shr`

- NULL-in-NULL-out.
- Both operands coerced to `i64` via SQLite integer coercion
  (Text→parse-int, Real→truncate, Blob→byte-interpret-as-int).
- `Shl`/`Shr`: shift count is the rhs coerced to i64; SQLite
  truncates to [0, 64). Negative shift counts: Shl-neg is a Shr by
  the absolute value, symmetric (SQLite-compatible).

#### Comparison: `Eq`, `Ne`, `Lt`, `Le`, `Gt`, `Ge`

- NULL-in-NULL-out (any NULL operand → Null result).
- Affinity-aware ordering: numeric operands compared numerically;
  text operands under collation (default BINARY); blob bytewise.
- Mixed numeric/text: SQLite "CAST to numeric" rule — if the text
  parses as a number, compare numerically; otherwise the operand
  types diverge, using SQLite's type ranking: Null < Numeric < Text
  < Blob.
- `Eq` under affinity equality — NOT strict bytewise equal (pin
  Phase 6as).

#### Logical: `And`, `Or`

- Three-valued logic on Null:
  - `False AND Null = False`, `True AND Null = Null`,
    `Null AND Null = Null`.
  - `True OR Null = True`, `False OR Null = Null`,
    `Null OR Null = Null`.
- Operands coerced to boolean via `value_is_truthy`
  (`core`'s predicate). Result is `Integer(0)` / `Integer(1)` /
  `Null`.

#### `Concat`

- SQL `||` — string concatenation.
- Either operand Null → Null.
- Both operands coerced to Text (Integer→%d, Real→%!.15g Ryu,
  Blob→byte-interpret-as-text). Result is `Value::Text(owned)`.

### `UnaryOp { kind, src, dest_reg }`

Read `a = regs[src]`.

- `Neg`: NULL→NULL; Integer→-v (wrap on i64::MIN to Real);
  Real→-v; Text/Blob→coerce to numeric first.
- `Not`: NULL→NULL; truthy→Integer(0); falsy→Integer(1).
- `BitNot`: NULL→NULL; else coerce to i64, apply `!x`.
- `IsNull`: Always Integer. Null→1, else 0. Never Null.
- `NotNull`: Always Integer. Null→0, else 1. Never Null.

### `Cast { kind, src, dest_reg }`

Read `a = regs[src]`.

- NULL→NULL.
- `Cast{Integer}`: Real truncated toward zero; Text parsed as i64
  (empty/unparseable → 0); Blob byte-interpret.
- `Cast{Real}`: Integer→f64; Text parsed as f64 (empty/unparseable
  → 0.0); Blob byte-interpret.
- `Cast{Text}`: Integer→%d; Real use `CastRealToText` algorithm
  (Ryu); Blob→byte-interpret-as-text (UTF-8, no revalidation).

### `Like { hay, pat, esc, dest_reg }`

- Any operand Null → Null.
- Case-insensitive ASCII fold.
- `%` matches zero or more chars; `_` matches exactly one.
- `esc` (if `Some`): the first char of `regs[esc]`'s Text payload
  is the escape character; `esc_char + %` matches literal `%` etc.
- Result is `Integer(0)` or `Integer(1)`.

### `Glob { hay, pat, dest_reg }`

- Any operand Null → Null.
- Case-sensitive.
- `*` zero-or-more; `?` exactly-one; `[abc]` character class;
  `[a-z]` range; `[!...]` negated class.
- Result is `Integer(0)` or `Integer(1)`.

### `Collate { src, collation, dest_reg }`

- Attach the named collation to `regs[src]` for downstream
  comparisons.
- Recognized collations: `"BINARY"` (default byte-wise), `"NOCASE"`
  (ASCII lowercase), `"RTRIM"` (trailing ASCII spaces stripped).
- Unknown collation → `Halt(Error(OpcodeIllegal))`.
- Runtime representation: most targets return the value unchanged
  and leverage a collation-context slot on state for subsequent
  compares. Minimal v2 implementation: if `collation == "BINARY"`
  copy src to dest; otherwise store src-with-annotation by cloning
  into the target's collation-wrapped value shape. Cross-build
  equivalence tests only exercise BINARY by default; NOCASE/RTRIM
  exercised by phase-specific tests.

### `Scalar { kind, args, dest_reg }`

Read all args via `regs[args[i]]`. Per-kind:

**String:**
- `Length(s)`: Null→Null; Text→char-count (UTF-8 code points);
  Blob→byte-count; numeric→length of Text coercion.
- `Upper(s)`, `Lower(s)`: ASCII case fold; Null→Null.
- `Trim(s [, chars])`, `Ltrim(s [, chars])`, `Rtrim(s [, chars])`:
  strip chars set (default whitespace) from end(s); Null input →
  Null.
- `Substr(s, start [, length])`: SQLite 1-based indexing; negative
  start counts from end; length missing means to end; Null→Null.
- `Replace(s, needle, replacement)`: global replace; Null→Null.
- `Instr(hay, needle)`: 1-based index of first needle; 0 if not
  found; Null→Null.

**Arithmetic:**
- `Abs(x)`: Null→Null; absolute value (Integer stays Integer,
  Real stays Real; i64::MIN → Real).
- `Round(x [, digits])`: SQLite banker's-rounding to given digits
  (default 0). Null→Null.

**Null-handling:**
- `Coalesce(a, b, ...)`: first non-Null arg; all Null → Null.
- `Nullif(a, b)`: `a == b` (affinity equality) → Null; else `a`.
- `Ifnull(a, b)`: `a` if non-Null; else `b`.

**Type introspection:**
- `Typeof(x)`: Text payload — `"null"`, `"integer"`, `"real"`,
  `"text"`, `"blob"`.
- `Hex(b)`: uppercase hex string of Blob's bytes; for Text,
  interpret as bytes.
- `Quote(v)`: SQL-literal quoting (Null→`"NULL"`, Integer/Real →
  decimal text, Text → `'...'` with doubled quotes, Blob →
  `X'hex'`).

**Misc:**
- `Random()`: i64 pseudo-random per-call.
- `Date(...)`, `Time(...)`, `Datetime(...)`, `Julianday(...)`,
  `Strftime(...)`: SQLite datetime modifiers; v2 supports ISO
  timestamp input + `'now'` literal, modifiers `'localtime'` /
  `'utc'` / `'+N days'` / `'-N days'`. Unknown modifiers cause
  Null output (SQLite behavior).
- `Unicode(t)`: Unicode codepoint of first char of Text.
- `Char(n1, n2, ...)`: Text from given codepoints.
- `Printf(fmt, args...)`: SQLite `printf` — %d, %s, %f, %x, etc.

### `CastRealToText { src, dest_reg }`

Null → Null. Real → Text using SQLite's `%!.15g` Ryu-clone format.
Byte-identical cross-target is a hard correctness pin (Phase 6r).

## Invariants

- `lhs`, `rhs`, `src`, `dest_reg`, `esc`, `args[i]` all in
  `[0, state.num_registers)` (compiler guarantee).
- `collation` is a borrowed slice over Program source; lifetime
  bounded by the Program.

## Correctness pins

Load-bearing rules the emission MUST satisfy.

1. **NULL propagation** is universal for arithmetic, bitwise,
   comparison, string ops (Concat/Like/Glob/Replace/Instr/
   Substr/Length/Trim/Upper/Lower), Cast, and Coalesce's
   per-arg check. Explicit exceptions (must return Integer even
   on Null): `UnaryOp::IsNull`, `UnaryOp::NotNull`. Ifnull
   intentionally absorbs Null in its first arg.

2. **Divide/Modulo by zero → `Value::Null`**, NEVER a runtime
   condition. Pin #120 / #121. DivZero exists in
   `RuntimeCondition` for diagnostics but is not raised by default
   execution.

3. **Arithmetic overflow** on Integer Add/Subtract/Multiply
   promotes to Real, never halts. Target emissions must use
   checked-arithmetic helpers and fall back to `f64` on overflow
   (SQLite semantics).

4. **Comparison uses affinity equality**, not strict bytewise
   equal. Pin Phase 6as: the C-side `SCALAR2_STRICT_EQ` was
   reverted in favor of affinity equality. For mixed
   numeric-text, follow SQLite's "CAST to numeric" rule (parse
   text; compare as number if parse succeeds; else type-rank
   order).

5. **Real→Text uses `%!.15g` Ryu-clone**, byte-identical
   cross-target (Phase 6r). Both `Cast{Text}` on a Real and the
   dedicated `CastRealToText` must use this formatter.
   Target mappings may share a library routine; output bytes must
   match. Cross-build equivalence tests assert this.

6. **Three-valued logic** for `And` / `Or` / `Not`. NULL is
   UNKNOWN — see truth tables above. Do NOT short-circuit NULL
   to false.

7. **`Concat` and `CastRealToText` produce OWNED Text payloads**.
   The builder allocates a fresh Text value; the opcode hands it
   to `state.set_register(dest_reg, v)` without clone.

8. **Register borrow release**: for `BinOp`, capture both `a` and
   `b` borrows into locals, compute result value (owned), release
   borrows, then call `state.set_register`. In strict-borrow
   targets (Rust), the get_register borrow must end before the
   set_register mut call. A pattern-safe structure is:

   ```
   let a = state.get_register(lhs).clone();  // or capture a field
   let b = state.get_register(rhs).clone();
   let result = compute(kind, a, b);
   state.set_register(dest_reg, result);
   ```

   Targets without a borrow checker (Python, Go, C, Zig) follow
   the same ordering for source parallelism, but do not pay the
   clone cost — they can operate on references.

9. **`Collate` unknown collation** is the only Halt path in this
   family — `Halt(Error(RuntimeCondition::OpcodeIllegal))`. All
   other non-Null-propagation faults (bad scalar arg count, e.g.)
   are compiler responsibilities; runtime assumes well-formed.

10. **`Scalar::Nullif` uses affinity equality** (same rule as
    `BinOp::Eq`). Pin Phase 117.

11. **Like escape**: when `esc == Some(r)`, the first char of
    `regs[r]`'s Text payload is the escape. Empty or non-Text
    `regs[r]` → Null result (defensive; compiler should not emit
    such shapes).

12. **GroupConcat, date/time, and printf scalars** may delegate to
    per-target library routines (e.g., Rust `chrono`, C `strftime`,
    Python `datetime.strftime`). The SEMANTIC contract is
    SQLite-compatible; the target mapping picks the library.
    Cross-build equivalence tests exercise a well-defined subset
    (ISO input + 'now' + '+N days').

## Storage interaction surface

None. All state mutation is through `VdbeState` methods.

## Regeneration envelope

- Spec (this file): < 350 lines.
- `shapes.json`: < 180 lines.
- Each target emission: 800-1400 lines. The expression evaluator
  is the densest opcode family; no factoring is expected beyond
  small per-kind helpers.
