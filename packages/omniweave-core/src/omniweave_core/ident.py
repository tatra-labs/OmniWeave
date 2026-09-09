r"""The four normalisers: `normalize_key`, `normalize_k`, `nfc` and `fold_common`.

Four functions, four jobs, and they are **not** interchangeable — the standing warning is
06-structure-extraction.md section 11 and charter.md section 5 X30, and the names of the first
two differ by four characters on purpose.

| function        | job              | folds                                     | returns       |
|-----------------|------------------|-------------------------------------------|---------------|
| `normalize_key` | blocking keys    | NFKC/casefold fixpoint, then `\w`-closed   | `str`         |
| `normalize_k`   | grounding        | seven operations, in one order            | `(str, back)` |
| `nfc`           | proof (INV-10)   | canonical composition, nothing else       | `str`         |
| `fold_common`   | the shared table | NFKC, `Cf`, dashes, whitespace (+options) | `str`         |

`normalize_key` is called by the `anchor`/`ref_site` writers and by `op.resolve`; `normalize_k`
by `GraphSink.mention` and by the router's `FieldGrounding`; `nfc` by INV-10's three
`OriginSpan` branches; `fold_common` by `omniweave_conform.normalize.normalize_eval`.

A **proof** normaliser folds strictly less than a **comparison** normaliser: that is the whole
reason `nfc` is a function of its own rather than a reuse of `normalize_k`
(ADR-5, `_plan/adr/0005-byte-exactness-chain.md`, decision 1).

`normalize_k` and `fold_common` share ONE implementation of the fold table rather than two
copies of it, because "a dash added to one is added to both" is the stated obligation
(13-quality.md section 8.2 rule 2) and two normalisers that drift are the failure that rule
exists to prevent. `normalize_k` is `_fold(soft_hyphen=True, casefold=True, quotes=False)`
carrying its back-map out; `fold_common` is the same pipeline with the flags the caller names
and the back-map discarded.

Specified in 06-structure-extraction.md section 1.7 (`normalize_k`, `nfc`), 13-quality.md
section 8.2 (`fold_common`), charter.md section D7 and 02-architecture.md section 2 row 5.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["fold_common", "nfc", "normalize_k", "normalize_key"]


# --------------------------------------------------------------------------------------------
# The shared table. ONE home (13-quality.md section 8.2 rule 2).
# --------------------------------------------------------------------------------------------

_SOFT_HYPHEN = "­"

#: Operation 1's line-break set: CR, LF, VT, FF, NEL, LS, PS. CRLF is handled as one break.
_LINE_BREAKS = frozenset("\n\r\v\f\x85  ")

#: Operation 5: the VISIBLE dashes, U+2010..U+2015, and nothing else. U+00AD is operation 1's
#: and is deleted rather than folded; the ASCII hyphen is already `-`.
_DASH_FOLD = dict.fromkeys("‐‑‒–—―", "-")

#: The quote table NFKC does not perform (13-quality.md section 8.2). `quotes=True` only.
_QUOTE_FOLD = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "“": '"',
    "”": '"',
    "„": '"',
}

_ASCII_LIMIT = 0x80

#: Hangul jamo, extended jamo and the syllable block. A Hangul V or T is a ccc=0 character that
#: composes with what precedes it, so a segment may not start at one (see `_is_segment_start`).
_HANGUL_RANGES = ((0x1100, 0x11FF), (0xA960, 0xA97F), (0xAC00, 0xD7FF))

_KEY_FIXPOINT_STEPS = 6
_KEY_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)
_KEY_UNDERSCORE_RUN = re.compile(r"_+")

#: A string and, in lockstep, the input index each of its characters came from. Two parallel
#: lists rather than a list of pairs: every operation below rewrites both or neither.
_Aligned = tuple[list[str], list[int]]


class _AlignmentError(AssertionError):
    """`normalize_k` broke its own `len(out) == len(back)` invariant.

    Raised rather than `assert`ed: `assert` is banned in `omniweave_core` source by the repo's
    ruff configuration (S101, 11-repo-layout.md section 8.1) and `python -O` strips it, and an
    invariant that vanishes under `-O` is not an invariant. 06-structure-extraction.md
    section 1.7 says this is asserted; this is that assertion, in a form that always runs.
    """


# --------------------------------------------------------------------------------------------
# The blocking-key normaliser
# --------------------------------------------------------------------------------------------


def normalize_key(s: str) -> str:
    r"""The BLOCKING-KEY normaliser. A key, NEVER an identifier (GR11).

    Invariants, one property test each: **idempotent** · **charset-closed** (`\w` and `_` only)
    · **caseless-stable** (`normalize_key(s) == normalize_key(s.casefold())`).

    The bounded fixpoint loop is LOAD-BEARING: casefold and NFKC do not commute and neither is
    a fixpoint of the other. Casefolding can expand a character into a base letter plus a
    combining mark (Turkish dotted I -> `i` + U+0307) which NFKC then recomposes, and Greek
    ypogegrammeni U+0345 casefolds to an iota NFKC composes with a following accent into a
    precomposed character a single pass never reaches. `re.UNICODE` on the filter is equally
    load-bearing: without it every CJK, Cyrillic and Arabic corpus collapses to one node per
    document.

    It is NOT `normalize_k` (grounding, and a different return type), NOT `nfc` (INV-10's
    proof normaliser) and NOT `sanitize_label` (`omniweave_core.answer.untrusted`).

    Vendored from graphify's `ids.py` (`normalize_id`, Apache-2.0), whose source belongs at a
    pinned SHA under `vendor/graphify-ids/` with LICENSE, NOTICE and `.sha256` (G12).
    Specified in charter.md section D7 and 02-architecture.md section 2 row 5.
    """
    cur = s
    for _ in range(_KEY_FIXPOINT_STEPS):
        nxt = unicodedata.normalize("NFKC", cur.casefold())
        if nxt == cur:
            break
        cur = nxt
    cur = _KEY_NON_WORD.sub("_", cur)
    return _KEY_UNDERSCORE_RUN.sub("_", cur).strip("_")


# --------------------------------------------------------------------------------------------
# The proof normaliser
# --------------------------------------------------------------------------------------------


def nfc(s: str) -> str:
    """The PROOF normaliser. `unicodedata.normalize("NFC", s)` and nothing else.

    No casefold, no `Cf` strip, no dash fold, no whitespace collapse, and NO back-map:
    canonical composition is the only length change, and INV-10's three branches compare WHOLE
    STRINGS rather than locate an offset inside one, so there is nothing to carry. The `bytes`
    branch reads
    `nfc(part_bytes[os_a : os_a + os_b].decode(*os_codec.split("/", 1))) == block.text`.

    A proof normaliser folds LESS than a comparison normaliser, not differently — under
    `normalize_k` a block reading "abc" would prove byte-exactness against source bytes reading
    "ABC", and under `normalize_eval` a source writing U+2013 would prove one writing '-'.

    Because NFKC is total and canonically composing, `nfc(d) == t` implies
    `normalize_k(d)[0] == normalize_k(t)[0]`: every VERBATIM block also satisfies the
    NORMALIZED predicate, and the converse fails (P-23, 13-quality.md section 6).

    It is NOT `normalize_k` (grounding), NOT `normalize_key` (blocking keys) and NOT
    `normalize_eval` (13-quality.md section 8.2, in `omniweave_conform`, which a core invariant
    must not import). Specified in 06-structure-extraction.md section 1.7 and ADR-5 decision 1.
    """
    return unicodedata.normalize("NFC", s)


# --------------------------------------------------------------------------------------------
# The grounding normaliser
# --------------------------------------------------------------------------------------------


def normalize_k(s: str) -> tuple[str, tuple[int, ...]]:
    """The GROUNDING normaliser. Returns the normalised string AND a back-map.

    `back[i]` is the index in `s` of the character that produced `out[i]`, so an offset found
    in `out` space is recoverable in `s` space. Seven operations, in EXACTLY this order. The
    order is load-bearing rather than incidental: operation 1 must precede operations 4 and 6
    or it is dead code, and six of the seven change length — which is precisely why the
    back-map exists:

      1. delete U+00AD, TAKING AN IMMEDIATELY FOLLOWING LINE BREAK WITH IT. The soft hyphen
                                    goes unconditionally; when the next character is CR, LF,
                                    CRLF, U+000B, U+000C, U+0085, U+2028 or U+2029, that
                                    character goes too and NOTHING is emitted in its place, so
                                    "hyphen\\u00ADation" and "hyphen\\u00AD\\nation" both
                                    normalise to "hyphenation".
      2. NFKC                       (compatibility decompositions; `block.text` is NFC, so
                                     these are LIVE — U+FB01 becomes two characters)
      3. casefold                   (U+00DF becomes 'ss': one character becomes two)
      4. strip Unicode category Cf  (U+200B, U+200D and friends vanish; U+00AD is already gone)
      5. fold U+2010..2015 to '-'   (the VISIBLE dashes only — the length-preserving operation)
      6. collapse whitespace runs to a single U+0020
      7. strip leading and trailing whitespace

    Operation 1 is first because U+00AD is category `Cf`. Ordered after operation 4 it can
    never fire — the soft hyphen is already deleted — and operation 6 then collapses the
    orphaned line break to a space, which is how "hyphen ation" became the only spelling that
    grounded against a soft-hyphenated word.

    The map is built DURING the transform: each step carries its predecessor's indices forward,
    an expansion repeats the source index once per produced character, a deletion drops it, and
    a COMPOSITION — many source characters to one output character — takes the FIRST
    contributing source index. `len(out) == len(back)` is checked. `back` is empty exactly when
    `out` is empty, and `back` is non-decreasing, which is what lets `ground()` read a span as
    `(back[i0], back[end - 1] + 1)`.

    It is NOT `nfc` (INV-10's proof normaliser), NOT `normalize_key` (the blocking-key
    normaliser) and NOT `sanitize_label` (06-structure-extraction.md section 9.2).

    Specified in 06-structure-extraction.md section 1.7 — its one home.
    """
    chars, srcs = _fold(s, soft_hyphen=True, casefold=True, quotes=False)
    if len(chars) != len(srcs):
        msg = f"normalize_k: len(out)={len(chars)} != len(back)={len(srcs)}"
        raise _AlignmentError(msg)
    return "".join(chars), tuple(srcs)


# --------------------------------------------------------------------------------------------
# The shared fold
# --------------------------------------------------------------------------------------------


def fold_common(s: str, *, casefold: bool, quotes: bool) -> str:
    """The shared `Cf`/dash/whitespace/NFKC table, so a second normaliser can COMPOSE it.

    NFKC, then optionally casefold, then strip category `Cf`, fold U+2010..2015 to '-',
    optionally fold the quote table (U+2018/U+2019/U+201A to `'`, U+201C/U+201D/U+201E to `"`)
    that NFKC does not perform, collapse whitespace runs to a single U+0020 and strip. Both
    flags are REQUIRED and keyword-only: the plan prints two call sites and both name both, and
    a default here is exactly how two normalisers quietly converge into one normaliser with two
    names (13-quality.md section 8.2 rule 3).

    `omniweave_conform.normalize.normalize_eval` is
    `fold_common(strip_md(s), quotes=True, casefold=False)`. It carries NO back-map — the
    evaluator compares whole strings — and it does NOT carry `normalize_k`'s operation 1, which
    is the grounding normaliser's and is stated only there; a soft hyphen reaches this function
    as a category-`Cf` character and is stripped as one.

    `fold_common(s, casefold=True, quotes=False) == normalize_k(s)[0]` for every `s` free of
    U+00AD, which is the mechanical form of "the table has one home".

    Specified in 13-quality.md section 8.2 and 02-architecture.md section 2 row 5.
    """
    chars, _ = _fold(s, soft_hyphen=False, casefold=casefold, quotes=quotes)
    return "".join(chars)


def _fold(s: str, *, soft_hyphen: bool, casefold: bool, quotes: bool) -> _Aligned:
    """The one pipeline. `normalize_k` keeps the back-map; `fold_common` discards it."""
    chars = list(s)
    srcs = list(range(len(s)))
    if soft_hyphen:
        chars, srcs = _op1_soft_hyphen(chars, srcs)
    chars, srcs = _op2_nfkc(chars, srcs)
    if casefold:
        chars, srcs = _op3_casefold(chars, srcs)
    chars, srcs = _op4_strip_cf(chars, srcs)
    table = {**_DASH_FOLD, **_QUOTE_FOLD} if quotes else _DASH_FOLD
    chars, srcs = _op5_map(chars, srcs, table)
    chars, srcs = _op6_collapse_whitespace(chars, srcs)
    return _op7_strip(chars, srcs)


def _op1_soft_hyphen(chars: list[str], srcs: list[int]) -> _Aligned:
    """Delete U+00AD, taking an immediately following line break with it, emitting nothing.

    FIRST, because U+00AD is category `Cf` and operation 4 would otherwise have eaten it.
    """
    out_c: list[str] = []
    out_s: list[int] = []
    i = 0
    n = len(chars)
    while i < n:
        if chars[i] != _SOFT_HYPHEN:
            out_c.append(chars[i])
            out_s.append(srcs[i])
            i += 1
            continue
        i += 1
        if i < n and chars[i] in _LINE_BREAKS:
            if chars[i] == "\r" and i + 1 < n and chars[i + 1] == "\n":
                i += 2  # CRLF is ONE line break.
            else:
                i += 1
    return out_c, out_s


def _op2_nfkc(chars: list[str], srcs: list[int]) -> _Aligned:
    """NFKC, carrying the indices through expansion, composition and reordering.

    Compatibility decomposition expands (U+FB01 -> 'f', 'i': the source index repeats) and
    canonical composition contracts ('a' + U+0301 -> U+00E1: the FIRST contributing source
    index wins). The string is normalised in segments that begin at a character no preceding
    character can compose or reorder across, and the segmented result is CHECKED against the
    whole-string normalisation, falling back to one unsegmented pass rather than trusting the
    segmentation — the segmentation is an optimisation and never the definition.
    """
    text = "".join(chars)
    if unicodedata.is_normalized("NFKC", text):
        return chars, srcs
    out_c: list[str] = []
    out_s: list[int] = []
    start = 0
    n = len(chars)
    for i in range(1, n + 1):
        if i < n and not _is_segment_start(chars[i]):
            continue
        seg_c, seg_s = _nfkc_segment(chars[start:i], srcs[start:i])
        out_c.extend(seg_c)
        out_s.extend(seg_s)
        start = i
    if "".join(out_c) != unicodedata.normalize("NFKC", text):
        return _nfkc_segment(chars, srcs)
    return out_c, out_s


def _is_segment_start(c: str) -> bool:
    """May a normalisation segment begin at `c` without changing the whole-string NFKC?

    True for every ASCII character: no canonical composition has an ASCII second element and
    no ASCII character is a non-starter, so nothing composes with or reorders past one. Beyond
    ASCII the test is conservative — a starter that is neither a combining mark nor a Hangul
    jamo — because a spacing mark such as U+09BE has `combining() == 0` and still composes
    backwards. `_op2_nfkc`'s check is what makes a wrong answer here slow rather than wrong.
    """
    o = ord(c)
    if o < _ASCII_LIMIT:
        return True
    if unicodedata.combining(c):
        return False
    if unicodedata.category(c)[0] == "M":
        return False
    return all(not (lo <= o <= hi) for lo, hi in _HANGUL_RANGES)


def _nfkc_segment(chars: list[str], srcs: list[int]) -> _Aligned:
    """NFKC one segment, one input character at a time, keeping the alignment exact.

    After each character the normalisation of the whole prefix is recomputed, so the string
    result is NFKC by construction. Whatever the new character changed — an expansion appended,
    a composition rewriting the tail, a canonical reordering — begins at the first index where
    the two normalisations differ, and every output character from there takes the first source
    index that contributed to it.
    """
    if unicodedata.is_normalized("NFKC", "".join(chars)):
        return list(chars), list(srcs)
    out_c: list[str] = []
    out_s: list[int] = []
    prefix = ""
    cur = ""
    for ch, src in zip(chars, srcs, strict=True):
        prefix += ch
        new = unicodedata.normalize("NFKC", prefix)
        p = _common_prefix_len(cur, new)
        first = out_s[p] if p < len(out_s) else src
        del out_c[p:]
        del out_s[p:]
        out_c.extend(new[p:])
        out_s.extend([first] * (len(new) - p))
        cur = new
    return out_c, out_s


def _common_prefix_len(a: str, b: str) -> int:
    """The length of the longest common prefix of `a` and `b`."""
    limit = min(len(a), len(b))
    i = 0
    while i < limit and a[i] == b[i]:
        i += 1
    return i


def _op3_casefold(chars: list[str], srcs: list[int]) -> _Aligned:
    """Casefold. Full case folding is per character, so an expansion repeats its index.

    U+00DF -> 'ss' and U+1E9E -> 'ss' each become two output characters carrying the one source
    index, which is what makes the quote "se" against "Strasse"'s eszett spelling a rejected
    span rather than a widened one.
    """
    out_c: list[str] = []
    out_s: list[int] = []
    for ch, src in zip(chars, srcs, strict=True):
        folded = ch.casefold()
        out_c.extend(folded)
        out_s.extend([src] * len(folded))
    return out_c, out_s


def _op4_strip_cf(chars: list[str], srcs: list[int]) -> _Aligned:
    """Strip Unicode category `Cf`. U+200B, U+200D and friends vanish, index and all.

    Both the wrapper's zero-width defanging and a zero-width-joiner obfuscation attack are
    invisible after this, which is why the joined and unjoined spellings of a surface are the
    same string here (06-structure-extraction.md section 9.4).
    """
    out_c: list[str] = []
    out_s: list[int] = []
    for ch, src in zip(chars, srcs, strict=True):
        if unicodedata.category(ch) != "Cf":
            out_c.append(ch)
            out_s.append(src)
    return out_c, out_s


def _op5_map(chars: list[str], srcs: list[int], table: dict[str, str]) -> _Aligned:
    """Fold the one-to-one character table. Length-preserving, so the indices ride through."""
    return [table.get(ch, ch) for ch in chars], srcs


def _op6_collapse_whitespace(chars: list[str], srcs: list[int]) -> _Aligned:
    """Collapse whitespace runs to a single U+0020, keeping the run's FIRST source index."""
    out_c: list[str] = []
    out_s: list[int] = []
    in_run = False
    for ch, src in zip(chars, srcs, strict=True):
        if ch.isspace():
            if not in_run:
                out_c.append(" ")
                out_s.append(src)
                in_run = True
            continue
        in_run = False
        out_c.append(ch)
        out_s.append(src)
    return out_c, out_s


def _op7_strip(chars: list[str], srcs: list[int]) -> _Aligned:
    """Strip leading and trailing whitespace, dropping those indices entirely."""
    a = 0
    b = len(chars)
    while a < b and chars[a].isspace():
        a += 1
    while b > a and chars[b - 1].isspace():
        b -= 1
    return chars[a:b], srcs[a:b]
