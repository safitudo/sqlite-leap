# Phase 6ab harness — INSERT OR IGNORE / INSERT OR REPLACE

Parser + compile extension; no new opcodes. Reuses 9g UNIQUE-probe + existing DeleteRow/InsertRow machinery. `max_invariant=43` unchanged.

Gate: 10 fixtures green both targets. `SUMMARY phase=6ab target=<c|rust> passed=10 failed=0 total=10`.

Notes:
- Two new keywords: `KEYWORD_REPLACE` (needs adding if not reserved); `KEYWORD_IGNORE` (needs adding if not reserved). `KEYWORD_OR` already reserved.
- AST: INSERT node gains `conflict_strategy: Default | Ignore | Replace` field.
- **IGNORE**: on UNIQUE/PK conflict, skip this tuple. Multi-row INSERT: partial success is the whole point.
- **REPLACE**: on UNIQUE/PK conflict, DELETE the row(s) holding the conflicting key, then INSERT. May delete multiple rows if one tuple conflicts with multiple UNIQUE constraints.
- **Default** behavior: unchanged from 9g (`STORAGE_UNIQUE_VIOLATION`).
- Only IGNORE and REPLACE are supported in v1. `OR ROLLBACK` / `OR ABORT` / `OR FAIL` → `PARSE_UNEXPECTED_TOKEN`.
- REPLACE INTO (no OR prefix) synonym form — permanent non-goal for v1.
- No new error names. IGNORE silently skips; REPLACE proceeds through existing DELETE + INSERT opcodes.
