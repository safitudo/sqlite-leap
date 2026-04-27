---
name: storage/triggers
kind: leaf
emits:
  rust: { path: src-rust/storage/triggers.rs }
  c:    { path: src-c/storage/triggers.c, headers: [src-c/storage/triggers.h] }
---

# Trigger storage / registry

Owns the per-database registry of trigger definitions. Every
trigger created by `CREATE TRIGGER` is registered here; the
compiler consults this registry every time it lowers a DML
statement to discover matching triggers; `DROP TRIGGER` (and
`DROP TABLE` cascade) remove entries here.

This is a STORAGE part, not a compiler part: it owns lifetime,
ordering, persistence, and existence semantics. It does NOT lower
trigger bodies — that is the compiler's job — and it does NOT parse
the body — that is the parser's job. It stores the parsed AST as a
borrow-stable record and returns lists of references on lookup.

The persistent counterpart of this registry is the
`sqlite_master` / `sqlite_schema` row whose `type='trigger'`. v1
mem-store backs the registry with an in-memory list; the
btree-backed real storage part (follow-up) reconstitutes it by
re-parsing the schema rows on database open.

## Public interface

```
register_trigger(
    db:  mut Database,
    stmt: CreateTriggerStmt,
) -> result<unit, StorageCondition>

unregister_trigger(
    db:        mut Database,
    name:      borrow string,
    if_exists: bool,
) -> result<unit, StorageCondition>

list_triggers_for_table(
    db:    borrow Database,
    table: borrow string,
) -> borrow list<CreateTriggerStmt>

list_all_triggers(
    db:    borrow Database,
) -> borrow list<CreateTriggerStmt>

drop_table_cascade(
    db:    mut Database,
    table: borrow string,
) -> u32
```

`drop_table_cascade` returns the number of triggers removed.
Called by the storage layer's DROP TABLE path (NOT by the parser
or compiler) so that the registry stays consistent with the
catalog.

## Storage shape

```
TriggerEntry {
    stmt: CreateTriggerStmt,    # owned AST, parsed
    creation_ordinal: u64,      # monotonic counter, registration order
    enabled: bool,              # for future PRAGMA disable_triggers; v1 always true
}

# Database (defined in /parts/storage/parts/mem-store) gains:
# triggers: list<TriggerEntry>
```

The list is kept in `creation_ordinal` order; lookups filter
in-place. v1 does not index by table name — the linear scan is
expected to dominate registration time, not lookup-per-DML time
(a large schema could justify a per-table index in a follow-up
part; flagged here as a candidate optimisation, not a v1
requirement).

## Persistence

`register_trigger` MUST also write the canonical
`sqlite_master` / `sqlite_schema` row for the trigger:

```
{ type: "trigger", name: <stmt.name>, tbl_name: <stmt.table>,
  rootpage: 0, sql: <reconstructed CREATE TRIGGER text> }
```

Reconstruction of the CREATE TRIGGER text from the AST is owned by
`/parts/parser/parts/create-trigger-stmt/` (a follow-up
`reconstruct_sql` function — out of scope this round; v1 may store
the original token range from the parser instead).

On database open, the storage layer re-tokenises and re-parses
each trigger row and calls `register_trigger` to repopulate the
in-memory registry. Re-registration uses the SAME
`creation_ordinal` (read from the schema row's rowid) so that
firing order is stable across restart.

## Lookup semantics

`list_triggers_for_table(db, "t")` returns a borrowed list of
references in `creation_ordinal` order. The compiler filters this
list further by `(event, timing)` (see
`/parts/compiler/parts/triggers/`). Borrowed lifetime is the
duration of one DML compilation; the registry MUST NOT be mutated
mid-compilation (the storage layer enforces this via the
connection's compile-time mutex).

## Correctness pins

1. **register_trigger appends, never overwrites silently** — if a
   trigger named `n` already exists and the `CreateTriggerStmt`
   carries `if_not_exists == false`, raise
   `StorageCondition::TriggerAlreadyExists`. With `if_not_exists ==
   true`, the second register is a no-op (returns Ok).
2. **Creation ordinal is monotonic** — each successful
   `register_trigger` increments a per-database counter; the new
   entry's ordinal is the post-increment value. Counter persists
   across `unregister_trigger` (i.e. ordinals are not reused).
3. **list_triggers_for_table returns creation order** —
   guaranteed; the compiler relies on this for mainline-compatible
   firing order.
4. **list_triggers_for_table is name-exact** — no case folding,
   no schema-qualifier handling. Case-insensitive matching is a
   downstream policy applied by the compiler's name-resolution
   pass (which already does case-folding for table refs).
5. **unregister_trigger missing name with if_exists=false** —
   raises `StorageCondition::TriggerNotFound`. With `if_exists=true`,
   it is a no-op (returns Ok).
6. **unregister_trigger removes from BOTH the in-memory list AND
   the sqlite_master row** — atomic in the same transaction; if
   either side fails, the operation rolls back.
7. **drop_table_cascade removes every trigger whose `stmt.table`
   matches** — exact match, name-exact (same case rule as pin 4).
   Returns the count for the caller's diagnostics.
8. **drop_table_cascade leaves no orphan schema rows** — every
   removed in-memory entry is paired with a removed
   `sqlite_master` row.
9. **Connection-shared visibility** — registered triggers are
   visible to every connection on the same database once the
   creating transaction commits. Pre-commit visibility is governed
   by the WAL/pager part's snapshot isolation rules; this part
   only specifies that an entry exists in the registry once and is
   visible to callers after their transaction sees the
   sqlite_master row.
10. **Trigger AST is owned at registration** — `register_trigger`
    consumes the `CreateTriggerStmt` and stores it. Subsequent
    lookups return references INTO the registry; the AST does NOT
    move per-lookup.
11. **Empty-name rejected** — `stmt.name == ""` is
    `StorageCondition::InvalidTriggerName`. The parser already
    rejects this at parse time, but the storage layer also checks
    so that the contract is independent of the caller.
12. **Distinct trigger names per database** — uniqueness is
    on the trigger NAME alone, NOT on `(name, table)`. SQLite does
    not allow two triggers of the same name even on different
    tables.
13. **Persistence boundary** — `register_trigger` and
    `unregister_trigger` are synchronous w.r.t. the journal /
    WAL: a successful return implies the schema row is durable
    according to the prevailing `synchronous` PRAGMA setting.
    Crash recovery on database open replays the schema rows and
    rebuilds the registry from scratch.
14. **No interpretation of trigger semantics** — this part does
    NOT evaluate WHEN, does NOT enforce OLD/NEW availability, does
    NOT enforce INSTEAD-OF-only-on-views. It is a pure registry.
    All those rules live in `/parts/compiler/parts/triggers/`.
15. **Borrow-stable lookup return** — `list_triggers_for_table`
    returns a borrowed slice into the registry. The storage
    layer MUST hold the connection's compile mutex for the
    duration of that borrow so that a concurrent
    `register_trigger` / `unregister_trigger` cannot invalidate
    it. Targets implement the borrow with their idiomatic
    aliasing primitive (Rust slice borrow, C pointer + length,
    etc.) — none of that detail leaks into the spec.
16. **Errors as named conditions** — `TriggerAlreadyExists`,
    `TriggerNotFound`, `InvalidTriggerName` are variants of the
    existing `StorageCondition` enum (not a new error type).
17. **TEMP triggers** — `stmt.is_temp == true` triggers persist
    in a separate temp catalog (the temp database's
    sqlite_temp_master). Their visibility is connection-local;
    they do NOT survive connection close. v1 mem-store treats
    `is_temp` as advisory (records the flag, scopes lookup the
    same as non-temp). The btree-backed storage part is
    responsible for the temp-catalog split.
18. **No inline tests, no invented helpers** — exports only the
    five functions named above and the `TriggerEntry` record. No
    auxiliary scan helpers, no SQL re-tokenisation entry points
    here (those live in the parser and storage open paths).
19. **MAX_TRIGGERS guard** — at 65535 registered triggers per
    database, further `register_trigger` calls return
    `StorageCondition::TooManyTriggers`. This bound matches the
    schema-row rowid range used by the
    `creation_ordinal` mapping in v1.
20. **Concurrency contract** — `list_triggers_for_table` and
    `list_all_triggers` are read-only and may be called by any
    connection holding a compile lock. `register_trigger`,
    `unregister_trigger`, `drop_table_cascade` MUST be called
    under a write lock; their effects are visible to subsequent
    readers in this connection's transaction immediately, to
    other connections only after commit (per pin 9).

## Regeneration envelope

- Target leaf size: 250–450 lines per target.
- Spec under 200 lines.
- Public items: `TriggerEntry`, `register_trigger`,
  `unregister_trigger`, `list_triggers_for_table`,
  `list_all_triggers`, `drop_table_cascade`, plus the named
  StorageCondition variants.

## Smoke probe (out of scope this round — to be added when emission lands)

A future hand-written smoke should cover:

```text
1. register tr1 on t (AFTER INSERT) → list_triggers_for_table("t")
   returns [tr1].
2. register tr2 on t (BEFORE UPDATE) → returns [tr1, tr2] in order.
3. register tr1 again with if_not_exists=false →
   StorageCondition::TriggerAlreadyExists.
4. register tr1 again with if_not_exists=true → Ok, no duplicate.
5. unregister tr1 → list now [tr2].
6. unregister tr1 again with if_exists=false →
   StorageCondition::TriggerNotFound.
7. drop_table_cascade("t") → returns 1, list_all_triggers() == [].
8. register 65536 triggers → 65536th call returns
   StorageCondition::TooManyTriggers.
```
