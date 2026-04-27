---
name: scalar-builtins/json1
---

# Part: scalar-builtins/json1

SQLite-compatible JSON1 extension surface as scalar functions. Twelve
functions covering construction, extraction, mutation, validation, and
RFC 7396 merge. The spec is language-neutral: every target implements
the same JSON parser, the same JSONPath evaluator, and the same
canonicalization rules.

The runtime opcode is `OpcodeExpr::Scalar` (see
`parts/vdbe/parts/opcodes-expr`), and these twelve functions ride the
existing `ScalarKind` enum as new variants. No new opcode kind. No new
shape. The compiler maps `Expr::Call` by lowercase name to the matching
`ScalarKind::Json…` variant; the runtime dispatcher routes to per-kind
handlers in this part.

## Function inventory

| Function                | ScalarKind variant | Arity     |
|-------------------------|---------------------|-----------|
| `json(text)`            | `JsonNorm`          | 1         |
| `json_array(...)`       | `JsonArray`         | 0..N      |
| `json_object(...)`      | `JsonObject`        | 0..N (even) |
| `json_extract(j, p, ...)` | `JsonExtract`     | 2..N      |
| `json_type(j[, p])`     | `JsonType`          | 1..2      |
| `json_valid(j)`         | `JsonValid`         | 1         |
| `json_array_length(j[, p])` | `JsonArrayLength` | 1..2  |
| `json_insert(j, p, v, ...)` | `JsonInsert`    | 3, 5, 7… |
| `json_replace(j, p, v, ...)` | `JsonReplace`  | 3, 5, 7… |
| `json_set(j, p, v, ...)`    | `JsonSet`        | 3, 5, 7… |
| `json_remove(j, p, ...)`    | `JsonRemove`     | 1..N     |
| `json_patch(target, patch)` | `JsonPatch`      | 2        |

## Correctness pins

1. **JSON model** — five node kinds: Null, Bool(true|false), Number
   (carrying either a 64-bit integer or 64-bit float), String (UTF-8),
   Array (ordered list of nodes), Object (ordered list of (key,node)
   pairs; insertion order preserved on output).

2. **JSON parser** — accepts the JSON grammar from RFC 8259. Whitespace
   between tokens is one-or-more of space, tab, LF, CR. Numbers parse
   to integer if they have no decimal point and no exponent and fit in
   signed 64 bits; otherwise to float. String escapes recognized: `\"`
   `\\` `\/` `\b` `\f` `\n` `\r` `\t` `\uXXXX`. Surrogate pairs
   `\uD8xx\uDCxx` decode to a single code point. Invalid input yields
   the `JsonInvalid` error condition.

3. **Canonical output** — every function that returns a JSON value
   returns it in the canonical text form:
   - Object keys quoted with `"`, separated from value by `:` (no
     space). Members separated by `,` (no space). Output order
     equals insertion order; mutating functions preserve original key
     order and append new keys at the end.
   - Array elements separated by `,` (no space).
   - Strings quoted with `"`, escaping `"`, `\`, control chars
     (`\u00xx` for U+0000..U+001F), with `\b \f \n \r \t` short forms.
   - Numbers: integer-valued numbers without exponent or decimal print
     as their decimal integer form. Float numbers print with enough
     precision to round-trip (`%.17g`-equivalent, trailing zeros after
     decimal trimmed except keep at least one digit after `.`; `1.0`
     stays `1.0`).
   - Null/Bool: `null`, `true`, `false`.

4. **JSONPath grammar** (subset, sufficient for the v1 stunt):

   ```
   path     := "$" segment*
   segment  := "." key | "[" index "]"
   key      := identifier  | quoted-string
   identifier := [A-Za-z_][A-Za-z0-9_]*
   index    := signed-integer
   ```

   Negative indices count from the end (`-1` is the last element).
   A path that does not start with `$` is an error (`JsonInvalidPath`).

5. **Path evaluation** — start at the root node. For each segment:
   - `.key`: target must be an object; result is the value at `key`,
     or `Missing` if absent. Targeting a non-object yields `Missing`.
   - `[i]`: target must be an array; result is element at `i` (or
     `len + i` if `i < 0`); `Missing` if out of range. Targeting a
     non-array yields `Missing`.

6. **NULL propagation** — every function returns SQL `NULL` if its
   first JSON argument is SQL `NULL`. `json_array` and `json_object`
   are the exceptions: they construct, so a `NULL` SQL argument
   becomes JSON `null` inside the result, never propagating to the
   whole call.

7. **`json(text)`** — parse and re-serialize in canonical form.
   Returns `Value::Text` of the canonical JSON. Invalid input → SQL
   `NULL` (SQLite behavior is actually error, but for v1 we surface
   invalid input as `NULL` to keep the dispatcher Halt-free; promote
   to a hard error in a follow-up).

8. **`json_array(v0, v1, ...)`** — build a JSON array from the SQL
   arguments. Mapping:
   - SQL `Null` → JSON `null`
   - SQL `Integer` → JSON number (integer form)
   - SQL `Real` → JSON number (float form)
   - SQL `Text` → JSON string. **Special rule**: if the text starts
     with `[` or `{` and parses as valid JSON, it is embedded as the
     parsed JSON node; otherwise it is embedded as a JSON string.
     This mirrors mainline SQLite's "json type detection" behavior
     for nested calls (e.g. `json_array(json_array(1))`).
   - SQL `Blob` → JSON string with the raw bytes interpreted as
     UTF-8 (replacement char on invalid).

9. **`json_object(k0, v0, k1, v1, ...)`** — odd argument count is an
   error (`JsonInvalidArgs`); v1 surfaces it as `NULL`. Each `k_i`
   must be `Text`; non-text key → coerce via canonical text rendering.
   Values follow the same SQL→JSON rules as `json_array`.

10. **`json_extract(j, p1[, p2, ...])`** — parse `j`, evaluate every
    path. With one path: return the addressed value as SQL value
    (JSON `null`→SQL `Null`; JSON `true|false`→`Integer(1|0)`;
    JSON number→`Integer` or `Real`; JSON string→`Text`; JSON
    array/object→canonical text). Missing path → SQL `Null`. With
    multiple paths: return a JSON array of the addressed values
    (canonical text), where missing paths contribute JSON `null`.

11. **`json_type(j[, p])`** — return one of: `"null" | "true" |
    "false" | "integer" | "real" | "text" | "array" | "object"`.
    Missing path → SQL `Null`. Non-JSON input → SQL `Null`.

12. **`json_valid(j)`** — `Integer(1)` if `j` parses as JSON,
    `Integer(0)` otherwise. SQL `Null` input → `Integer(0)` (mainline
    quirk; v1 follows it).

13. **`json_array_length(j[, p])`** — array length as `Integer`.
    Non-array (or path missing) → `Integer(0)` if `j` parses, SQL
    `Null` if `j` does not parse.

14. **`json_insert(j, p, v, ...)`** — for each (path, value) pair, if
    the path does NOT exist, insert. Inserting into an array out of
    range appends. Inserting where the parent does not exist is a
    no-op for that pair (matches SQLite). The first arg `j` is the
    target document, returned in canonical form.

15. **`json_replace(j, p, v, ...)`** — for each (path, value) pair,
    if the path EXISTS, replace. Otherwise no-op for that pair.

16. **`json_set(j, p, v, ...)`** — for each pair, set: insert if
    missing, replace if present.

17. **Value embedding rule for insert/replace/set/array/object**:
    when the value comes from an SQL `Text` whose content parses as a
    JSON array or object (starts with `[` or `{`), embed the parsed
    structure rather than a quoted string. Rationale: lets users
    nest JSON without manual `json()` wrapping.

18. **`json_remove(j, p, ...)`** — for each path, delete the
    addressed node. Removing array elements shifts subsequent
    elements left. Missing path → no-op. Path `$` (root) is an
    error → SQL `Null`.

19. **`json_patch(target, patch)`** — RFC 7396 merge. Both inputs
    parsed as JSON. If `patch` is not an object, the result is
    `patch` (verbatim). Else for each (k, v) in patch:
    - if `v` is `null`: delete `k` from target (if target is an
      object); if target is not an object, replace target with an
      empty object first.
    - else: recursively patch `target[k]` with `v` (creating
      `target[k]` as `null` first if missing).

20. **Error conditions** (closed set, all surface as SQL `Null` in
    v1 — promote to `RuntimeCondition` in a follow-up):
    `JsonInvalid`, `JsonInvalidPath`, `JsonInvalidArgs`,
    `JsonRootRemove`.

## Generation scope

This part is a leaf — no sub-parts. Each target's `mapping.md`
specifies how the target maps the spec onto its language: which
stdlib JSON parser (if any) it uses, how it canonicalizes output,
and which integer/float promotion rule it applies.

The 12 new `ScalarKind` variants must be added to
`parts/vdbe/parts/opcodes-expr/shapes.json` and their compiler
name→kind mapping to `parts/compiler/parts/expr-compile`. This is a
**spec edit**, not target-local: a single coordinated change across
those two parts.
