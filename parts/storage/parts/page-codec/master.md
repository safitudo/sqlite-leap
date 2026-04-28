---
name: storage/page-codec
kind: leaf
shapes: ./shapes.json
inherits:
  - /parts/storage/parts/file-format/master.md
emits:
  rust:   { path: src-rust/storage/page_codec.rs }
  c:      { path: src-c/storage/page_codec.c, headers: [src-c/storage/page_codec.h] }
  zig:    { path: src-zig/storage/page_codec.zig }
  go:     { path: src-go/storage/page_codec.go }
  python: { path: src-python/storage/page_codec.py }
---

# Part: storage/page-codec — page byte encoders (Pin 19b)

Pin 19b. Library leaf that owns the **page-byte encoding helpers**
currently embedded in `parts/storage/parts/fileformat-write/`. The
existing helpers (`encode_cell`, `build_leaf_page`,
`build_interior_table_page`, `encode_varint_be`, `serial_type_for`,
`usable_size`) are pure byte-shape functions: they take row data and
emit on-disk page bytes. Both runner-mode `fileformat-write` and
library-mode `btree-write` (Pin 19) need to call them; embedding
them in the runner forces `btree-write` to either re-emit or
duplicate the byte semantics. Pin 19b says: extract once, import
twice.

This is **a lift, not a redesign**. The byte semantics are already
specified — and proven byte-identical across 5 targets, see
`projects/2026-04-25 5-target fileformat byte-identity` — by
`fileformat-write/master.md`. This part claims the surface; sibling
regen at Phase 19b.1 / 19b.2 moves the function bodies.

## Why this part exists

Two distinct call sites need the same encoders:

1. **Runner mode** — `fileformat-write` builds a complete `.db` byte
   blob from a Database snapshot, atomic-writes it. Used today by
   the 5-target byte-identity probe and the L4 INSERT bench's
   serialize-and-rename path.
2. **Library mode** — `btree-write` (Pin 19) calls the encoders
   per-page during in-place mutation: a leaf split needs to
   `build_leaf_page` for the left and right halves, an insert
   without split needs `encode_cell` to splice one cell into a
   live page image. Btree-write is not a runner; it has no
   `main`; it returns page images to its caller (`pager_*`).

A library leaf is the correct shape: pure functions, no I/O, no
allocator beyond the returned byte buffer, declared once in the
shape, imported by both consumers via `inherits:`.

## Public surface

All functions are pure. No global state, no I/O, no clock, no
randomness. Inputs determine outputs byte-for-byte.

```
encode_varint_be(v: u64)                                 -> blob
serial_type_for(value: Value)                            -> u64
encode_cell(rowid: i64, values: list<Value>)             -> blob
build_leaf_page(
    page_size: u32, reserved_space: u8,
    cells: list<(i64, list<Value>)>,
    is_page_one: bool,
)                                                        -> blob[page_size]
build_interior_table_page(
    page_size: u32, reserved_space: u8,
    children: list<(u32, i64)>,        # (left_child_pn, sep_rowid)
    rightmost_child_pn: u32,
    is_page_one: bool,
)                                                        -> blob[page_size]
usable_size(page_size: u32, reserved_space: u8)          -> u32
```

Per-function semantics defer to the canonical sections in
`fileformat-write/master.md` — see the Byte semantics table below.

## Byte semantics

This part **does not restate** the byte layouts. Each helper's
contract is fixed by the existing canonical text in
`/parts/storage/parts/fileformat-write/master.md`:

| Function                       | Canonical spec                                                    |
|--------------------------------|-------------------------------------------------------------------|
| `encode_varint_be`             | `fileformat-write/master.md` §"Varint encode"                     |
| `serial_type_for`              | `fileformat-write/master.md` §"Integer serial-type picker"        |
| `encode_cell`                  | `fileformat-write/master.md` §"Encode cell (leaf table)"          |
| `build_leaf_page`              | `fileformat-write/master.md` §"build_leaf_page"                   |
| `build_interior_table_page`    | `fileformat-write/master.md` §"build_interior_table_page"         |
| `usable_size`                  | `fileformat-write/master.md` §"Usable size — the reserved-space byte" |

The body of those sections is the contract. Pin 19b's sibling regen
moves the function bodies into this leaf's emission; the prose
stays where it lives today. If the prose ever needs to move, that
is a follow-up cleanup pin — not part of 19b.

## Numbered Correctness pins

**PC-1. Byte-identity preserved across the extraction.** The
cross-target byte-identity bench (`parts/eq-harness` /
`demo_5target_stunt.sh` SHA1 5/5 match on the 5000-row split fixture)
MUST stay green after Phase 19b.1 lands. Any divergence — even a
single byte — fails this pin. The pre-extraction SHA1
(`fef632262aa...` per
`projects/2026-04-25 5-target multi-page split`) is the load-
bearing witness; post-extraction SHA1 must equal it.

**PC-2. Pure functions, no side channels.** No I/O syscalls, no
clock reads, no `random`/`rand`/`urandom`, no global mutable
state, no thread-local state. The only allocation permitted is the
returned `blob`. A second call with the same arguments returns
byte-identical output.

**PC-3. `usable_size` convention.** `usable_size(page_size,
reserved_space) = page_size - reserved_space`. Both
`build_leaf_page` and `build_interior_table_page` MUST start the
cell-packing cursor at `usable_size(page_size, reserved_space)`,
not at `page_size`. See `fileformat-write/master.md` lines 523-525
for the integrity_check failure mode if missed.

**PC-4. `encode_varint_be` covers the full u64 range.** Mainline
SQLite varints are up to 9 bytes for 64-bit unsigned values.
Implementations MUST handle the full `0..=u64::MAX` range and emit
the canonical narrowest encoding (no padding, no over-long form).
The 1-byte (≤ 0x7f) and 2-byte (≤ 0x3fff) fast-paths are
permitted; the 3..=9 byte path MUST be present.

**PC-5. `serial_type_for` is exhaustive over the Value variant
set.** Every variant declared on the canonical `Value` shape
(`/parts/core`) — Null, Integer, Real, Text, Blob — has a defined
mapping. If `Value` ever gains a new variant, this function fails
to compile until extended; the failure surface is intentional.
Targets MUST NOT introduce a `_default` arm that returns 0 (Null)
for unknown variants.

**PC-6. Stateless and re-entrant.** The same input produces the
same output regardless of call order, calling thread, or prior
calls. No memoization, no caching, no internal counters.
`encode_cell(42, [Integer(1)])` returns the same bytes on call 1
and call 1_000_000.

**PC-7. No new dependencies.** This leaf imports only `Value` and
`RuntimeCondition` from `/parts/core`. It does not depend on
`mem-store`, `pager`, `wal`, or any I/O part. The dependency arrow
points down: `fileformat-write` and `btree-write` depend on
`page-codec`; `page-codec` depends on nothing but core.

**PC-8. Generation scope.** Per `/spec/part-conventions.spec.md`
§"Generation scope" — no inline tests, no public helpers beyond
the 6 declared functions. File-private byte-poke helpers
(`write_u16_be`, `write_u32_be`, zero-fill, slice-copy) MAY exist
inside the emission file scoped target-private; they are not
declared in `shapes.json`.

## Generation scope

Standard `/spec/part-conventions.spec.md` §"Generation scope"
applies. This is a **library** leaf — runner exception does NOT
apply. No `main` / `__main__` / `fn main` entry points. The 6
functions above are the entire exported surface. Cross-target
byte-identity is verified by the existing `eq-harness` runner.

## Regeneration envelope

Estimated emission sizes per target (lifted from the existing
fileformat-write codec block):

| Target | Approx lines |
|--------|--------------|
| Rust   | 250 - 350    |
| C      | 400 - 500 (`.c` + `.h` combined) |
| Zig    | 300 - 400    |
| Go     | 350 - 450    |
| Python | 200 - 300    |

These are estimates. The acceptance signal is PC-1 (SHA1 match),
not line count.

## Phase pins

- **Phase 19b.1** — extract the codec helpers from fileformat-write
  into this leaf, sibling-regen 5/5. Acceptance: PC-1 SHA1 match
  holds; `demo_5target_stunt.sh` 7/7 PASS unchanged; corpus
  regression at parity with pre-extraction baseline (≥ 99.9%
  excl-SKIP on every target).
- **Phase 19b.2** — amend `fileformat-write/master.md` to import
  this part via `inherits:` and remove the helper bodies from its
  emission. The fileformat-write target leaves shrink by the
  extracted line count (~600 lines per target). Acceptance:
  byte-identity bench still 5/5; runner-mode `.db` writes
  unchanged byte-for-byte.
- **Phase 19** — `btree-write` consumes `page-codec` directly,
  unblocking in-place B-tree mutation. (Outside Pin 19b proper.)

The two phases are sequenced because Phase 19b.2 reduces
fileformat-write's emission to a thin orchestration layer; Phase
19b.1 must validate byte-identity before that reduction lands, so
a regression in 19b.1 is recoverable by reverting one part rather
than two.

## Smoke probe

Round-trip through the existing read path; no new runner needed:

1. Build a synthetic 10-row leaf via `build_leaf_page(4096, 0,
   cells, is_page_one=false)`.
2. Wrap it in a minimal 1-page `.db` (DbHeader + the leaf as
   page 1, regenerated with `is_page_one=true`).
3. Decode via `/parts/storage/parts/fileformat-read/`; assert
   all 10 rows recovered (rowid + values).
4. SHA1 the page bytes; compare across all 5 targets; MUST match.

The load-bearing acceptance test is the existing 5000-row split
byte-identity bench (`parts/eq-harness`), not this synthetic
probe. Probe is a fast smoke for Phase 19b.1 dispatch; bench is
the gate.

## Out of scope

- Cell **decoding** — owned by `/parts/storage/parts/fileformat-read/`.
- Index-btree pages (page-types 0x02 / 0x0A). v1 ships table-btree
  only (0x05 / 0x0D); index pages defer to Pin 19.3.
- Overflow pages. Today's fileformat-write asserts payloads fit
  in-page; pin 19b inherits that assumption verbatim.
- WAL frame headers — owned by `/parts/storage/parts/wal/`.
- Page-1 `DbHeader` encoding — owned by `/parts/storage/parts/file-
  format/`. This leaf treats page 1 as "ordinary leaf with a 100-byte
  reserved prefix" via `is_page_one`; it does not write the header.

## Open questions for follow-up

1. Should `serial_type_for` / `encode_varint_be` migrate to
   `file-format` (read/write-symmetric)? Pin 19b keeps them here
   because integer-narrowing is encode-specific. Revisit if a
   third caller materializes.
2. Cache-aware variant: a future `encode_cell_into(buf, offset,
   ...)` may join the surface to avoid a copy when in-place
   B-tree mutation lands (Pin 19).
