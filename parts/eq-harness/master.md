---
name: eq-harness
kind: spec
---

# Cross-target equivalence harness

**Purpose.** First-class proof that the LEAP spec generates *equivalent*
implementations across targets. Given a single JSON golden-corpus entry
describing a VDBE program and its expected emitted rows, each target's
runner executes the program through its composed VDBE and emits the
rows it observed. The meta-runner diffs observed vs expected across
targets and fails if any target diverges.

This is the operational form of the LEAP flex: "Turso has one spec
(their Rust code). sqlite-leap has a neutral spec and N targets, same
corpus passes on all."

## Corpus format

Each corpus entry is a JSON object at
`parts/eq-harness/corpus/<name>.json`:

```json
{
  "name": "count_star_x3",
  "doc":  "Reset CountStar; step 3×; finalize into reg[0]; emit reg[0]; halt.",
  "program": {
    "num_registers":  1,
    "num_cursors":    0,
    "num_aggregates": 1,
    "num_windows":    0,
    "opcodes": [
      { "family": "Agg",  "op": "AggReset", "acc_slot": 0, "kind": "CountStar" },
      { "family": "Agg",  "op": "AggStep",  "acc_slot": 0, "kind": "CountStar",
                          "arg_reg": 0, "sep_reg": null },
      { "family": "Agg",  "op": "AggStep",  "acc_slot": 0, "kind": "CountStar",
                          "arg_reg": 0, "sep_reg": null },
      { "family": "Agg",  "op": "AggStep",  "acc_slot": 0, "kind": "CountStar",
                          "arg_reg": 0, "sep_reg": null },
      { "family": "Agg",  "op": "AggFinal", "acc_slot": 0, "kind": "CountStar",
                          "dest_reg": 0 },
      { "family": "Core", "op": "ResultRow", "start_reg": 0, "count": 1 },
      { "family": "Core", "op": "Halt" }
    ]
  },
  "expected_rows": [
    [ { "t": "Integer", "v": 3 } ]
  ]
}
```

### Opcode encoding

Each opcode is `{ "family": <Family>, "op": <Variant>, ...fields }`.
`family` ∈ {`Core`, `Rows`, `Scan`, `Expr`, `Agg`, `Window`, `Control`}
matches the flat `Opcode` compose declared in `parts/vdbe/shapes.json`.
`op` names the variant inside that family (e.g. `AggReset`, `Halt`).
Remaining keys are that variant's fields. Field names match the
variant declaration in the family's `shapes.json`.

### Value encoding

A `Value` is `{ "t": <Tag>, ...payload }`:

- `{ "t": "Null" }`
- `{ "t": "Integer", "v": <i64> }`
- `{ "t": "Real",    "v": <f64> }` — JSON number; NaN / Inf encode as
  strings `"NaN"`, `"Inf"`, `"-Inf"`.
- `{ "t": "Text",    "v": "<string>" }`
- `{ "t": "Blob",    "v": "<base64>" }`

### Expected rows

`expected_rows` is an array of rows; each row is an array of `Value`
in column order. A single row with a single `Integer(3)` looks like
`[ [ { "t": "Integer", "v": 3 } ] ]`.

## Per-target runner contract

Each target emits / hosts a runner binary that:

1. Reads a corpus file path from `argv[1]`.
2. Parses the JSON into the target's native `Program` + `Value`
   representations.
3. Constructs a `VdbeState` via the canonical
   `VdbeState.new(num_registers, num_cursors, num_aggregates,
   num_windows, db)` constructor.
4. Supplies a `row_sink` that appends each emitted row to an
   in-memory buffer (converted back to the canonical Value form).
5. Calls `execute_program(&program, &mut state)`.
6. On return, compares `observed_rows` to `expected_rows`.
7. Prints `OK` + exits 0 on match; prints diff + exits 1 on mismatch.

Runners are located at:

| Target | Path                                      |
|--------|-------------------------------------------|
| Rust   | `src-rust/examples/eq_runner.rs`          |
| Python | `src-python/eq_runner.py`                 |
| Go     | `src-go/cmd/eq_runner/main.go`            |
| Zig    | `src-zig/eq_runner.zig` (pending ctor)    |
| C      | `src-c/eq_runner.c`    (pending ctor)     |

Zig and C runners are blocked until the ctor schema lands in their
mapping passes; they currently have no external way to materialize a
`VdbeState`.

## Meta-runner

`parts/eq-harness/eqcheck.py <corpus_file>` invokes each available
runner with the corpus file, collects exit codes, and reports:

```
count_star_x3:
  rust    OK
  python  OK
  go      OK
  zig     SKIP (ctor schema pending)
  c       SKIP (ctor schema pending)
```

Meta-runner exits non-zero if ANY non-SKIP runner fails. The spec is
"every target agrees on every corpus entry"; silent skip is distinct
from failure but must be called out explicitly, never swallowed.

## Growth path

- **Phase C.0 (this):** 1 corpus entry × 3 runners → Integer(3)
  cross-target.
- **Phase C.1 (Zig / C ctor):** extend runners to 5 targets once the
  ctor schema ships mapping rules.
- **Phase C.2 (corpus breadth):** add entries for each opcode family's
  happy path. Per master.md §Correctness pins in each part, one
  positive and one negative entry per pin — at least for opcodes
  where neutral-spec semantics matter (NULL handling, DIV-zero, Rank
  vs DenseRank ties, aggregate empty-group rules).
- **Phase C.3 (SQL-level):** corpus entries sourced from the compiler
  emission — feed SQL through the future parser+compiler, record the
  resulting `Program`, use that as a corpus entry. At that point the
  harness becomes the continuous parity proof.
