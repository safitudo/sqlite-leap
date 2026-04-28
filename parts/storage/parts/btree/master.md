---
name: storage/btree
kind: leaf
inherits:
  - /parts/storage/parts/file-format/master.md
  - /parts/storage/parts/pager/master.md
emits:
  c: { path: src-c/storage/btree.c, headers: [src-c/storage/btree.h] }
  rust: { path: src-rust/src/storage/btree.rs }
---

# Part: storage/btree

Read-only framing of the B-tree shape: descent, cursor positioning,
and range scan. Mutation entry points (insert, update, delete, page
split / merge) are owned by `parts/storage/parts/btree-write/master.md`
(pin 19). This leaf documents the shared read-side machinery; the
write-side spec carries the dirty-bit propagation contract that pin 19
makes normative.

## Public interface

```
fn btree_insert(tree, key, value) -> Result<()>
fn btree_delete(tree, key) -> Result<()>
fn btree_seek(tree, key) -> Result<Option<Cursor>>
fn btree_scan(tree, direction) -> Cursor
fn btree_next(cursor) -> Result<Option<(key, value)>>
```

## Page splits and merges

When inserting into a full page, split at the midpoint. Promote
the split key to the parent; if parent full, recurse up. Splits
may grow the tree height.

Deletes may underflow a page below half-full; merge with a sibling
if possible. Root-collapse when the root becomes single-child.

## Cursor stability

Cursors may be invalidated by any write operation on the same
tree. Compiled programs MUST NOT perform a write and then
continue to read through a pre-existing cursor on the written
tree. Compiler enforces this invariant.

## Phase pins

- **Phase 113** — Rust multi-page index B-tree.
- **Phase 116** — C multi-page index B-tree.
- **#114** — Page-variant-bit correctness (file-format integration).

## Regeneration envelope

- Target leaf size: 800–1200 lines per target.
- Spec < 200 lines.
