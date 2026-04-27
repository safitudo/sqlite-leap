---
name: storage/encryption
kind: leaf
shapes: ./shapes.json
inherits:
  - /parts/storage/parts/file-format/master.md
  - /parts/storage/parts/fileformat-read/master.md
  - /parts/storage/parts/fileformat-write/master.md
  - /parts/storage/parts/pager/master.md
  - /parts/storage/parts/wal/master.md
---

# Part: storage/encryption

Page-level transparent encryption for the SQLite-leap storage
stack. Every page that leaves the pager toward the file system is
encrypted; every page that re-enters from the file system is
decrypted and authenticated. The plaintext page image visible to
the B-tree and the VDBE is unchanged: encryption is a boundary
transform on the I/O path, not a schema-level feature.

This is a **language-neutral specification**. No target code is
emitted from this part directly; the page-cipher boundary is
spliced into the I/O sites declared by `pager`, `fileformat-write`,
`fileformat-read`, and `wal`. Targets implement the named
primitives (KDF, AEAD, HMAC, random) using their platform crypto
library; the spec fixes the byte layout, key derivation, and
verification protocol.

## Why page-level (not file-level)

A whole-file cipher cannot satisfy SQLite's I/O model: the pager
reads and writes individual pages at random offsets, the WAL
appends single page images, and recovery scans page-aligned frames.
Encrypting and authenticating each page independently preserves
random access and bounds the corruption blast radius to a single
page. This is the same boundary mainline SQLCipher chose, and the
same boundary the WAL frame contract already exposes.

## Two cipher suites

Suite is selected at database creation time and frozen in the
database header's reserved area; it cannot be changed without a
full rewrite (see `PRAGMA rekey`).

| Suite tag | AEAD                         | KDF                  | Reserved bytes/page |
|-----------|------------------------------|----------------------|---------------------|
| `AES_CTR` | AES-256-CTR + HMAC-SHA512    | PBKDF2-HMAC-SHA512   | 32                  |
| `XCHACHA` | XChaCha20-Poly1305 (AEAD)    | PBKDF2-HMAC-SHA512   | 32                  |

`AES_CTR` is the SQLCipher-3 compat target (see §SQLCipher-3
compat). `XCHACHA` is the leap-native preferred suite: 192-bit
nonce eliminates the per-page nonce-reuse audit, and Poly1305 is a
single AEAD construction rather than encrypt-then-MAC.

## Reserved bytes per page

Encryption claims `R` bytes at the **end** of every page. The
plaintext page region is therefore `[0, page_size - R)` and the
ciphertext metadata occupies `[page_size - R, page_size)`. `R` is
fixed by suite (32 bytes for both v1 suites) and stored in the
database header at byte offset 20 (`reserved_space`, already
specified by `file-format` per the mainline spec). For `AES_CTR`:

```
[ ciphertext         page_size - 32 bytes ]
[ nonce              16 bytes             ]   # CTR IV / counter base
[ hmac_tag           16 bytes             ]   # HMAC-SHA512 truncated to 16
```

For `XCHACHA`:

```
[ ciphertext         page_size - 32 bytes ]
[ nonce              24 bytes             ]   # XChaCha20 nonce
[ poly1305_tag       16 bytes             ]   # AEAD tag (last 8 bytes of 32 zero)
                                              #  → see ENC8
```

The B-tree and VDBE see only the plaintext region and operate as
if the page is `page_size - R` bytes long. The `usable_size`
invariant from `file-format` already accounts for `reserved_space`;
no other part is touched.

## Master key derivation

The user supplies a passphrase via `PRAGMA key = '...'` (see
§PRAGMA surface). The master key is derived once per connection,
at first I/O after key set:

```
derive_master_key(passphrase, kdf_salt) -> Key32:
    return PBKDF2_HMAC_SHA512(
        password = passphrase_utf8,
        salt     = kdf_salt,                 # 16 bytes from db header
        iters    = 256_000,
        out_len  = 32                        # AES-256 / XChaCha key size
    )
```

`kdf_salt` is 16 random bytes captured at database creation and
written into the **first 16 bytes of page 1**, displacing the
mainline SQLite "magic header string" `"SQLite format 3\0"`. This
is the SQLCipher-3 convention and is the single irrecoverable
deviation from mainline file-format compatibility for encrypted
databases: an encrypted leap-DB is **not** a mainline-readable DB
and vice versa. Plaintext leap-DBs remain bidirectionally
compatible.

The master key is held in process memory in a zeroizable buffer
(see ENC15). It is never written to disk and never logged.

## Per-page encryption

Encryption is keyed by `(master_key, page_number)`; the page
number is part of the AAD so that a swapped page (an attacker
moving page N's ciphertext to slot M) fails authentication.

```
encrypt_page(master_key, page_number, plaintext_region) -> (ciphertext, nonce, tag):
    nonce = csprng(suite.nonce_len)
    aad   = u32_be(page_number) || u32_be(suite_tag)
    case suite of
      AES_CTR:
        ciphertext = AES_256_CTR(key=master_key, iv=nonce, plaintext_region)
        tag        = HMAC_SHA512(key=master_key, msg=ciphertext || nonce || aad)[..16]
      XCHACHA:
        (ciphertext, tag) = XChaCha20_Poly1305_Encrypt(
            key=master_key, nonce=nonce, plaintext=plaintext_region, aad=aad)
    return (ciphertext, nonce, tag)

decrypt_page(master_key, page_number, ciphertext, nonce, tag) -> plaintext_region | AUTH_FAIL:
    aad = u32_be(page_number) || u32_be(suite_tag)
    case suite of
      AES_CTR:
        expected = HMAC_SHA512(key=master_key, msg=ciphertext || nonce || aad)[..16]
        if not constant_time_eq(expected, tag): raise AUTH_FAIL
        return AES_256_CTR(key=master_key, iv=nonce, ciphertext)
      XCHACHA:
        plaintext = XChaCha20_Poly1305_Decrypt(
            key=master_key, nonce=nonce, ciphertext=ciphertext, aad=aad, tag=tag)
        if plaintext is INVALID: raise AUTH_FAIL
        return plaintext
```

Nonces are drawn from a CSPRNG per write. Per-page nonce reuse is
catastrophic for AES-CTR (XOR of two ciphertexts under the same
keystream leaks plaintext); under XChaCha20 the 192-bit nonce
makes random-nonce reuse negligible. See ENC9.

## Page 1 is special

Page 1 carries the database header (100 bytes) which the pager
inspects **before** the cipher is keyed (page-size discovery,
suite tag, kdf_salt). The first 16 bytes (`kdf_salt`) and bytes
16..32 (header magic + page-size + suite tag, see §Header layout)
are stored **in the clear**. The encrypted region of page 1 is
`[32, page_size - R)`. The remainder of the page-1 header (file
change counter, schema cookie, etc.) is encrypted along with the
page body.

A reader observing page 1 in the clear can determine: whether the
file is encrypted (suite tag), the page size, the KDF salt. They
cannot derive the key, decrypt the body, or distinguish two
encrypted databases with the same passphrase (kdf_salt rolls per
database).

### Header layout (page 1 leading 32 bytes)

```
[ kdf_salt           16 bytes ]   # bytes  0..16, random per database
[ "SQLite leap E\0\0\0"        ]   # bytes 16..32, 16-byte magic + suite tag at byte 31
```

The 16-byte magic is `"SQLite leap E\0\0\0"` (ASCII, NUL-padded)
with the **last byte** holding the `suite_tag`:

- `0x01` → AES_CTR
- `0x02` → XCHACHA

A non-encrypted leap database keeps the mainline-compatible
`"SQLite format 3\0"` magic at bytes 0..16 and `0x00` at byte 31
(treated as part of the page-size field, which constrains it to
zero-padding in mainline anyway). The **first byte** disambiguates
encrypted (`'k'` from `kdf_salt`'s random prefix in 255/256 cases,
fall through on the 1/256 collision via byte-31 suite_tag check)
from plaintext (`'S'` always). When the first byte is `'S'` and
bytes 0..16 spell the mainline magic, treat as plaintext.

## Read path

Splice point: at the bottom of `pager_read_page` (and inside the
WAL reader's `wal_read_page`), after the raw page bytes are
loaded and before they enter the page cache:

```
load_and_decrypt(page_number) -> plaintext_page:
    raw = io_read(page_number * page_size, page_size)
    if connection.cipher_state is None:
        return raw                              # plaintext database
    nonce = raw[page_size - R .. page_size - R + nonce_len]
    tag   = raw[page_size - R + nonce_len .. page_size]
    ct    = raw[0 .. page_size - R]
    if page_number == 1:
        # carve out the cleartext header prefix
        cleartext_prefix = ct[0..32]
        ct_body          = ct[32..]
        body_pt = decrypt_page(master_key, 1, ct_body, nonce, tag)
        return cleartext_prefix || body_pt || zeros(R)
    pt = decrypt_page(master_key, page_number, ct, nonce, tag)
    return pt || zeros(R)                       # plaintext region + reserved
```

`AUTH_FAIL` from `decrypt_page` raises `RuntimeCondition::NotADb`
(maps to `SQLITE_NOTADB` on the C ABI). It does NOT map to
`SQLITE_CORRUPT`: an authentication failure is indistinguishable
from a wrong key, and exposing it as corruption would let an
attacker probe the suite tag. See ENC11.

## Write path

Splice point: at the top of `pager_write_page` and inside
`wal_append_frame`, immediately before the bytes are handed to
the OS:

```
encrypt_and_store(page_number, plaintext_page) -> raw:
    if connection.cipher_state is None:
        return plaintext_page
    pt_region = plaintext_page[0 .. page_size - R]
    if page_number == 1:
        cleartext_prefix = pt_region[0..32]
        body_pt          = pt_region[32..]
        (ct_body, nonce, tag) = encrypt_page(master_key, 1, body_pt)
        return cleartext_prefix || ct_body || nonce || tag
    (ct, nonce, tag) = encrypt_page(master_key, page_number, pt_region)
    return ct || nonce || tag
```

WAL frames carry encrypted page images. The frame header itself
(24 bytes) is **not** encrypted: page_number, salts, and frame
checksums must be inspectable for recovery before the cipher is
keyed. The WAL frame checksum (W3, W4) is computed over the
**ciphertext** page image, not the plaintext, so a frame validates
under the WAL contract independently of the cipher state.

## PRAGMA surface

The encryption part registers two pragmas through
`parts/compiler/parts/statements/pragma`:

### `PRAGMA key = '<passphrase>'`

Sets the connection's passphrase. Must be issued before any I/O
on the database. Idempotent if the same passphrase is set twice.
Issuing on a plaintext database opened for write triggers an
implicit rekey (see below). Issuing on a plaintext database
opened read-only is an error (`SQLITE_READONLY`).

State machine:

```
        +---------+       PRAGMA key       +---------+
        |  fresh  | ---------------------> | keyed   |
        +---------+                        +---------+
             |  first I/O without key                 ^
             v                                        |
        +---------+       (no transition)             |
        | locked  |                                   |
        +---------+                                   |
                                                      |
        plaintext db --- PRAGMA key (write open) -----+
                          → triggers rekey
```

`fresh → keyed` requires:

1. Read page 1 in clear.
2. If the encrypted-magic suite tag is present, derive master key
   from passphrase + kdf_salt; attempt decryption of page 1 body;
   on AUTH_FAIL, return `SQLITE_NOTADB`.
3. Otherwise, treat as plaintext-open-with-key, schedule rekey.

### `PRAGMA rekey = '<new_passphrase>'`

Changes the passphrase on an already-keyed database, or encrypts
a previously-plaintext database, or (with empty new passphrase)
decrypts an encrypted database to plaintext.

Algorithm: vacuum-into-new-file under a write transaction, with
the destination file initialized using the new key. On success,
atomic-rename over the original. The implementation reuses
`fileformat-write` atomic-rename and runs page-by-page, never
holding the entire database in memory. Rekey is `O(file_size)`
and acquires the writer lock for its duration; readers see the
old database until the rename commits. See ENC13.

## SQLCipher-3 compat (optional)

A target build flag `--cipher-compat=sqlcipher3` selects an
alternate parameterization that is byte-identical to mainline
SQLCipher version 3:

- KDF: PBKDF2-HMAC-**SHA1** (not SHA512), 64,000 iterations
- KDF salt: first 16 bytes of page 1 (same)
- AEAD: AES-256-CBC + HMAC-SHA1 (not CTR + SHA512)
- Reserved-bytes-per-page: 48 (16 IV + 32 HMAC-SHA1 tag, padded)
- HMAC AAD: page_number little-endian u32 (not big-endian, not
  with suite_tag)

Compat mode is **opt-in** and not the default: SHA1 and CBC are
deprecated for new deployments. The flag exists to read existing
SQLCipher-3 archives without a rekey. See ENC18.

A future SQLCipher-4 compat (PBKDF2-SHA512 256k iters, AES-256-CBC
+ HMAC-SHA512) is deferred to a follow-up; the suite_tag space
reserves `0x03` for that.

## Memory discipline

The master key, the passphrase buffer, and any plaintext page
that has been displaced from the page cache live in
**zeroize-on-drop** allocations. Targets implement zeroize via
their platform's volatile-write or secure-zero primitive
(`explicit_bzero`, `RtlSecureZeroMemory`, `core::ptr::write_volatile`
loop). See ENC15.

The page cache stores plaintext pages. A connection that has been
closed must zero its page cache before releasing it. A connection
that runs `PRAGMA key = ''` (empty passphrase, treated as
"forget") must zero its page cache and master key buffer
synchronously.

## Generation scope

Per `parts/spec/part-conventions.spec.md` §Generation scope:
targets emit only the cipher boundary functions
(`encrypt_page`, `decrypt_page`, `derive_master_key`,
`zeroize_buffer`) plus the splice-point integrations declared in
`shapes.json`. Targets must NOT invent helpers, retry logic,
key-stretching rounds beyond the spec, or "convenience" key-cache
layers.

The AEAD/KDF/HMAC primitives themselves are imported from the
target's platform crypto library — they are NOT re-implemented in
target code. `mapping.md` per target names the library and
version (e.g., Rust uses `aes` + `ctr` + `hmac` + `sha2` +
`pbkdf2` + `chacha20poly1305` + `subtle` from RustCrypto; C uses
OpenSSL `EVP_*` or BoringSSL; Python uses `cryptography.hazmat`).

## Correctness pins

**ENC1. Suite is frozen at creation.** The suite tag at page-1
byte 31 is set when the database is first encrypted and never
changes for the lifetime of that file (other than by `rekey`,
which produces a new file via vacuum-into).

**ENC2. Plaintext leap-DB is unchanged.** A database opened
without `PRAGMA key` is byte-identical to a non-encryption build's
output. The encryption part is a no-op on plaintext I/O.

**ENC3. Page 1 first 32 bytes are cleartext.** Bytes 0..16 are
`kdf_salt`; bytes 16..32 carry the encrypted-magic with suite tag
at byte 31. The pager must be able to discover suite + salt
without holding a key.

**ENC4. Reserved bytes are at end of page.** The trailing `R`
bytes of every page hold `(nonce || tag)` in that order. The
plaintext region is `[0, page_size - R)`. This matches the
mainline `reserved_space` semantics already declared by
`file-format`.

**ENC5. Per-page nonce per write.** Every encrypt operation draws
a fresh nonce from a CSPRNG. Reusing a nonce under AES-CTR is
forbidden; under XChaCha20 it is statistically negligible but
still spec-forbidden.

**ENC6. AAD binds page number and suite.** The AAD is
`u32_be(page_number) || u32_be(suite_tag)`. Page-swap attacks
fail authentication; suite-confusion attacks fail authentication.

**ENC7. Constant-time tag comparison.** HMAC tag verification on
AES_CTR uses constant-time equality. Targets that lack a stdlib
constant-time compare must use the platform crypto library's
provided primitive (RustCrypto `subtle::ConstantTimeEq`, OpenSSL
`CRYPTO_memcmp`).

**ENC8. AEAD tag length 16 bytes.** Both suites truncate to 16
bytes. For HMAC-SHA512, take the first 16 of the 64-byte digest.
For Poly1305, the tag is natively 16 bytes.

**ENC9. AES-CTR counter starts at zero.** The 16-byte nonce is
the initial counter block in big-endian. The CTR mode increments
the low 64 bits per 16-byte AES block. The high 64 bits of the
nonce are random, the low 64 bits are zero at the start of each
page; this gives 2^64 blocks of headroom per page, far exceeding
any practical page size.

**ENC10. PBKDF2 iters ≥ 256_000.** v1 leap-native suites use
exactly 256,000 PBKDF2-SHA512 iterations. SQLCipher-3 compat uses
64,000 PBKDF2-SHA1 iterations (mandated by that format). Targets
MUST NOT lower the iteration count below the suite's pin.

**ENC11. AUTH_FAIL maps to SQLITE_NOTADB.** Distinguishes
"unreadable / wrong key" from "structural corruption". Never
return `SQLITE_CORRUPT` for a tag mismatch; never log the
attempted key or its derivative.

**ENC12. WAL frame checksum is over ciphertext.** The
W3/W4 cumulative checksum consumes the encrypted page image (and
the trailing nonce + tag), not the plaintext. This preserves the
WAL contract under encryption; mainline cannot read encrypted
WALs anyway, so the salt+checksum protocol is internal.

**ENC13. Rekey is vacuum-into-new-file.** No in-place rekey: a
crash mid-rekey leaves the original file intact. Atomic rename
commits the new file; the writer lock is held for the entire
operation; readers see old until rename.

**ENC14. CSPRNG required.** `kdf_salt`, every per-page `nonce`,
and any internal random material come from the platform CSPRNG
(`getrandom(2)`, `BCryptGenRandom`, `/dev/urandom`,
`SecRandomCopyBytes`, Rust `OsRng`). User-space PRNGs and
predictable salts are forbidden.

**ENC15. Zeroize on drop.** Master key, passphrase buffer, and
displaced plaintext pages are zeroized via volatile writes when
their owning structure is dropped or the connection closes.
Compilers MUST NOT optimize the zero away; targets use the
platform's volatile-write primitive.

**ENC16. PRAGMA key before I/O.** A connection that issues any
read or write before `PRAGMA key` on an encrypted database fails
with `SQLITE_NOTADB`. The pager probes page 1 cleartext to detect
the encrypted-magic, then refuses to read body until keyed.

**ENC17. Empty passphrase forgets.** `PRAGMA key = ''` on a keyed
connection zeroizes the master key, drops the page cache, and
returns the connection to the `fresh` state. Subsequent I/O
without a re-keying fails per ENC16.

**ENC18. SQLCipher-3 compat is opt-in.** The `--cipher-compat=
sqlcipher3` build flag is the ONLY path to SHA1/CBC. Default
builds reject SQLCipher-3 files with `SQLITE_NOTADB` (they look
encrypted but the suite tag is absent / unknown).

**ENC19. No invented helpers.** Per §Generation scope. Targets
emit only the four primitives plus the declared splice integrations.
Crypto primitives come from the platform library; targets MUST
NOT implement AES, ChaCha20, Poly1305, HMAC, SHA, or PBKDF2 in
target code.

**ENC20. Encrypted ≠ mainline-readable.** Pin W11 (mainline-
readable WAL) and the file-format mainline-interop guarantees do
NOT extend to encrypted databases. An encrypted leap database is
an opaque blob to mainline `sqlite3` and to other tools. The
mainline-interop tests run on plaintext databases; encryption
adds a separate test track.

**ENC21. Page-size minimum.** Encrypted databases require
`page_size >= 512 + R = 544` to leave room for the page-1 header
plus reserved bytes plus a non-trivial body. Pages of 4096 (the
v1 default) are well within this. Targets MUST reject creation
of an encrypted database with `page_size < 544`.

**ENC22. KDF derivation is once-per-connection.** The expensive
PBKDF2 runs at most once per connection lifetime (cached in the
`cipher_state` struct). Re-keying via `PRAGMA rekey` invalidates
the cache and runs PBKDF2 again on the new passphrase.

## Phase pins

- **Phase ENC0** — spec only (this part). `shapes.json` declares
  the cipher_state record + the four primitive function shapes.
  No target code emitted.
- **Phase ENC1** — single-target prototype (Rust), AES_CTR suite.
  RustCrypto stack. Round-trip a 100-row INSERT/SELECT under
  `PRAGMA key`.
- **Phase ENC2** — XChaCha20-Poly1305 suite on Rust. Same
  round-trip; benchmarks under both suites.
- **Phase ENC3** — second target (C) for parity. OpenSSL EVP.
  Byte-identical encrypted output is **NOT** required (nonces are
  random); the test is round-trip and cross-target read of
  fixtures generated by the other target.
- **Phase ENC4** — `PRAGMA rekey` end-to-end, including
  plaintext→encrypted and encrypted→plaintext.
- **Phase ENC5** — SQLCipher-3 compat behind the build flag;
  fixture from a real SQLCipher-3 file decrypted by leap.
- **Phase ENC6** — remaining 3 targets (Zig, Go, Python),
  benchmarks, fuzz harness on key/IV mishandling.

## Open questions (for follow-up phases)

1. **Authenticated header.** The page-1 cleartext prefix
   (kdf_salt + magic + suite tag) is unauthenticated. An attacker
   can flip the suite tag from `0x01` to `0x02`; the wrong suite
   then fails AUTH on first body read with `SQLITE_NOTADB`, so
   this is detectable but not distinguishable from a wrong-key
   error. Phase ENC4 should consider extending the AAD to bind
   the cleartext prefix bytes; trade-off is a tighter coupling
   to the cleartext layout.

2. **HKDF subkey separation.** v1 uses the master key directly
   for both AES-CTR and HMAC under AES_CTR suite. A cleaner
   construction derives encrypt-key and mac-key via HKDF from a
   single PBKDF2 output. Defer; SQLCipher-3 also uses a single
   key per role.

3. **Per-table or per-column encryption.** Out of scope for v1;
   adding it requires schema-level metadata and changes the
   plaintext-region invariant. Track as a follow-up stunt.

4. **Hardware acceleration.** AES-NI on x86_64 and ARM crypto
   extensions on aarch64 are accessed transparently through
   RustCrypto / OpenSSL when those libraries are built with the
   right features. v1 targets MUST link those features on; the
   benchmark lane comparing leap-encrypted vs SQLCipher must use
   the same primitive set on both sides.

5. **Key-rotation without rekey.** A re-encryption that
   preserves the passphrase (rolling the master key via a second
   KDF round) is sometimes wanted to bound key lifetime under
   memory exposure. v1 requires a full `rekey`; defer.
