# Phase 6bk harness — WINDOW functions (ROW_NUMBER + simple OVER)

Introduces the `OVER` clause with `ROW_NUMBER()` as the single window function in v1. Supports `OVER (ORDER BY …)` and `OVER (PARTITION BY … ORDER BY …)`. No explicit frame spec. New reserved keywords `KEYWORD_OVER`, `KEYWORD_PARTITION`, `KEYWORD_WINDOW` (latter reserved for future `WINDOW clause-name AS (…)` — parsed-and-rejected). One new aggregate-like function name `ROW_NUMBER`.

Gate: 7 fixtures green both targets. `SUMMARY phase=6bk target=<c|rust> passed=7 failed=0 total=7`.

### Grammar extension

```
function-expr := IDENTIFIER LPAREN [ expression-list ] RPAREN [ over-clause ]
over-clause   := KEYWORD_OVER LPAREN [ partition-clause ] [ order-by-clause ] RPAREN
partition-clause := KEYWORD_PARTITION KEYWORD_BY expression ( COMMA expression )*
```

`ROW_NUMBER()` must appear with an `OVER (…)` clause; bare `ROW_NUMBER()` → `COMPILE_WINDOW_FUNCTION_WITHOUT_OVER`.

### Semantics

- Implementation is sort-and-scan:
  1. Materialize the SELECT's row set into an intermediate buffer.
  2. If `PARTITION BY` present, group rows by the partition expression tuple; else one partition.
  3. Within each partition, sort by the `ORDER BY` expression list; emit `ROW_NUMBER()` as the 1-based position within the sorted partition.
  4. The outer SELECT's own ORDER BY is applied after the window pass.
- No frame clause: ROW_NUMBER is frame-independent (its value is determined by partition + order alone).
- Multiple window functions on the same OVER spec in one SELECT share the sort; different OVER specs run independent sort passes. v1 fixture suite uses only a single OVER per query.
- Interaction with aggregates: window functions run AFTER GROUP BY aggregation in v1 (i.e., on aggregated rows). Mixing GROUP BY + window is out of scope for v1 fixtures.

### Errors

- `COMPILE_WINDOW_FUNCTION_WITHOUT_OVER { function }` — e.g., bare `ROW_NUMBER()` without OVER.
- `COMPILE_UNSUPPORTED_WINDOW_FUNCTION { function }` — any window function name other than `ROW_NUMBER` in v1. (RANK, DENSE_RANK, LAG, LEAD, NTILE, SUM() OVER, COUNT() OVER → this error in v1; broadened in later phases.)
- `COMPILE_UNSUPPORTED_WINDOW_FRAME` — reserved for when a frame clause (ROWS/RANGE/GROUPS BETWEEN …) is syntactically present. v1 fixtures do not exercise this path but parser must reject the frame syntax if it appears.

### Implementation

- Parser: `function-expr` optionally consumes an OVER clause following the closing RPAREN of the function call.
- AST: new node `WindowSpec { partition_by: Vec<AstExpr>, order_by: Vec<OrderKey> }`. Function-call node gains `window: Option<WindowSpec>`.
- Compile: when a SELECT contains a window-function reference, emit a second pass: sort + group-scan + row-number-counter. VDBE: reuses SortInit / SortStep / SortFinal from ORDER BY path; counter lives in a new register; resets on partition change (partition-change detected by equality-compare of partition tuple against previous row's tuple).
- No new opcodes required if SortInit/SortStep/SortFinal + existing Add and Move suffice; if a gap appears the generator may propose `WindowReset`/`WindowRowNumber` additions (cross-corroboration: if both agents independently invent the same opcode name, canonize in spec).

### Non-goals (v1)

- RANK, DENSE_RANK, LAG, LEAD, NTILE, FIRST_VALUE, LAST_VALUE, NTH_VALUE, aggregate-OVER (SUM/COUNT/etc. with OVER).
- Explicit frame clauses (ROWS/RANGE/GROUPS BETWEEN).
- Named windows via top-level `WINDOW w AS (…)` clause — parsed and rejected.
- Multiple OVER specs in one SELECT sharing a common WINDOW clause — v1 fixtures use only single OVER.
