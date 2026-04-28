# Pin 19 — Migration notes

Companion to `master.md`. Lists the parts and concrete code sites that
require amendment **after** the btree-write leaf is canonical. The leaf
itself is the boundary; tree-wide migration is per-landing follow-up.

## Spec parts to amend (Pin 19.2 — spec-only landing)

1. `parts/storage/parts/wal-bridge/master.md` — drop the
   "Phase 18.1 limitation" stanza (lines 249–256), update the
   commit pseudo-code (lines 213, 216–217), update §"Recovery
   on open" (line 337), update §"Out of scope" line 445, update
   §"Phase pins" (lines 479–481).

2. `parts/storage/parts/wal-bridge/shapes.json` — update the
   `pager_commit_transaction` doc string (line 117) and remove
   the `encode_database_to_pages` function entirely (line 150);
   it is no longer part of the API.

3. `parts/storage/parts/mem-store/master.md` — pin 19 forward
   references at lines 365, 518, 535, 577 resolve. The text
   "pin 19's incremental B-tree page faulting" can become a
   back-reference to btree-write/master.md.

4. `parts/storage/parts/mem-store/shapes.json` — cursor doc
   strings at lines 160 and 197 update from
   "pin 19 will route the actual page write through it" to
   "pin 19 routes the page write through it".

5. `parts/storage/parts/pager/master.md` — §"Pager dirty-set
   (Phase 4b)" updates: the snapshot-diff v1 description is
   replaced by per-page dirty tracking via `pager_get_page_mut`.
   §"Cache eviction" already says "dirty pages are never evicted
   until commit or rollback" — no change.

6. `parts/storage/parts/btree/master.md` — currently a 52-line
   stub. Pin 19's carve-up: btree-write owns mutation entry
   points; btree remains the read-side facade (cursor_rewind,
   _next, _column descent helpers). Extend the stub with an
   explicit "read-only" framing line and a "see btree-write for
   mutations" cross-reference.

## Concrete code sites that change

7. `src-rust/storage_pager.rs:404-477` — the
   `pager_commit_transaction` body. Lines 413–428 (the
   `encode_database_to_pages` call + the dirty-put loop) drop in
   full; the surviving body is the `flush_dirty` →
   `wal_append_frame` loop already present (lines 437–448 in the
   current emission).

   After pin 19.1 the `encode_database_to_pages` symbol can also
   be removed from `src-rust/storage_wal.rs` and equivalents.

## Non-issues confirmed

- `parts/lib-api/parts/c-abi/master.md:447` and
  `parts/lib-api/parts/c-abi/shapes.json:194` reference "Pin 19"
  but those are **local** to c-abi (its own §Correctness pin 19
  about column-pointer ownership), not a forward reference to
  btree-write. No renumbering needed.
