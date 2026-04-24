---
name: storage/pager
kind: leaf
inherits:
  - /parts/io-backend/master.md
  - /parts/storage/parts/file-format/master.md
emits:
  c: { path: src-c/storage/pager.c, headers: [src-c/storage/pager.h] }
  rust: { path: src-rust/src/storage/pager.rs }
---

# Part: storage/pager

Page cache, dirty-page tracking, page eviction. Absorbs v1
`spec/pager-async.spec.md`.

## Public interface

```
fn pager_get_page(page_id) -> Result<&Page>
fn pager_get_page_mut(page_id) -> Result<&mut Page>  // marks dirty
fn pager_new_page() -> Result<PageId>
fn pager_free_page(page_id) -> Result<()>
fn pager_flush() -> Result<()>
```

## Pager dirty-set (Phase 4b)

The snapshot-diff v1 dirty-set is the authoritative tracker:

- On `begin_session`, snapshot the current page-image set.
- On each `get_page_mut`, mark the page dirty in a per-session set.
- On `commit`, hand the dirty set (+ current page images) to
  `storage/wal` for frame emission.
- On commit-or-rollback, reset dirty set to empty.

v1's single-bool `dirty` flag is replaced; the new structure is a
page-granular set. The snapshot-diff approach was chosen over
write-barrier interception because it requires no changes to
`btree`'s write path.

## Cache eviction

LRU with dirty-page pinning: dirty pages are never evicted until
commit or rollback. Clean pages evict at configurable threshold
(default: 2000 pages = ~8 MB).

## Phase pins

- **Phase 4b** — pager dirty-set (snapshot-diff v1) for WAL frame
  emission.

## Regeneration envelope

- Target leaf size: 400–700 lines per target.
- Spec < 150 lines.
