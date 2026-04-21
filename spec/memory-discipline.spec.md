# Memory discipline — language-neutral rules for the hot path

This spec is load-bearing for benchmark-lane parity between targets. It's strictly language-neutral: every rule here is stated as an ownership invariant that each target's generator must implement with its native mechanism (C: pointers into the source buffer; Rust: `&str` with a lifetime tied to the source buffer; other targets: equivalent borrow-or-view construct).

## The rule

Intermediate compiled structures that flow through the parse → compile → execute pipeline MUST NOT own character data for SQL identifiers, keywords, or punctuation. They MUST reference character data already present in the SQL source buffer supplied by the caller.

Owning a `String`-equivalent per statement in each intermediate structure accumulates to 2–3× per-statement overhead on parse-heavy and INSERT-heavy workloads. This is not a stylistic preference — it's a published benchmark requirement (see `CLAUDE.md` § "The six benchmark lanes"). Generators that clone strings along the pipeline produce correct but slow implementations.

## Lifetime contract

The SQL source buffer supplied by the caller MUST outlive:

- the token stream produced by the tokenizer
- the AST produced by the parser
- the Program produced by the compiler
- the execution of that Program by the VDBE

In practice this means every generator emits a pipeline in which a single source buffer (passed in by the CLI main, the harness, or the WASM FFI entry point) is held by the caller for the full statement run, and all downstream structures reference it.

## Where ownership DOES live

Character data IS owned at exactly these boundaries:

1. **Database catalog** — `Table.name`, `Column.name`, `Column.type_label` (stored long-term; cloned into the catalog when `CreateTable` opcode executes).
2. **Row values** — `Value::Text` and the bytes of a stored record own their contents. A `Value::Text` produced by the VDBE at execute time is either (a) copied out of the source buffer at load-constant time, or (b) decoded from a record payload read from storage. Either way, ownership is required because the value may outlive the source buffer (e.g., result rows returned to the caller after the statement is complete).
3. **Error fields** — `ParseError.kind`, `ParseError.expected`, storage-error fields (`table`, `column`, etc.) own their strings. Errors cross arbitrary API boundaries and must not carry lifetimes tied to the source.
4. **Returned result rows** — `QueryResult.rows[*][*]` and anything callers can hold after the statement finishes.

Everything else on the hot path is a reference.

## Concrete mapping to each field

The following table specifies, for every field of every structure type in the pipeline, whether its character data is **Borrowed** (references into the source buffer) or **Owned**.

| Structure       | Field                          | Discipline |
|-----------------|--------------------------------|------------|
| `Token::Identifier`    | `name`                  | Borrowed  |
| `Token::StringLiteral` | `value`                 | Owned (may need escape decoding; see below) |
| `Token` (other)        | —                       | n/a |
| `ColumnDef`            | `name`                  | Borrowed (in AST/Opcode) — Owned (in catalog) |
| `ColumnDef`            | `type_label` (if any)   | Borrowed (in AST/Opcode) — Owned (in catalog) |
| `Ast::CreateTable`     | `table`                 | Borrowed |
| `Ast::Insert`          | `table`                 | Borrowed |
| `Ast::Insert`          | `column_names[i]`       | Borrowed |
| `Ast::Select`          | `table`                 | Borrowed |
| `Ast::Update`          | `table`                 | Borrowed |
| `Ast::Update.assignments[i]` | `column`          | Borrowed |
| `Ast::Delete`          | `table`                 | Borrowed |
| `Expression::Column`   | `name`                  | Borrowed |
| `Opcode::OpenRead`     | `table`                 | Borrowed |
| `Opcode::OpenWrite`    | `table`                 | Borrowed |
| `Opcode::CreateTable`  | `table`                 | Borrowed |
| `Opcode::CreateTable`  | `columns[i]`            | Borrowed |
| `Opcode::InsertRow`    | `column_names[i]`       | Borrowed |
| `Opcode::UpdateRow`    | `column_names[i]`       | Borrowed |
| `Value::Text` (in Opcode `LoadConst`, computed at compile time) | inner | Owned (see "String-literal decoding" below) |
| `ParseError.kind`      |                         | Owned |
| `ParseError.expected[i]`|                        | Owned |
| `EngineError::*`       | (any string field)      | Owned |
| `QueryResult.rows[i][j]::Text` | inner           | Owned |
| `Table.name` (catalog) |                         | Owned |
| `Column.name` (catalog)|                         | Owned |

**String-literal decoding.** SQL string literals written as `'hello'` need the surrounding quotes stripped and `''` escape sequences collapsed to `'`. This transform produces a new sequence of bytes that is NOT a sub-slice of the source. The spec-compliant choice is to own the decoded bytes at tokenize time (so `Token::StringLiteral.value` is owned). This is a single allocation per literal — acceptable because string-literal-heavy workloads are rare, and the alternative (Cow-like borrow-when-no-escape / own-when-escape) adds spec complexity for little marginal gain.

## What this means per target

**C.** Current C generator already complies: tokens carry `const char *text` pointing into the source buffer; identifier fields on AST/Opcode carry the same pointer; the storage catalog `strdup`'s into its own memory on CREATE TABLE. No change required.

**Rust.** Current Rust generator violates this spec by carrying `String` (owned) on every identifier field. Rust generator must re-emit the pipeline so that:

- `Token<'src>`, `Ast<'src>`, `Opcode<'src>`, `Program<'src>` are lifetime-parameterized.
- Every field marked "Borrowed" above becomes `&'src str` (or `Vec<&'src str>`, `Option<&'src str>`, etc.).
- The top-level entry point (`tokenize(sql: &str)`) returns a token stream parameterized by the lifetime of `sql`.
- Parser, compiler, VDBE runner all take `&'src`-parameterized inputs and return `&'src`-parameterized outputs.
- Error types remain owned (`String` fields), so errors can be returned across the lifetime boundary without blocking.
- Catalog types in `storage.rs` remain owned (`String`), and the VDBE clones at the moment of CREATE TABLE / row insertion.

**WASM.** Unaffected at the FFI boundary — `leap_exec` still takes a NUL-terminated pointer, copies it into a Rust `String`, then tokenizes with that buffer live for the statement. The borrowed-string refactor is entirely internal.

## Verification

A generator is compliant with this spec if:

1. All existing phase harnesses pass (`phase1`..`phase6a`, 255 tests/target).
2. `tests/cross-build/roundtrip_formal.py` passes 16/16.
3. `tests/cross-build/phase7_smoke.mjs` still passes 13/13 (WASM).
4. Allocations-per-statement on a simple `INSERT INTO t VALUES (N);` are within ~1 of the C build's count (measured via Rust's `#[global_allocator]` or equivalent — optional; benchmark proxy is sufficient).
5. Per-statement wall-time overhead on the 5k-INSERT L2 benchmark drops to ≤ 1.3× C build (previously ~3×).

## Non-goals

- Zero-allocation tokenize. Integer literals are parsed into `i64` eagerly; string literals allocate once for escape decoding; errors allocate. These are acceptable.
- Zero-copy storage path. The catalog and record payloads continue to own their data.
- Interning / string-table optimizations. Out of scope; the borrow discipline captures >90% of the win.
