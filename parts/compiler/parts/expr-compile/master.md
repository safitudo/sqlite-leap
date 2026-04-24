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
- `Expr::Case { branches, else_ }` — emit branch-evaluation chain
  using `IfNot` + `Goto` control opcodes from
  `/parts/vdbe/parts/opcodes-control`. Result register is allocated
  at `reg_base` and left untouched until a branch hits. See
  §CASE compilation algorithm below. **Self-relative PC targets:**
  every `Goto`/`IfNot.target` emitted by `compile_expr` is an
  absolute PC **within the returned `code` list** (0-based,
  `0..code.len()`). When a caller splices the emitted code into
  a larger program at offset `k`, the caller MUST rewrite every
  such target to `k + target` before final resolution. This
  self-relative discipline is new for Case; prior arms emitted
  no jumps, so the caller (e.g. select-compile) was never asked
  to rebase. SPEC NOTE: the rebase responsibility belongs to
  the splicing caller; the composed-splice helper lives in
  select-compile (to be added on first use beyond the standalone
  smoke).

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

        Case(branches, else_):
            return compile_case(branches, else_, reg_base)

        Col | Call:
            return Err(CompileError { message: "deferred: " + node_kind })
```

## CASE compilation algorithm

Layout of emitted code for `CASE WHEN p1 THEN r1 WHEN p2 THEN r2 ELSE e END`:

```
  result_reg = reg_base
  scratch    = reg_base + 1  (grows during each branch's evaluation)

  ; branch 1
  <code for p1, result in reg P1, uses regs scratch..>
  IfNot { cond_reg: P1, target: L_NEXT_1 }
  <code for r1, result in reg R1>
  Copy { src_reg: R1, dest_reg: result_reg }
  Goto { target: L_END }
L_NEXT_1:
  ; branch 2
  <code for p2, result in reg P2>
  IfNot { cond_reg: P2, target: L_NEXT_2 }
  <code for r2, result in reg R2>
  Copy { src_reg: R2, dest_reg: result_reg }
  Goto { target: L_END }
L_NEXT_2:
  ; else
  <code for e, result in reg E>    ; if else_ == None, emit LoadConst(result_reg, Null) instead
  Copy { src: E, dst: result_reg }  ; skipped if no else_
L_END:
```

`Copy` is the opcode from `/parts/vdbe/parts/opcodes-core` (or the
equivalent register-copy opcode; agent confirms the exact name by
reading the composed Opcode surface). Its effect is
`regs[dst] := regs[src]`.

`scratch = reg_base + 1` is passed as the `reg_base` parameter to each
sub-`compile_expr` call. This preserves pin 2 (monotonic register
allocation within a sub-expression) while reserving reg_base exclusively
for the final result.

Emission procedure (single pass; PC placeholders are resolved at the
end of compile_case):

```
compile_case(branches, else_, reg_base):
    result_reg = reg_base
    scratch    = reg_base + 1
    code       = []
    goto_end_patches = []           # indices of Goto instructions whose target = L_END
    for (when_e, then_e) in branches:
        (wc, wr, wn) = compile_expr(when_e, scratch)?
        # The wc opcodes have self-relative jumps in the range 0..len(wc).
        # When we append them to `code` at current offset, we must rebase
        # their internal Goto/IfNot targets by +len(code).
        append_with_rebase(code, wc, offset = len(code))
        ifnot_idx = len(code)
        code.push(IfNot { cond_reg: wr, target: PC_PLACEHOLDER })
        (tc, tr, tn) = compile_expr(then_e, scratch)?
        append_with_rebase(code, tc, offset = len(code))
        code.push(Copy { src: tr, dst: result_reg })
        goto_end_patches.push(len(code))
        code.push(Goto { target: PC_PLACEHOLDER })
        # Patch ifnot to point at the next instruction (start of next branch or else).
        code[ifnot_idx].target = len(code)
    if else_ is Some(ee):
        (ec, er, en) = compile_expr(ee, scratch)?
        append_with_rebase(code, ec, offset = len(code))
        code.push(Copy { src: er, dst: result_reg })
    else:
        code.push(LoadConst { dest_reg: result_reg, value: Null })
    l_end = len(code)
    for idx in goto_end_patches:
        code[idx].target = l_end
    # Tight next_reg upper bound — compile_case never writes past scratch's
    # highest reach. Compute by walking (tn, en) max and adding safety 1.
    high = max(scratch + 1, observed_max_of(wn, tn, en))
    return Ok(code, result_reg, next_reg = high)

append_with_rebase(code, sub_code, offset):
    # Every Goto { target } and IfNot { cond_reg, target } inside sub_code
    # has `target` in range 0..len(sub_code). Rewrite target += offset.
    # Other opcode kinds are copied unchanged.
    for op in sub_code:
        code.push(rebase(op, offset))
```

The `PC_PLACEHOLDER` sentinel is any unambiguous value (e.g. `u32::MAX`
or equivalent); its presence must not survive the return (all patches
applied before return). `append_with_rebase` inspects each opcode; in
practice only `Goto` and `IfNot` carry PC targets today. If a future
opcode gains a PC target, the rebase helper must learn to rewrite it.

Empty `branches` is a PRECONDITION violation (caller must enforce; the
parser rejects empty-branches CASE). If `compile_case` still sees an
empty list, return `CompileError { message: "internal: Case with zero branches" }`.


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
15. **Case compilation — result register** — `result_reg = reg_base`
    is the FIRST register owned by the Case emission. It receives
    exactly one write: either a `Copy` from the winning branch's
    then_expr, or (missing else_ with no branches truthy) a
    `LoadConst(reg_base, Null)`. Sub-expressions allocate starting
    at `reg_base + 1`.
16. **Case compilation — self-relative jumps** — all `Goto` and
    `IfNot` targets in the returned `code` list are absolute PCs
    within that list (0-based, `0..code.len()`). A caller splicing
    this code at offset `k` must rebase every such target by `+k`.
    Within a single `compile_case` invocation, `append_with_rebase`
    handles this rebasing for the sub-expression emissions; the
    outermost Gotos/IfNots are written to compile_case's local
    code list and patched there.
17. **Case compilation — no placeholders survive** — on successful
    return, no opcode in the emitted list carries `PC_PLACEHOLDER`.
    All patches (branch-skip IfNots, end-of-Case Gotos) are applied
    inside `compile_case` before return. The spec MUST fail if a
    placeholder survives (internal invariant check).
18. **Case compilation — else absence** — if `else_` is `None`, the
    emitted tail writes `LoadConst(result_reg, Null)`, not a
    Copy. This way result_reg always gets a definite value even
    when no branch matches.

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
7. CASE WHEN 1 THEN 10 ELSE 20 END           → Integer(10)
8. CASE WHEN 0 THEN 10 ELSE 20 END           → Integer(20)
9. CASE WHEN 0 THEN 10 WHEN 1 THEN 20 ELSE 30 END   → Integer(20)
10. CASE WHEN 0 THEN 10 END                   → Null (no else_, no match)
11. CASE 2 WHEN 1 THEN 'a' WHEN 2 THEN 'b' ELSE 'c' END → Text("b") (simple-form desugar)
```

The runner sets up a `VdbeState` via `VdbeState::new`, appends the
compiled opcodes + a final `OpcodeCore::Halt`, runs
`execute_program`, reads out the result register, and prints
`OK: all N expressions compile + execute to expected value` on
success.
