---
name: storage/file-format
kind: leaf
inherits:
  - /spec/memory-discipline.spec.md
emits:
  c: { path: src-c/storage/file_format.c, headers: [src-c/storage/file_format.h] }
  rust: { path: src-rust/src/storage/file_format.rs }
---

# Part: storage/file-format

On-disk byte layout. Absorbs v1 `spec/file-format.spec.md`.
Bidirectional compatibility with mainline SQLite's file format 3
is a hard requirement — a LEAP-written DB must be readable by
mainline, and vice versa.

## Reference

SQLite's published file-format documentation
(https://sqlite.org/fileformat2.html) is the authoritative external
spec. This sub-part's master.md does NOT restate it in full;
instead, it fixes LEAP-specific choices within the permitted
latitude.

## Fixed choices (v2)

- **Page size**: 4096 bytes. (SQLite permits 512–65536; LEAP is
  fixed at 4096 for v2.)
- **Text encoding**: UTF-8.
- **Write version**: 2 (WAL).
- **Read version**: 2.
- **Reserved space per page**: 0 bytes (full 4096 usable).

## Page types

- **Header page** (page 1): standard 100-byte SQLite header +
  schema b-tree root.
- **Table b-tree pages**: interior + leaf, variant bits per SQLite
  spec.
- **Index b-tree pages**: interior + leaf.
- **Overflow pages**: for rows larger than ~1/4 page size.
- **Free-list pages**: reused after DROP / DELETE.

## Varint encoding

SQLite's huffman-style 1–9 byte varint. Used for rowids, record
headers, serialized type tags. Encode/decode routines are owned
by this sub-part.

## Record format

Serialized row: (header-size-varint)(type-codes-varint-list)(value-bytes).
Type codes map {NULL, INTEGER, REAL, TEXT, BLOB} to a compact
encoding per the SQLite spec.

## Roundtrip fuzz corpus

`tests/fuzz/file-format/roundtrip_campaign.py` generates random
schemas + row values; writes via LEAP; reads via mainline; writes
via mainline; reads via LEAP; asserts byte-identical reads. 900/900
green at v1 freeze. v2 inherits this corpus.

## Phase pins

- **Phase 91** — File-format compat (SQLite→LEAP reading gap).
- **#114** — C leap writes corrupt indexes (fixed by B-tree
  variant-bit correctness).
- **#133** — C record-level aggregate value-mismatches (serialized
  type-tag consistency).

## Regeneration envelope

- Target leaf size: 600–1000 lines per target.
- Spec < 200 lines.
