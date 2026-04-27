---
name: storage/fts5-tokenizer
kind: leaf
emits:
  rust:   { path: src-rust/storage_fts5_tokenizer.rs }
  c:      { path: src-c/storage/fts5_tokenizer.c }
  zig:    { path: src-zig/storage_fts5_tokenizer.zig }
  go:     { path: src-go/storage/fts5_tokenizer.go }
  python: { path: src-python/leap_sqlite/storage_fts5_tokenizer.py }
---

# Part: storage/fts5-tokenizer — built-in tokenizers

Three built-in tokenizers shipped with FTS5: `unicode61`, `ascii`,
and `porter`. Tokenization is the boundary between source text and
the byte-keyed postings the index part stores. The tokenizer must
be deterministic — the same input bytes produce the same token
stream every time, on every target — because index bytes encode
the result.

This part owns:

- The `Fts5Tokenizer` opaque handle.
- The `Fts5TokenStream` iterator surface.
- The `unicode61` Unicode-aware tokenizer (default).
- The `ascii` byte-level tokenizer.
- The `porter` stemming wrapper.
- The `tokenize=` argument-parser, called by both index-create and
  query-parse paths.

It does NOT own custom user tokenizers (deferred), the FTS5
configuration (lives in the query part), or any bytes that hit
disk (lives in the index part).

## API surface

```
Fts5Tokenizer.create(name, args)         -> Fts5Tokenizer | RuntimeCondition
Fts5Tokenizer.tokenize(text, mode)       -> Fts5TokenStream
Fts5TokenStream.next()                   -> (token_bytes, start, end) | absent
```

`mode` is `Document` (build phase: emit folded primary tokens) or
`Query` (search phase: emit folded primary tokens, plus colocated
synonyms when the tokenizer supplies them — v1: identical to
Document because no built-in tokenizer emits synonyms).

## Correctness pins

1. **Three built-in names.** `unicode61`, `ascii`, `porter`. Match
   ASCII case-insensitively. Any other name from the `tokenize=`
   option raises `Fts5UnknownTokenizer` at CREATE.

2. **`tokenize=` value parsing.** Whitespace-separated string.
   First token names the tokenizer. Remaining tokens are
   tokenizer-specific arguments, parsed by that tokenizer; any
   unrecognised argument raises `Fts5TokenizerArgError`.

3. **Token shape.** Every emitted token is a tuple
   `(bytes, start, end)`:
   - `bytes`: the *folded* representation written to the index
     (lowercased / stripped per the tokenizer rules). UTF-8.
   - `start`, `end`: byte offsets into the *original* input,
     half-open. `end > start`. The (start, end) range covers the
     *original* span; index storage uses `bytes` only.

4. **Position numbering.** Tokens are emitted in document order;
   the index part assigns ascending integer positions starting
   from 0 within each (rowid, column).

5. **Empty input → empty stream.** No diagnostic; legal to
   index an empty TEXT column.

6. **`unicode61` — character classification.** Code points are
   classified using the **Unicode 6.1** category table (frozen for
   stability — matches mainline FTS5). The table lives as a
   compile-time constant in this leaf; targets either embed a
   generated table or call into a stdlib that pins ≥ Unicode 6.1
   (mapping.md must record the choice).

   Token characters: any code point whose category is L\* (Letter),
   N\* (Number), or Co (Private Use).
   Separator characters: everything else (default).

7. **`unicode61` — token boundaries.** A token is a maximal run
   of token characters. Runs of separator characters are
   discarded. Two adjacent runs of token characters separated by
   even one separator are different tokens.

8. **`unicode61` — folding.** Each token character is mapped via
   the Unicode-6.1 *case folding* table to its lowercase form;
   the folded code point is then encoded UTF-8. Diacritic stripping
   is OFF by default; enable with the `remove_diacritics=1` or
   `remove_diacritics=2` argument (mainline values: 0=off, 1=NFKD
   strip combining marks, 2=NFKD strip combining marks plus
   common Latin extension folding). v1 supports 0 and 1; 2 is
   accepted but treated as 1 (logged as `Fts5RemoveDiacritics2`).

9. **`unicode61` — `categories=` argument.** Optional. Quoted
   space-separated list of two-letter category codes prefixed
   with `+` or `-` to add/remove from the default token-character
   set. e.g. `"categories='+Sm -Nd'"` adds math symbols, removes
   decimal digits. Unrecognised category → `Fts5TokenizerArgError`.

10. **`unicode61` — `tokenchars=` and `separators=`.** Optional.
    Each is a quoted string whose characters are added (or
    forced-separator) regardless of category. `tokenchars=` wins
    over `separators=` when a character appears in both
    (mainline rule).

11. **`ascii` — character classification.** Token characters: ASCII
    letters (A–Z, a–z) and digits (0–9). Every other byte
    (including all bytes ≥ 0x80) is a separator. Folding: ASCII
    lowercase only (uppercase A–Z mapped to a–z). Non-ASCII bytes
    pass through *as separators*; they never form tokens.

12. **`ascii` — `tokenchars=` / `separators=` arguments.** Same
    semantics as `unicode61`'s versions but on raw ASCII bytes.
    A non-ASCII byte in either argument value raises
    `Fts5TokenizerArgError`.

13. **`porter` — wrapping.** `porter` is a stemmer wrapper around
    a base tokenizer. With no extra args, the base tokenizer is
    `unicode61` with default settings. With extra args, the args
    name and configure the base: `tokenize='porter ascii'` makes
    the base `ascii`. Recursive porter (`porter porter …`) is an
    error (`Fts5TokenizerArgError`).

14. **`porter` — algorithm.** Apply the base tokenizer to obtain
    a stream of `(bytes, start, end)`. For each token whose
    folded form is pure ASCII letters of length ≥ 3, replace the
    `bytes` with the result of the **Porter stemming algorithm**
    (M.F. Porter, 1980 — published spec); leave `start` and `end`
    untouched. Tokens whose folded form contains any byte ≥ 0x80
    or whose length < 3 pass through unmodified.

15. **`porter` — algorithm pinning.** This part owns a frozen
    pseudocode listing of Porter (1980) Steps 1a/1b/1c/2/3/4/5a/5b
    in `parts/storage/parts/fts5-tokenizer/porter.spec.md` (sibling
    file). Every target must produce identical bytes for every
    English ASCII word ≥ 3 letters. Cross-target equivalence is a
    correctness gate — the same `tests/cross-build/fts5-porter.txt`
    runs on all targets.

16. **Determinism across targets.** Identical input bytes →
    identical token stream on every target. No reliance on locale,
    runtime ICU version, or non-frozen Unicode tables. Targets
    that lack a frozen Unicode 6.1 table embed the generated one
    described in pin 6.

17. **Streaming, not buffering.** The tokenizer interface is a
    pull iterator; targets must not require the entire input
    text to fit in memory before emitting the first token. (A
    finite lookahead within the current code point's UTF-8 byte
    sequence is fine.)

18. **UTF-8 well-formedness.** Inputs that are not well-formed
    UTF-8 (`unicode61`, `porter`) treat each ill-formed byte as
    a single separator and emit a `Fts5TokenizerWarning`
    diagnostic (best-effort; v1 may silently drop the
    diagnostic). The byte never becomes part of a token.

19. **Argument-parser shape.** `tokenize='name a1 a2 …'` —
    whitespace-separated. To embed a literal whitespace in an
    argument value, wrap in single or double quotes; backslash is
    NOT an escape character. Unbalanced quotes raise
    `Fts5TokenizerArgError`.

20. **Same tokenizer on index and query.** The tokenizer used
    when querying is the *exact* tokenizer (name + args)
    persisted in `t_config`. The query part loads the config and
    re-creates the tokenizer; this part exposes a deterministic
    `create` that produces the same tokenizer for the same args.

21. **Cross-target test corpus.** A 50-line UTF-8 text file with
    Latin, Cyrillic, CJK, emoji, mixed-script, and edge-case
    inputs (zero-width joiners, combining marks) is checked into
    `tests/cross-build/fts5-tokenize.txt`. All five targets must
    emit byte-identical token streams; this is the
    cross-corroboration gate for this leaf.

22. **Error conditions** (closed set):
    `Fts5UnknownTokenizer`, `Fts5TokenizerArgError`,
    `Fts5RemoveDiacritics2`, `Fts5TokenizerWarning`.

## Out of scope (v1)

- Custom tokenizer plug-in API (`fts5_tokenizer_v2`).
- `trigram` tokenizer (mainline 3.34+).
- `sqlite3_fts5_tokenizer()` C registration shim — the v1 spec is
  language-neutral; binding-layer FFI is a follow-up part.
- `remove_diacritics=2` exact-equivalence to mainline; v1 collapses
  to `=1` and surfaces `Fts5RemoveDiacritics2` once.

## Generation scope

Leaf. Each `parts/targets/<lang>/mapping.md` records:

- The Unicode 6.1 fold/category table source (embedded vs stdlib
  pin).
- The UTF-8 decoder used.
- The Porter stemmer source — must be either generated from the
  shared pseudocode or hand-written and verified against
  `tests/cross-build/fts5-porter.txt`.

Any third-party dependency must be pinned by version in
`mapping.md` per the toolchain-pin discipline already in force on
this project.
