---
name: storage/page-cache
kind: leaf
inherits:
  - /parts/storage/parts/pager/master.md
  - /parts/storage/parts/file-format/master.md
emits:
  rust:   { path: src-rust/page_cache.rs }
  c:      { path: src-c/storage/page_cache.c, headers: [src-c/storage/page_cache.h] }
  zig:    { path: src-zig/storage/page_cache.zig }
  go:     { path: src-go/storage/page_cache.go }
  python: { path: src-python/storage/page_cache.py }
---

# Part: storage/page-cache

A bounded, in-process LRU page cache layered between `storage/pager`
and the file-format reader/writer. Phase A.1 of the v1 production
roadmap. Single-process scope only — multi-process / shared-memory
variants are deferred to Phase A.2.

The cache is the **single source of truth for the live page image**
during a session: every pager read and every pager write goes
through the cache. The file-format layer is invoked only on a cache
miss (read) or on flush/checkpoint (write).

## State machine

A `PageCache` instance has the following state:

- `capacity: integer (page count)` — fixed at construction; `> 0`.
- `entries: map<PageId, CacheEntry>` — present pages.
- `lru_order: ordered list<PageId>` — most-recently-used at one end,
  least-recently-used at the other. Every key in `entries` appears
  exactly once in `lru_order`.

Each `CacheEntry` carries:

- `page: Page` — the byte image (page-sized buffer, refcounted so
  callers can hold a read view without a copy).
- `dirty: bool` — `true` iff the in-memory image differs from the
  on-disk image (i.e. there is an uncommitted write).
- `pinned: bool` — `true` iff eviction is currently forbidden for
  this page (used by the pager during cell mutation).

### Operations

1. `new(capacity)`: empty cache. Raises `CACHE_INVALID_CAPACITY` if
   `capacity == 0`.
2. `get(page_id)`: if `page_id` in `entries`, move it to MRU end of
   `lru_order` and return the page; else return *absent*.
3. `put(page_id, page, dirty)`: if `page_id` is already in
   `entries`, replace its `page` and `dirty`, move to MRU. Else,
   while `entries.size >= capacity` AND a clean unpinned victim
   exists at LRU end, evict it; then insert at MRU.
4. `mark_dirty(page_id)`: set `entries[page_id].dirty = true`. Raises
   `CACHE_PAGE_NOT_PRESENT` if absent.
5. `pin(page_id)` / `unpin(page_id)`: set/clear pinned flag. Raises
   `CACHE_PAGE_NOT_PRESENT` if absent.
6. `invalidate(page_id)`: if present, remove from both `entries`
   and `lru_order`. Idempotent on absent ids. Pinned pages MUST NOT
   be invalidated; raises `CACHE_PAGE_PINNED`.
7. `flush_dirty()`: return the list of `(page_id, page)` for every
   entry with `dirty == true`, in ascending `page_id` order. Clears
   the `dirty` flag on each returned entry. Does not evict.
8. `len() / capacity() / is_empty()`: query observers.
9. `peek(page_id)`: if `page_id` in `entries`, return the page
   image **without** moving the entry in `lru_order`; else return
   *absent*. Pin 19.1a perf bridge — used by write-path probes
   that need to inspect a page before deciding whether to consume
   it. Strictly read-only on LRU state.
10. `clear()`: drop every entry; `lru_order` becomes empty.

## LRU eviction discipline

The `lru_order` list is the sole eviction source-of-truth. On `get`
and `put`, the targeted page becomes MRU. On `put` when at capacity,
the eviction algorithm walks `lru_order` from the LRU end and
evicts the first entry whose `dirty == false` AND `pinned == false`.
If no such entry exists, the cache **may exceed capacity** for the
duration of the operation (correctness over strict bound). This is
the dirty-page-pinning rule established by the pager part.

## Numbered Correctness pins

1. `capacity == 0` is rejected at construction with
   `CACHE_INVALID_CAPACITY`.
2. After `put(p, …)` the entry for `p` is at the MRU end of
   `lru_order`.
3. After `get(p)` returning present, the entry for `p` is at the MRU
   end of `lru_order`.
4. After `get(p)` returning absent, `lru_order` is unchanged.
5. `entries.size == lru_order.length` at every observable boundary.
6. Eviction never selects a `dirty == true` entry.
7. Eviction never selects a `pinned == true` entry.
8. If every entry is dirty-or-pinned, `put` of a new page inserts
   without evicting (cache temporarily exceeds capacity).
9. `invalidate(p)` on a pinned `p` raises `CACHE_PAGE_PINNED` and
   leaves state unchanged.
10. `invalidate(p)` on an absent `p` is a no-op (returns *ok*).
11. `flush_dirty` returns entries in ascending `page_id` order;
    after the call, every returned entry has `dirty == false`.
12. `flush_dirty` does not change `lru_order` or remove entries.
13. `mark_dirty` on absent page raises `CACHE_PAGE_NOT_PRESENT`.
14. `clear()` returns the cache to its post-`new` state (size 0,
    empty order). Used on transaction rollback by the pager.
15. `pin` / `unpin` are idempotent: setting `pinned` to its current
    value is allowed and does not raise.
16. `Page` is a refcounted byte buffer; `get` returns a clone of the
    refcount handle, never a deep copy.

## Pager integration (informative — owned by `storage/pager`)

- `pager_get_page(p)`: cache.get(p) → on hit, return; on miss, read
  via file-format, cache.put(p, image, dirty=false), return.
- `pager_get_page_mut(p)`: cache.get + cache.mark_dirty.
- `pager_free_page(p)`: cache.invalidate(p).
- Commit / checkpoint: pager calls `flush_dirty`, hands the result
  to `storage/wal` for frame emission, retains entries (they remain
  cached, now clean).
- Rollback: pager calls `clear()` (page images regenerate from disk
  on next read).

## Out of scope (Phase A.2+)

- Cross-process shared memory (mmap'd cache region).
- Prefetch / read-ahead.
- Write-back coalescing.
- NUMA-aware sharding.
- Cache statistics export (hit/miss counters) — added in observability
  phase.

## Regeneration envelope

- Spec ≤ 150 lines.
- Target leaf size: 200–350 lines per target.
