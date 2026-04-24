---
name: expr-compile
kind: leaf
emits:
  rust: { path: src-rust/compiler/expr_compile.rs }
---

# Expression compiler (AST → VDBE opcodes)

Translates a parser `Expr` AST into a sequence of VDBE opcodes that,
when executed, leaves the expression's result in a designated register.
This is the **critical structural probe for the middle of the
pipeline**: if AST→VDBE compiles cleanly from a language-neutral spec,
the whole compiler tree (SELECT / INSERT / UPDATE / DELETE compilers)
is on rails.

## Scope

Admitted AST nodes:
- `Expr::IntLit { text }` — parse text as `i64` decimal; hex `0x...`
  accepted; failure → CompileError.
- `Expr::RealLit { text }` — parse text as `f64`; failure → CompileError.
- `Expr::StrLit { text }` — text carries surrounding `'...'`. Strip
  quotes and un-double `''` escapes before producing `Value::Text`.
  This is the one place in the probe where text transformation happens.
- `Expr::Null` — produces `Value::Null`.
- `Expr::Unary { op, arg }` — recurse into arg, emit one `UnaryOp`
  opcode (dest_reg = next free).
- `Expr::Binary { op, lhs, rhs }` — recurse into lhs then rhs, emit
  one `BinOp` opcode.
- `Expr::IsNull { arg, negated }` — recurse into arg; emit one
  `UnaryOp { kind: IsNull or NotNull, src, dest_reg }` opcode.
  `negated=false` → `UnaryOpKind::IsNull`; `negated=true` →
  `UnaryOpKind::NotNull`. Both opcodes already exist in
  `/parts/vdbe/parts/opcodes-expr/shapes.json::UnaryOpKind` and
  return Integer(1)/Integer(0), never Null.

Not-yet-admitted (produce CompileError with message
`"deferred: <NodeKind>"`):
- `Expr::Col` — needs a column resolver (later part).
- `Expr::Call` — needs a scalar-function catalog (later part).

## Declared shapes (in `shapes.json`)

- `CompileError { message: string }`
- `CompileOk { code: list<Opcode>, result_reg: Register, next_reg: Register }`
- `compile_expr(expr: &Expr, reg_base: Register) -> result<CompileOk, CompileError>`

## Algorithm (recursive pre-order walk, three-address form)

```
compile_expr(expr, reg_base):
    match expr:
        IntLit(text):
            v = parse_int(text)                         ? → CompileError
            return Ok(code: [LoadConst(reg_base, Integer(v))],
                      result_reg: reg_base,
                      next_reg: reg_base + 1)

        RealLit(text):
            v = parse_real(text)                        ? → CompileError
            return Ok(code: [LoadConst(reg_base, Real(v))], ...)

        StrLit(text):
            s = strip_quotes_and_unescape(text)
            return Ok(code: [LoadConst(reg_base, Text(s))], ...)

        Null:
            return Ok(code: [LoadConst(reg_base, Null)], ...)

        Unary(op, arg):
            (ac, ar, an) = compile_expr(arg, reg_base)?
            dest         = an
            kind         = map_unary(op)
            code         = ac ++ [UnaryOp { kind, src: ar, dest_reg: dest }]
            return Ok(code, result_reg: dest, next_reg: dest + 1)

        Binary(op, lhs, rhs):
            (lc, lr, ln) = compile_expr(lhs, reg_base)?
            (rc, rr, rn) = compile_expr(rhs, ln)?
            dest         = rn
            kind         = map_binary(op)
            code         = lc ++ rc ++ [BinOp { kind, lhs: lr, rhs: rr, dest_reg: dest }]
            return Ok(code, result_reg: dest, next_reg: dest + 1)

        IsNull(arg, negated):
            (ac, ar, an) = compile_expr(arg, reg_base)?
            dest         = an
            kind         = negated ? UnaryOpKind::NotNull : UnaryOpKind::IsNull
            code         = ac ++ [UnaryOp { kind, src: ar, dest_reg: dest }]
            return Ok(code, result_reg: dest, next_reg: dest + 1)

        Col | Call:
            return Err(CompileError { message: "deferred: " + node_kind })
```

Three-address form: each opcode reads from two registers and writes
into one. Registers are allocated monotonically; no re-use within a
sub-tree. This keeps the compiler simple and proves the structural
point without tackling the register-pressure optimization problem.

## BinaryOp → BinOpKind mapping

The parser's `BinaryOp` has 18 cases; VDBE's `BinOpKind` (declared by
`/parts/vdbe/parts/opcodes-expr`) has its own naming. The map:

| Parser `BinaryOp` | VDBE `BinOpKind` |
|-------------------|------------------|
| `Or`              | `Or`             |
| `And`             | `And`            |
| `Eq`              | `Eq`             |
| `NotEq`           | `Ne`             |
| `Lt`              | `Lt`             |
| `Le`              | `Le`             |
| `Gt`              | `Gt`             |
| `Ge`              | `Ge`             |
| `BitOr`           | `BitOr`          |
| `BitAnd`          | `BitAnd`         |
| `ShiftL`          | `Shl`            |
| `ShiftR`          | `Shr`            |
| `Plus`            | `Add`            |
| `Minus`           | `Subtract`       |
| `Mul`             | `Multiply`       |
| `Div`             | `Divide`         |
| `Mod`             | `Modulo`         |
| `Concat`          | `Concat`         |

The emission agent must read
`/parts/vdbe/parts/opcodes-expr/shapes.json` to confirm the exact
VDBE-side case names. If any parser-side name is absent in the VDBE
enum, STOP and surface the gap.

## UnaryOp → UnaryOpKind mapping

| Parser `UnaryOp` | VDBE `UnaryOpKind` |
|------------------|--------------------|
| `Neg`            | `Neg`              |
| `Not`            | `Not`              |

## Literal-text transformations

**Int**: accept optional `0x` / `0X` hex prefix. Otherwise parse as
decimal. Negative values are not literals (parser emits `Unary(Neg, ...)`
for `-1`). Overflow of `i64` → CompileError with message
`"integer literal out of i64 range: <text>"`.

**Real**: parse using the target's standard float parser. `inf` / `nan`
emit CompileError (not SQL literals).

**Str**: strip the opening and closing `'` bytes; un-double every `''`
into a single `'`. The result is an owned UTF-8 string wrapped in
`Value::Text`. Blob-literal handling (`X'...'`) is DEFERRED — parser
produces `Expr::StrLit` only, so compile_expr never sees a blob here.

## Correctness pins

1. **Pure function** — `compile_expr` does not mutate any caller state.
   The only outputs are through the returned `CompileOk` / `CompileError`.
2. **Monotonic register allocation** — `CompileOk.next_reg >
   CompileOk.result_reg` always, and recursive sub-calls receive
   `reg_base` >= their parent's reg_base. No register is written
   twice across the emitted program.
3. **Three-address BinOp / UnaryOp** — every binary opcode has
   distinct `lhs`, `rhs`, `dest_reg` from the recursion's sub-results.
   Every unary opcode's `dest_reg` is a fresh register (equal to the
   child's `next_reg`).
4. **Every parser BinaryOp case maps** — the 18 cases in
   `/parts/parser/parts/expr/shapes.json::BinaryOp.cases` each map to
   exactly one VDBE `BinOpKind`. The mapping table above is
   authoritative; the agent must NOT invent a new mapping silently.
   If a mapping is missing, STOP and flag.
5. **Every parser UnaryOp case maps** — `Neg`, `Not` both map.
6. **Int literal parsing** — `"42"` → Integer(42); `"0x10"` →
   Integer(16); `"99999999999999999999"` → CompileError
   (out-of-range).
7. **Real literal parsing** — `"1.5"` → Real(1.5); `"1e10"` →
   Real(1e10); `"inf"` / `"nan"` → CompileError (not a literal).
8. **String literal unescape** — `"'can''t'"` (8 bytes with
   surrounding quotes) → Value::Text("can't"). Opening+closing quotes
   are stripped; `''` pairs become single `'`.
9. **Null literal** — `Expr::Null` → `[LoadConst(r, Null)]`.
10. **Deferred nodes** — `Expr::Col { name }` →
    `CompileError { message: "deferred: Col" }`. `Expr::Call` →
    `CompileError { message: "deferred: Call" }`. No partial output.
11. **Recursive descent, not iteration** — the compiler recurses into
    lhs, then rhs, then emits the parent opcode — a textbook
    post-order walk of the AST. This is the natural form for
    three-address code and must be the structure in the emission.
12. **No inline tests, no helpers not needed by the algorithm** —
    `compile_expr` plus target-idiomatic literal-parsing helpers
    (e.g. Rust `str::parse::<i64>`, `str::parse::<f64>`). No
    optimization passes, no common-subexpression elimination.
14. **IsNull compilation** — `Expr::IsNull { arg, negated }` emits
    the arg's code, then one `UnaryOp { kind: IsNull|NotNull, src,
    dest_reg }`. The arg's `result_reg` is the `src` of the unary
    opcode. `dest_reg` is the next free register after the arg's
    `next_reg`. Result is always Integer(0) or Integer(1), never Null.

13. **Opcode composition** — the emitted `code` list is over the
    composed `Opcode` type declared in `/parts/vdbe/shapes.json`
    (the `compose` union of OpcodeCore + OpcodeExpr + the other
    families). The agent reads the composed `Opcode` surface to know
    which constructors wrap `LoadConst` and `BinOp`.

## Regeneration envelope

- Line budget: **~150-250 lines** of Rust.
- No dependencies beyond std.
- Public items: `CompileError`, `CompileOk`, `compile_expr`.

## Smoke probe

`src-rust/examples/compile_smoke.rs` (hand-written, NOT regenerated)
tokenizes + parses + compiles six expressions and executes each via
the composed VDBE, asserting the final register holds the expected
`Value`:

```text
1. 1 + 2                   → Integer(3)
2. 2 * 3 + 4               → Integer(10)   (left-assoc: (2*3)+4)
3. (1 + 2) * 3             → Integer(9)
4. 10 - 3 * 2              → Integer(4)    (prec: 10-(3*2))
5. -5 + 1                  → Integer(-4)   (unary)
6. 'ab' || 'cd'            → Text("abcd")
```

The runner sets up a `VdbeState` via `VdbeState::new`, appends the
compiled opcodes + a final `OpcodeCore::Halt`, runs
`execute_program`, reads out the result register, and prints
`OK: all N expressions compile + execute to expected value` on
success.
