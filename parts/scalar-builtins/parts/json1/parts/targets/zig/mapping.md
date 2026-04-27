# Target mapping: scalar-builtins/json1 — Zig

## Toolchain
- Zig 0.16
- `std.json` is available but its DOM model differs subtly from the
  spec's canonical output (object key order is hash-iteration in some
  versions). For canonical-output guarantees, hand-roll a parser that
  matches the spec exactly. Use `std.json.Parser` only as a validity
  check for `json_valid`.

## Module layout
- `src-zig/scalar_json1.zig`
- `JsonNode` as `union(enum) { null, bool: bool, integer: i64, real:
  f64, string: []const u8, array: []JsonNode, object: []ObjectEntry
  }`, all owned by an `Allocator` passed in.

## Allocator
Use a per-call `std.heap.ArenaAllocator` from
`std.heap.page_allocator`; deinit before returning.

## Float canonicalization
`std.fmt.format` with `{d}`, post-process to ensure `.0` for
integer-valued reals. Matches Rust/C rule.

## Error surfacing
`!Value` returns are caught in the dispatch wrapper and converted to
`Value.null`.
