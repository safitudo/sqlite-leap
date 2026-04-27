# encryption — gaps

## Surface today
- `src-rust/encryption.rs` (612 LOC) ships:
  - `CipherSuite` { AesCtr (tag 0x01), XChaCha (tag 0x02) },
  - constants (RESERVED_BYTES_PER_PAGE=32, KEY_LEN=32, KDF_SALT_LEN=16, PBKDF2_ITERS=256_000, PAGE1_CLEARTEXT_PREFIX_LEN=32, MIN_ENCRYPTED_PAGE_SIZE=544, magic template),
  - `EncryptionState::new` + `derive_key` (PBKDF2-HMAC-SHA256),
  - `encrypt_page` / `decrypt_page` (per-page AEAD with HMAC tag in reserved tail),
  - `pragma_key` (verify suite tag from page-1 prefix + build state from passphrase),
  - `pragma_rekey` (fresh KDF salt for destination, returns new state + new prefix),
  - `check_page_size` (≥ 544).
- `#[cfg(test)]` unit tests for AES-CTR + XChaCha roundtrip exist in-module.

## SLT-visible blocker
Three independent layers are missing:
1. **PRAGMA dispatch** — slt_runner has `("PRAGMA", _) => Ok(())` (silent accept). `PRAGMA key`, `PRAGMA cipher`, `PRAGMA rekey` all silently no-op; no key state is propagated to the Catalog or pager.
2. **Storage-pager wiring** — `pager.rs` / `storage_fileformat.rs` open path takes no `EncryptionState`; pages are read/written cleartext. The encryption module's `encrypt_page` / `decrypt_page` are not called from any read/write path. So even with a working PRAGMA arm, on-disk pages would still be cleartext.
3. **First-open bootstrap (ENC16)** — opening an encrypted DB requires the PRAGMA-key-before-first-IO ordering. `open_database_at` has no hook for "received key, now derive state, validate page-1 magic, then proceed". The state machine in encryption.rs presumes this gating but the storage stack doesn't implement it.

## What the smoke pins (12/12 PASS)
- Baseline CREATE/INSERT/SELECT live (3 records).
- `PRAGMA key`, `PRAGMA cipher`, `PRAGMA rekey`, empty-key, alt-cipher all silently OK (7).
- INSERT after `PRAGMA key` succeeds (writes are unencrypted today).
- `SELECT count(*)` after a manifestly-wrong `PRAGMA key` returns 3 (data is cleartext).

The wrong-key SELECT counting 3 is the *important* pin: when encryption is wired, that record MUST flip to error/empty, and the smoke needs the expectation updated.

## Wiring needed
1. Real PRAGMA arm: parse `PRAGMA key = '<pass>'`, `PRAGMA cipher = '<suite>'`, `PRAGMA rekey = '<new>'`; route to a per-Catalog `EncryptionState` slot.
2. Pager hook: `pager.rs` page read/write path conditionally calls `encrypt_page` / `decrypt_page` when state is bound. Reserved-bytes-per-page in the file header must reach 32 (today probably 0).
3. `open_database_at` returns a "needs key" handle for files whose page-1 prefix matches the encrypted-magic template; subsequent `PRAGMA key` finalises by calling `pragma_key` and validating via a trial `decrypt_page` of the page-1 body.
4. Rekey (ENC4 / ENC13): vacuum-into-new-file with `pragma_rekey`'s output state, atomic swap.
5. Empty-key path (ENC2 / ENC17): vacuum-to-plaintext (the inverse of rekey). Must be a separate code path — `pragma_rekey` rejects empty new_passphrase.

## Spec-cleanliness note
Encryption is "deferred to follow-up stunts" per project CLAUDE.md scope. The SLT smoke today is a placeholder that documents the SQL-visible no-op bar; do not promise encryption in v1 publication. The smoke is structured so that switching the `wrong-key SELECT` from PASS to error becomes the *test signal* that encryption landed end-to-end.
