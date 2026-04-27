---
name: create-table-stmt
kind: leaf
emits:
  rust: { path: src-rust/parser/create_table_stmt.rs }
  c:    { path: src-c/parser/create_table_stmt.c, headers: [src-c/parser/create_table_stmt.h] }
---

# CREATE TABLE statement parser

Parses a `CREATE TABLE` statement from a `Token` stream produced by
`/parts/parser/parts/tokenizer`, using `parse_expr` from
`/parts/parser/parts/expr` for every embedded DEFAULT / CHECK /
GENERATED expression. This is the first DDL leaf and validates that
the statement-parser pattern handles the structurally richest DDL
form (column-list, per-column constraint sequences, table-level
constraints, table-level options).

## Scope

Admitted:
- `CREATE TABLE` followed by an optional `IF NOT EXISTS`.
- A bare table identifier.
- A non-empty parenthesized list of column definitions, each with:
  - column name (Ident),
  - optional type name (one or more bare Idents space-joined; e.g.
    `INT`, `DOUBLE PRECISION`, `VARCHAR`),
  - zero or more column constraints (see `ColumnConstraint`).
- Zero or more table-level constraints inside the same parens, after
  the last column, comma-separated.
- Optional table-level options after the closing paren:
  `WITHOUT ROWID`, `STRICT`, or both (in either order, comma-separated).

Deferred (flag ParseError with `"deferred: <construct>"`):
- `CREATE TEMP TABLE` / `CREATE TEMPORARY TABLE`.
- Schema-qualified names (`schema.table`).
- `CREATE TABLE ... AS SELECT ...`.
- Parameterized type names (`VARCHAR(255)`, `DECIMAL(10,2)`).
- `ON DELETE` / `ON UPDATE` action clauses on REFERENCES.
- `DEFERRABLE` / `INITIALLY DEFERRED` on FK.
- `CONFLICT-clause` (`ON CONFLICT REPLACE` etc.) on column constraints.
- `CONSTRAINT <name>` named-constraint prefix.
- Multi-column `REFERENCES` from the column-level shorthand
  (column-level shorthand admits `REFERENCES t(c)` only one ref-col
  through this leaf — but to keep the shape uniform with table-level
  FK we admit a list; pin 9 explains).

## Algorithm

```
parse_create_table(tokens, i):
    expect tokens[i] == KwCreate; i += 1
    expect tokens[i] == KwTable;  i += 1   # otherwise "expected TABLE after CREATE"
    if_not_exists = false
    if tokens[i] == KwIf:
        i += 1
        expect tokens[i] == KwNot;    i += 1
        expect tokens[i] == KwExists; i += 1
        if_not_exists = true
    if tokens[i] != Ident: error("expected table name")
    name = tokens[i].text; i += 1
    if tokens[i] == Dot: error("deferred: schema-qualified table")
    if tokens[i] == KwAs: error("deferred: CREATE TABLE AS SELECT")
    expect tokens[i] == LParen; i += 1
    columns = []
    table_constraints = []
    loop:
        # Decide column-def vs table-constraint by leading keyword.
        if tokens[i] in { KwPrimary, KwUnique, KwCheck, KwForeign }:
            tc, i = parse_table_constraint(tokens, i)
            table_constraints.push(tc)
        else:
            cd, i = parse_column_def(tokens, i)
            columns.push(cd)
        if tokens[i] == Comma: i += 1; continue
        break
    if tokens[i] != RParen: error("expected ) after column list")
    i += 1
    without_rowid = false; strict = false
    loop:
        if tokens[i] == KwWithout:
            i += 1
            if tokens[i] != Ident("ROWID"): error("expected ROWID after WITHOUT")
                # ROWID is a contextual keyword; tokenizer emits Ident for it.
            i += 1
            without_rowid = true
        elif matches_strict_ident(tokens[i]):
            # STRICT is contextual: tokenizer emits Ident{"STRICT"} since
            # there is no KwStrict token kind.
            i += 1
            strict = true
        else: break
        if tokens[i] == Comma: i += 1; continue
        break
    return Ok({ name, if_not_exists, columns, table_constraints,
                without_rowid, strict }, next: i)

parse_column_def(tokens, i):
    if tokens[i] != Ident: error("expected column name")
    name = tokens[i].text; i += 1
    type_name = None
    if tokens[i] == Ident and tokens[i].text not in CONSTRAINT_LEAD:
        # Type name: one or more Idents, joined by ' '. Stops at any
        # constraint-leading keyword (NOT, PRIMARY, UNIQUE, DEFAULT,
        # CHECK, REFERENCES, COLLATE, GENERATED, KwAs which leads
        # GENERATED-AS shorthand) or at Comma / RParen.
        parts = []
        while tokens[i] == Ident:
            parts.push(tokens[i].text); i += 1
        type_name = Some(parts.join(' '))
        type_params = []
        if tokens[i] == LParen:
            # Parameterized type: VARCHAR(30), DECIMAL(10, 2), etc.
            # Admit one or two non-negative integer arguments. The
            # type_name string does NOT include the parens; the integer
            # arguments are captured separately on ColumnDef.type_params.
            i += 1
            require(tokens[i] == Integer); type_params.push(parse_int(tokens[i].text)); i += 1
            if tokens[i] == Comma:
                i += 1
                require(tokens[i] == Integer); type_params.push(parse_int(tokens[i].text)); i += 1
            require(tokens[i] == RParen); i += 1
    constraints = []
    loop:
        c = match tokens[i]:
            KwNot:        consume NOT NULL  → NotNull
            KwPrimary:    consume PRIMARY KEY [ASC|DESC] → PrimaryKey { ascending }
            KwUnique:     consume UNIQUE → Unique
            KwDefault:    consume DEFAULT <expr> → Default { value }
                          ; allows parenthesized expr or single-token literal
            KwCheck:      consume CHECK (<expr>) → Check { expr }
            KwReferences: consume REFERENCES <ident> [(col-list)] → References
            KwCollate:    consume COLLATE <ident> → Collate
            KwGenerated:  consume GENERATED ALWAYS AS (<expr>) [STORED|VIRTUAL]
                          → Generated { expr, stored }
            KwAs:         consume AS (<expr>) [STORED|VIRTUAL] → Generated
                          (shorthand: `AS (...)` without `GENERATED ALWAYS`)
            else:         break
        constraints.push(c)
    return { name, type_name, type_params, constraints }, i

parse_table_constraint(tokens, i):
    match tokens[i]:
        KwPrimary: consume PRIMARY KEY (<col-list>) → PrimaryKey
        KwUnique:  consume UNIQUE      (<col-list>) → Unique
        KwCheck:   consume CHECK       (<expr>)     → Check
        KwForeign: consume FOREIGN KEY (<col-list>)
                       REFERENCES <ident> [(<col-list>)] → ForeignKey
    return tc, i
```

Contextual ident note: SQLite treats `STRICT` and `ROWID` as
context-sensitive keywords, NOT as reserved words. Our tokenizer
emits them as `Ident { text }`. The parser matches by text
case-insensitively (per pin 12).

## Correctness pins

1. **Shape conformance** — `CREATE TABLE t (a)` parses to
   `{ name: "t", if_not_exists: false, columns: [{name:"a", type_name:None, constraints:[]}], table_constraints: [], without_rowid: false, strict: false }`.
2. **IF NOT EXISTS** — `CREATE TABLE IF NOT EXISTS t (a)` sets
   `if_not_exists = true`. A bare `IF` not followed by `NOT EXISTS`
   is a ParseError.
3. **Type names** — `a INT` produces `type_name: Some("INT")`;
   `b DOUBLE PRECISION` produces `type_name: Some("DOUBLE PRECISION")`
   (single ASCII space joiner).
4. **NotNull constraint** — `a INT NOT NULL` yields a single
   `NotNull` constraint. `a NOT NULL` (no type) is ALSO valid.
5. **PrimaryKey** — `a INT PRIMARY KEY` → `PrimaryKey { ascending: true }`.
   `a INT PRIMARY KEY DESC` → `PrimaryKey { ascending: false }`.
   `a INT PRIMARY KEY ASC` → `PrimaryKey { ascending: true }`.
6. **Default** — `b TEXT DEFAULT 'x'` → `Default { value: StrLit("x") }`.
   `c INT DEFAULT (1+2)` → `Default { value: Binary(Plus, IntLit(1), IntLit(2)) }`.
7. **Check** — `a INT CHECK (a > 0)` produces a column-level
   `Check { expr: Binary(Gt, Col(a), IntLit(0)) }`. The CHECK form
   here MUST have parens — bare `CHECK expr` (no parens) is a
   ParseError.
8. **References** — `a INT REFERENCES p` →
   `References { table: "p", columns: [] }`. Optional `(c1, c2)`
   list. `ON DELETE` / `ON UPDATE` after produces
   `deferred: REFERENCES action`.
9. **Generated** — `c INT GENERATED ALWAYS AS (a + 1) STORED` →
   `Generated { expr, stored: true }`. `c INT AS (a + 1)` (shorthand)
   → `Generated { expr, stored: false }` (VIRTUAL default).
10. **Table-level constraints** — `CREATE TABLE t (a, b, PRIMARY KEY (a, b))`
    parses with `table_constraints: [PrimaryKey { columns: ["a","b"] }]`
    and two columns.
11. **Foreign key** — `FOREIGN KEY (a) REFERENCES p(c)` →
    `ForeignKey { columns: ["a"], ref_table: "p", ref_columns: ["c"] }`.
12. **Contextual STRICT / WITHOUT ROWID** — match the post-`)` ident
    text case-insensitively (`Strict`, `STRICT`, `strict` all match).
    Both options accepted in either order, comma-separated.
13. **Owned strings** — every string field in the AST is owned
    (copied from token's borrowed slice).
14. **Statement terminator** — stops BEFORE `;` or Eof; `next`
    points at the terminator token.
15. **Empty column list rejected** — `CREATE TABLE t ()` is a
    ParseError (`"expected column name"`).
16. **Deferred constructs are explicit** — `TEMP`, `AS SELECT`,
    `schema.t`, ON DELETE/UPDATE, DEFERRABLE each emit a
    `deferred: <construct>` ParseError. Parameterized type names
    (`VARCHAR(30)`, `DECIMAL(10, 2)`) are NOT deferred — they are
    admitted and captured in `ColumnDef.type_params` (see pin 19).
17. **Expression errors propagate** — DEFAULT / CHECK / GENERATED
    expression failures bubble up as-is.
18. **No inline tests, no invented helpers** — the file exports only
    `parse_create_table` plus the AST types declared in `shapes.json`
    and the per-clause sub-parsers (private, not exported).
19. **Parameterized type capture** — `a VARCHAR(30)` parses to
    `{ name: "a", type_name: Some("VARCHAR"), type_params: [30],
    constraints: [] }`; `b DECIMAL(10, 2)` to `type_params: [10, 2]`.
    The `type_name` string does NOT include the parens. Sibling
    consumers that don't care about width (CAST normalization,
    storage type-affinity) may treat ColumnDef as if `type_params`
    were empty; consumers that DO care (re-emission, ALTER TABLE
    cloning) round-trip the field.

## Regeneration envelope

- Line budget: **~400-600 lines** of Rust. The bulk is the column-
  constraint dispatch and the per-constraint sub-parsers.
- No dependencies beyond std.
- Public items: `CreateTableStmt`, `ColumnDef`, `ColumnConstraint`,
  `TableConstraint`, `CreateTableParseOk`, `parse_create_table`.

## Smoke probe

`src-rust/examples/ddl_parse_smoke.rs` (hand-written runner,
leaplint: runner) parses
`CREATE TABLE t (a INT PRIMARY KEY, b TEXT NOT NULL DEFAULT 'x', CHECK (a > 0))`
and asserts the AST shape via Debug substrings.
