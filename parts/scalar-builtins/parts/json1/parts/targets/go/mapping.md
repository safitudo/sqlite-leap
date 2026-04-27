# Target mapping: scalar-builtins/json1 — Go

## Toolchain
- Go 1.22+
- `encoding/json` decodes to `interface{}` but loses original key
  order (uses a `map[string]interface{}`). For canonical-output
  guarantees, hand-roll the parser using only `unicode/utf8` and
  `strconv`. `encoding/json.Valid` may be used for `json_valid`.

## Module layout
- `src-go/scalar_json1.go`, package `vdbe` (sibling to existing
  scalar dispatch).
- `JsonNode` as a sealed interface implemented by `jsonNull`,
  `jsonBool`, `jsonInt`, `jsonReal`, `jsonStr`, `jsonArr`, `jsonObj`
  (the last carries `[]struct{Key string; Val JsonNode}` for order).

## Float canonicalization
`strconv.FormatFloat(f, 'g', 17, 64)`, then ensure `.0` suffix when
neither `.` nor `e` appears.

## Error surfacing
Internal `error` returns are caught at the dispatch boundary and
converted to `Value{kind: ValNull}`.
