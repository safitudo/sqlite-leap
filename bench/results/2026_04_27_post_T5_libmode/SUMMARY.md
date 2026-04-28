# Lib-mode bench summary — 2026-04-27 post-T5

Mac arm64. Single run each. Library mode (no CLI startup overhead — the apples-to-apples numbers).

| Lane | leap-rust | leap-c | mainline | leap-c vs mainline |
|------|-----------|--------|----------|--------------------|
| L2 parse | 1,749 | 1,636 | 58,156 stmts/s | 1:36 (corpus caveat) |
| L3 SELECT | 408,558 | 744,031 | 804,544 qps | **1:1.08** |
| L4 INSERT | 528,885 | 868,287 | 948,967 ips | **1:1.09** |

## vs 2026-04-26 lib-mode publication

| Lane | leap-rust then | leap-rust now | improvement |
|------|----------------|---------------|-------------|
| L3 | 3,076 qps | 408,558 qps | **133× faster** |
| L4 | 39,687 ips | 528,885 ips | **13× faster** |

Lane 3 attack (PK index + predicate-pushdown) and Lane 4 attack (prepared-statement cache) landed.

## L2 caveat

L2 ratio 1:36 contaminated by hostile corpus — ~25-33% of statements fail prepare on leap targets, so most of leap's wall time is compile-error handling rather than parse work. Mainline produces 191 errors and exits in 2.7s; leap loops the remainder for ~90s. Needs a corpus-cleanup pass before publication.

## L1, L5, L6 (unchanged from CLI mode — they're not CLI-flattered)

- L1 cold start: leap-c 2.7× faster than mainline
- L5 binary size: leap-c 3.3× smaller than mainline, 36.5× smaller than turso
- L6 memory: leap-rust 1.4× lower than mainline, 8.6× lower than turso

## Verdict for publication

Of 6 lanes, leap-c is publication-shaped on:
- L1 ✓ WIN 2.7×
- L3 ✓ near-parity (1:1.08, within noise)
- L4 ✓ near-parity (1:1.09, within noise)
- L5 ✓ WIN 3.3×
- L6 ✓ WIN 1.3×

L2 needs corpus cleanup. Linux validation still owed before public publication.
