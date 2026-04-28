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

## Pager dirty-set (pin 19)

The page cache's per-entry `dirty` bit is the authoritative tracker:

- On each `pager_get_page_mut(p, page_no)`, the cache marks that page
  dirty (page-cache pin 13). Cursor write paths in
  `parts/storage/parts/btree-write/master.md` go through this entry
  point exclusively — there is no path that mutates a page image
  without setting the bit.
- On `pager_commit_transaction`, `cache.flush_dirty()` returns the
  dirty pages in ascending `page_no` order and clears their bits;
  WAL frames are appended in that order.
- On `pager_rollback_transaction`, `cache.clear()` drops every
  in-memory page image; subsequent `pager_get_page` re-faults from
  disk-or-WAL.

The pre-pin-19 snapshot-diff design is retired: the page cache's
per-entry dirty bit subsumes it, and cursor writes are responsible
for honoring the boundary by routing through `pager_get_page_mut`.

## Cache eviction

LRU with dirty-page pinning: dirty pages are never evicted until
commit or rollback. Clean pages evict at configurable threshold
(default: 2000 pages = ~8 MB).

## Phase pins

- **Phase 4b** (deprecated; superseded) — pager dirty-set
  (snapshot-diff v1). Replaced at pin 19 by per-page dirty tracking
  in the page cache; cursor writes route through
  `pager_get_page_mut` per `parts/storage/parts/btree-write/master.md`.

## Regeneration envelope

- Target leaf size: 400–700 lines per target.
- Spec < 150 lines.
