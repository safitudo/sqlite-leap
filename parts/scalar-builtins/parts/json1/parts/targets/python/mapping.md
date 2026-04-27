# Target mapping: scalar-builtins/json1 — Python

## Toolchain
- CPython 3.11+
- `json` from stdlib MAY be used for parsing AND validity, with two
  caveats:
  1. Pass `object_pairs_hook=list` to preserve insertion order.
  2. Distinguish int vs. float on output (`json.dumps` already does).
  Hand-rolling is also acceptable; the spec's canonical writer is
  small enough either way.

## Module layout
- `src-python/scalar_json1.py`
- `JsonNode` as Python tagged tuples `("null",)`, `("bool", b)`,
  `("int", i)`, `("real", f)`, `("str", s)`, `("arr", [nodes])`,
  `("obj", [(k, node), ...])`. Tuples are cheap and immutable;
  the writer pattern-matches on `node[0]`.

## Float canonicalization
`repr(f)` for the shortest-roundtrip representation. Append `.0` if
neither `.` nor `e` appears.

## Error surfacing
Module-private `JsonError` exception caught at the dispatch
boundary and converted to `Value(kind="null", v=None)`.
