r"""The four normalisers, and the back-map that carries an offset between two coordinate systems.

`normalize_k`'s contract is what makes `ground()` correct, and `ground()` lives in the graph
layer rather than here — so `_reference_ground` below is 06-structure-extraction.md section
1.7's printed algorithm, copied into the test so the contract can be exercised where the
contract lives. It is a FIXTURE, not a second grounding path: GR5 says there is one producer of
a `ts_a`/`ts_b` and it is `ground()`.

Covers 06-structure-extraction.md section 1.7 and section 11 (P-GROUND's seven classes),
13-quality.md section 6 (P-23) and section 8.2 (`fold_common`, Q-G23's case-sensitivity
difference), ADR-5 decision 1 (`nfc`), and charter.md section D7 / section 5 X30
(`normalize_key`'s three invariants).

Randomness is a blake2b keystream rather than `random`: the repo bans `random` outright
("Sampling is blake2b. Determinism is a gate, not a habit.", 11-repo-layout.md section 8.1), and
a fuzz corpus that is not reproducible cannot be re-run against a fix.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence

import pytest
from omniweave_core.ident import fold_common, nfc, normalize_k, normalize_key

# --------------------------------------------------------------------------------------------
# The one grounding algorithm, as 06 section 1.7 prints it. A fixture, not a shipped path.
# --------------------------------------------------------------------------------------------


def _reference_ground(block_text: str, quote: str) -> tuple[int, int, int] | None:
    """-> (ts_a, ts_b, occurrences) in BLOCK.TEXT coordinates, or None.

    Verbatim from 06-structure-extraction.md section 1.7. The offsets come back through
    `normalize_k`'s back-map; they are NEVER the offsets `.find()` returned.
    """
    hay, back = normalize_k(block_text)
    needle, _ = normalize_k(quote)
    if not needle:
        return None
    hits: list[int] = []
    i = hay.find(needle)
    while i != -1:
        hits.append(i)
        i = hay.find(needle, i + 1)
    if not hits:
        return None
    i0 = hits[0]
    end = i0 + len(needle)
    ts_a = back[i0]
    ts_b = back[end - 1] + 1
    if normalize_k(block_text[ts_a:ts_b])[0] != needle:
        return None
    return ts_a, ts_b, len(hits)


# --------------------------------------------------------------------------------------------
# The five cases verified by executing the specification
# --------------------------------------------------------------------------------------------

VERIFIED_NONE = (
    ("the ﬁle", "the f"),  # a boundary inside a ligature expansion
    ("ﬁx it", "i"),  # the same, at the head of the block
    ("Straße", "se"),  # a boundary inside a casefold expansion
)


@pytest.mark.parametrize(("text", "quote"), VERIFIED_NONE)
def test_a_boundary_inside_an_expansion_is_none_and_never_a_widened_span(
    text: str, quote: str
) -> None:
    """`ground()` never widens a span to make one fit (06 section 1.7, P-GROUND class 7).

    Each of these matches in NORMALISED space, so `.find()` succeeds and a span is computed;
    only the round-trip post-condition rejects it.
    """
    hay, _ = normalize_k(text)
    needle, _ = normalize_k(quote)
    assert needle in hay, "the fixture must match in normalised space or it proves nothing"
    assert _reference_ground(text, quote) is None


def test_a_trailing_cf_run_is_outside_the_span() -> None:
    """`back[end - 1] + 1`, not `back[end]`: the span ends at 2, not 5 (06 section 1.7)."""
    out, back = normalize_k("ab\u200b\u200b\u200bc")
    assert out == "abc"
    assert back == (0, 1, 5)
    assert _reference_ground("ab\u200b\u200b\u200bc", "ab") == (0, 2, 1)


def test_a_soft_hyphen_across_a_line_break_grounds_the_unbroken_word() -> None:
    """Operation 1, and the proof that it runs before operations 4 and 6 (P-GROUND class 6)."""
    text = "The hyphen­\nation rule applies"
    assert normalize_k(text)[0] == "the hyphenation rule applies"
    assert _reference_ground(text, "hyphenation") == (4, 17, 1)
    assert text[4:17] == "hyphen­\nation"


# --------------------------------------------------------------------------------------------
# P-GROUND: seven classes, each with a different length delta (06 section 11)
# --------------------------------------------------------------------------------------------

#: (class, block_text, quote, expected) — the table of 06 section 11, verbatim.
P_GROUND: tuple[tuple[str, str, str, object], ...] = (
    ("ligature", "the ﬁle", "file", "triple"),
    ("double space", "a  b", "a b", "triple"),
    ("leading space", "  Acme", "acme", "triple"),
    ("category Cf", "Ac\u200bme", "acme", "triple"),
    ("casefold expansion", "Straße", "strasse", "triple"),
    ("soft hyphen", "The hyphen­\nation rule applies", "hyphenation", (4, 17, 1)),
    ("boundary in expansion", "the ﬁle", "the f", None),
    ("boundary in expansion", "ﬁx it", "i", None),
    ("boundary in expansion", "Straße", "se", None),
)


@pytest.mark.parametrize(("klass", "text", "quote", "expected"), P_GROUND)
def test_p_ground(klass: str, text: str, quote: str, expected: object) -> None:
    """P-GROUND. The outcome its class specifies, and whenever it returns a triple,
    `normalize_k(block_text[ts_a:ts_b])[0] == normalize_k(quote)[0]`."""
    got = _reference_ground(text, quote)
    if expected is None:
        assert got is None, klass
        return
    assert got is not None, klass
    if expected != "triple":
        assert got == expected, klass
    ts_a, ts_b, occurrences = got
    assert 0 <= ts_a < ts_b <= len(text)
    assert occurrences >= 1
    assert normalize_k(text[ts_a:ts_b])[0] == normalize_k(quote)[0], klass


def test_p_ground_covers_seven_classes_each_changing_length_by_a_different_operation() -> None:
    """ "Seven classes, each with a different length delta, and the suite fails if the set has
    fewer" (06 section 11). The seven OPERATIONS are what differ; the numeric deltas are not
    distinct and cannot be — see this module's deviation note. What the suite must not permit is
    two classes that exercise the same length change, so the operation is what is asserted.
    """
    classes = {row[0] for row in P_GROUND}
    assert len(classes) == 7
    operations = {
        "ligature": "2 NFKC expands",
        "double space": "6 whitespace collapses",
        "leading space": "7 strip drops",
        "category Cf": "4 Cf strip deletes",
        "casefold expansion": "3 casefold expands",
        "soft hyphen": "1 soft hyphen takes the line break",
        "boundary in expansion": "the post-condition rejects",
    }
    assert set(operations) == classes
    assert len(set(operations.values())) == 7
    deltas = {len(row[1]) - len(normalize_k(row[1])[0]) for row in P_GROUND}
    assert deltas != {0}, "every class must change length, or it tests nothing"
    assert min(deltas) < 0 < max(deltas), "expansion and contraction must both be covered"


# --------------------------------------------------------------------------------------------
# normalize_k: the seven operations, their order, and the shape of what comes back
# --------------------------------------------------------------------------------------------


def test_the_return_type_is_a_pair_and_the_back_map_is_a_tuple() -> None:
    """`normalize_k(s) -> tuple[str, tuple[int, ...]]` (terminology.md; 06 section 1.7).

    `normalize_k(x) == s` compares a tuple to a string and is statically always False, which is
    the misuse that produced the original `ts_a`/`ts_b` defect (06 section 11).
    """
    result = normalize_k("Acme")
    assert isinstance(result, tuple)
    out, back = result
    assert isinstance(out, str)
    assert isinstance(back, tuple)
    assert all(isinstance(i, int) for i in back)
    assert result != "acme"  # the shape of the defect the semgrep rule matches


def test_the_empty_string_and_the_empty_back_map() -> None:
    """ "`back` is empty exactly when `out` is empty" (06 section 1.7)."""
    assert normalize_k("") == ("", ())
    assert normalize_k("   \t\n ") == ("", ())
    assert normalize_k("\u200b‍") == ("", ())
    assert normalize_k("­") == ("", ())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hyphen­ation", "hyphenation"),
        ("hyphen­\nation", "hyphenation"),
        ("hyphen­\r\nation", "hyphenation"),
        ("hyphen­\ration", "hyphenation"),
        ("hyphen­\x0bation", "hyphenation"),
        ("hyphen­\x0cation", "hyphenation"),
        ("hyphen­\x85ation", "hyphenation"),
        ("hyphen­ ation", "hyphenation"),
        ("hyphen­ ation", "hyphenation"),
    ],
)
def test_operation_1_takes_every_line_break_form_with_it(text: str, expected: str) -> None:
    """CR, LF, CRLF, U+000B, U+000C, U+0085, U+2028 and U+2029 — and CRLF is ONE break."""
    assert normalize_k(text)[0] == expected


def test_operation_1_emits_nothing_in_the_line_breaks_place() -> None:
    """ "NOTHING is emitted in its place" — a space there is the defect operation 1 repairs."""
    out, _ = normalize_k("a­\nb")
    assert out == "ab"
    assert " " not in out


def test_operation_1_must_precede_the_cf_strip_or_it_is_dead_code() -> None:
    """The order is load-bearing. Under a `Cf`-strip-first order U+00AD is already gone, the
    line break survives, operation 6 collapses it to a space, and "hyphen ation" becomes the
    only spelling that grounds — which is the defect 06 section 1.7 names."""
    assert unicodedata.category("­") == "Cf"
    wrong_order = normalize_k("".join(c for c in "hyphen­\nation" if c != "­"))[0]
    assert wrong_order == "hyphen ation"  # what the wrong order produces
    assert normalize_k("hyphen­\nation")[0] == "hyphenation"  # what this one produces


def test_a_bare_soft_hyphen_goes_unconditionally() -> None:
    """ "The soft hyphen goes unconditionally" — the line break is the conditional half."""
    assert normalize_k("a­b")[0] == "ab"
    assert normalize_k("a­ b")[0] == "a b"  # a SPACE is not a line break: it stays


def test_operation_2_nfkc_expands_and_the_index_repeats() -> None:
    """U+FB01 becomes two characters, both carrying the ligature's one source index."""
    out, back = normalize_k("aﬁb")
    assert out == "afib"
    assert back == (0, 1, 1, 2)


def test_operation_3_casefold_expands_and_the_index_repeats() -> None:
    """U+00DF and U+1E9E each become 'ss': one source index, two output characters."""
    assert normalize_k("Straße") == ("strasse", (0, 1, 2, 3, 4, 4, 5))
    assert normalize_k("ẞ") == ("ss", (0, 0))


def test_operation_5_folds_the_visible_dashes_and_only_those() -> None:
    """U+2010..U+2015 to '-', the one length-preserving operation. U+00AD is operation 1's."""
    out, back = normalize_k("a‐b‑c‒d–e—f―g")
    assert out == "a-b-c-d-e-f-g"
    assert back == tuple(range(13))
    assert normalize_k("−")[0] == "−"  # MINUS SIGN is not a dash in the table


def test_operation_6_collapses_a_run_and_keeps_its_first_index() -> None:
    """A composition — many source characters to one — takes the FIRST contributing index."""
    out, back = normalize_k("a \t\n b")
    assert out == "a b"
    assert back == (0, 1, 5)


def test_operation_7_strips_and_drops_those_indices() -> None:
    out, back = normalize_k("  Acme  ")
    assert out == "acme"
    assert back == (2, 3, 4, 5)


def test_a_composition_takes_the_first_contributing_source_index() -> None:
    """'a' + U+0301 -> U+00E1: one output character, and the index of the 'a'."""
    out, back = normalize_k("xáy")
    assert out == "xáy"
    assert back == (0, 1, 3)


def test_the_back_map_is_the_same_length_as_the_output_and_stays_in_range() -> None:
    for text in ("", "abc", "Straße", "the ﬁle", "a­\nb", "\u200b\u200b"):
        out, back = normalize_k(text)
        assert len(out) == len(back)
        assert all(0 <= i < len(text) for i in back)


def test_op1_can_enable_a_composition_so_a_slice_round_trip_is_not_unconditional() -> None:
    """A regression, and the reason the fuzz asserts a CONDITIONAL round trip.

    Deleting U+00AD brings a combining mark into contact with the base character before it, so
    the single output character's span in input coordinates does not renormalise to itself.
    `ground()` is correct anyway: its post-condition rejects exactly this, which is what makes
    "a RIGHT span or None" true. Written down because an unconditional round-trip assertion
    would look reasonable and would be false.
    """
    out, back = normalize_k("a­́")
    assert out == "á"
    assert back == (0,)
    assert normalize_k("a­́"[back[0] : back[0] + 1])[0] == "a"
    assert _reference_ground("a­́", "á") is None


# --------------------------------------------------------------------------------------------
# nfc: ADR-5 decision 1, and the ladder it makes provable
# --------------------------------------------------------------------------------------------


def test_nfc_is_canonical_composition_and_nothing_else() -> None:
    """`unicodedata.normalize("NFC", s)` and nothing else (ADR-5 decision 1)."""
    assert nfc("é") == "é"
    assert nfc("ABC") == "ABC"  # NOT casefold
    assert nfc("a\u200bb") == "a\u200bb"  # NOT a Cf strip
    assert nfc("a–b") == "a–b"  # NOT a dash fold
    assert nfc("a  \n b") == "a  \n b"  # NOT a whitespace collapse
    assert nfc("ﬁ") == "ﬁ"  # NOT NFKC: no compatibility decomposition
    assert nfc("hyphen­\nation") == "hyphen­\nation"  # NOT operation 1
    assert isinstance(nfc("x"), str)  # NO back-map


def test_nfc_is_what_inv_10s_bytes_branch_compares() -> None:
    """`nfc(part_bytes[os_a : os_a + os_b].decode(*os_codec.split("/", 1))) == block.text`.

    And ADR-5's evidence fixture: a retained part reading "ABC" against a `block.text` of "abc"
    passes under `normalize_k` and MUST fail under `nfc`.
    """
    part_bytes = "Café x".encode()
    os_a, os_b, os_codec = 0, len(part_bytes), "utf-8/strict"
    block_text = "Café x"
    assert nfc(part_bytes[os_a : os_a + os_b].decode(*os_codec.split("/", 1))) == block_text
    assert nfc("ABC") != "abc"
    assert normalize_k("ABC")[0] == "abc"


def test_p_23_the_quote_ladder_is_ordered_and_its_top_two_rungs_are_not_equal() -> None:
    """P-23 (13-quality.md section 6), both halves.

    (a) `nfc(d) == t` implies `normalize_k(d)[0] == normalize_k(t)[0]`, so every VERBATIM block
    also satisfies the NORMALIZED predicate; (b) the converse FAILS on the case-varied
    generator, so the two rungs are not one rung with two names.
    """
    pairs = [
        ("Café", "Café"),  # NFD / NFC
        ("hyphen­ation", "hyphen­ation"),  # soft-hyphenated
        ("the ﬁle", "the ﬁle"),  # ligatured
        ("Straße", "Straße"),
        ("À̧", "À̧"),
    ]
    for decoded, text in pairs:
        if nfc(decoded) == text:
            assert normalize_k(decoded)[0] == normalize_k(text)[0]

    converse_failures = [
        (decoded, text)
        for decoded, text in [("ABC", "abc"), ("Heading", "heading"), ("ẞ", "ss")]
        if normalize_k(decoded)[0] == normalize_k(text)[0] and nfc(decoded) != text
    ]
    assert converse_failures, "the converse must fail on the case-varied generator"


# --------------------------------------------------------------------------------------------
# normalize_key: three invariants, and two load-bearing implementation details
# --------------------------------------------------------------------------------------------

KEY_CORPUS = (
    "Acme Holdings, Ltd.",
    "İslemYap",  # Turkish dotted I: casefold expands, NFKC recomposes
    "ᾴ",  # Greek alpha with oxia and ypogegrammeni
    "́ͅ",  # ypogegrammeni then a combining accent
    "中文文档",  # CJK
    "Документ",  # Cyrillic
    "ＡＢＣ",  # full-width Latin
    "  __leading and trailing__  ",
    "éclair",
    "ÉCLAIR",
    "",
    "!!!",
)


@pytest.mark.parametrize("s", KEY_CORPUS)
def test_normalize_key_is_idempotent(s: str) -> None:
    once = normalize_key(s)
    assert normalize_key(once) == once


@pytest.mark.parametrize("s", KEY_CORPUS)
def test_normalize_key_is_charset_closed(s: str) -> None:
    r"""The result contains only `\w` characters, and never a leading, trailing or doubled `_`.

    `_` is itself a `\w` character; the separate clauses are the collapse and the strip.
    """
    key = normalize_key(s)
    assert re.fullmatch(r"\w*", key, re.UNICODE), key
    assert "__" not in key
    assert key == key.strip("_")


@pytest.mark.parametrize("s", KEY_CORPUS)
def test_normalize_key_is_caseless_stable(s: str) -> None:
    """The bounded fixpoint loop is what makes this true; a single pass is not enough."""
    assert normalize_key(s) == normalize_key(s.casefold())
    assert normalize_key(s) == normalize_key(s.upper().casefold().casefold())


def test_the_fixpoint_loop_is_load_bearing_on_the_turkish_dotted_i() -> None:
    """Casefolding U+0130 expands it to 'i' + U+0307, and NFKC does not recompose the pair —
    there is no precomposed "i with dot above" — so the combining mark reaches the `[^\\w]+`
    filter, which is not a `\\w` character and becomes an underscore. The fixpoint loop is what
    makes the result STABLE: every mark casefold introduces is fully normalised before the
    filter runs, so one pass and two agree and a pre-casefolded caller lands on the same key.
    """
    single_pass = unicodedata.normalize("NFKC", "\u0130slemYap".casefold())
    assert "\u0307" in single_pass
    assert normalize_key("\u0130slemYap") == "i_slemyap"
    assert normalize_key(normalize_key("\u0130slemYap")) == "i_slemyap"
    assert normalize_key("\u0130slemYap".casefold()) == "i_slemyap"


def test_re_unicode_is_load_bearing_or_every_cjk_corpus_collapses_to_one_node() -> None:
    """Without `re.UNICODE` the `[^\\w]+` filter eats every non-ASCII letter and a whole
    Cyrillic or CJK corpus becomes one node per document."""
    assert normalize_key("中文文档") == "中文文档"
    assert normalize_key("Док") == "док"
    assert normalize_key("مستند") == "مستند"


def test_normalize_key_is_a_str_and_normalize_k_is_not() -> None:
    """ "The two now differ in return type as well" (06 section 11)."""
    assert isinstance(normalize_key("Acme"), str)
    assert not isinstance(normalize_k("Acme"), str)


def test_normalize_key_and_normalize_k_are_not_interchangeable() -> None:
    """Four characters apart, and X30 says both survive deliberately."""
    assert normalize_key("Acme Holdings") == "acme_holdings"
    assert normalize_k("Acme Holdings")[0] == "acme holdings"


# --------------------------------------------------------------------------------------------
# fold_common: one home for the table (13 section 8.2 rules 2 and 3)
# --------------------------------------------------------------------------------------------


SHARED_TABLE_TEXTS: Sequence[str] = (
    "The  ﬁle — Straße\u200b",
    "  ＡＢ \t\n Ćafe  ",
    "a–b‐c",
    "",
)


def test_fold_common_at_casefold_true_is_normalize_ks_string() -> None:
    """The mechanical form of "the table has one home": for text free of U+00AD, the two
    agree character for character, because they are one pipeline with one flag over."""
    for s in SHARED_TABLE_TEXTS:
        assert "­" not in s
        assert fold_common(s, casefold=True, quotes=False) == normalize_k(s)[0]


def test_fold_common_folds_the_quote_table_nfkc_does_not() -> None:
    """`'‘’‚'` to `'` and `'“”„'` to `"` (13 section 8.2)."""
    s = "‘a’ ‚b “c” „d"
    assert fold_common(s, casefold=False, quotes=True) == "'a' 'b \"c\" \"d"
    assert fold_common(s, casefold=False, quotes=False) == s


def test_fold_common_leaves_case_alone_at_casefold_false() -> None:
    """Q-G23: `normalize_eval` is case-sensitive and `normalize_k` is not. Two normalisers that
    quietly converge are one normaliser with two names."""
    assert fold_common("Heading", casefold=False, quotes=True) == "Heading"
    assert fold_common("Heading", casefold=True, quotes=True) == "heading"
    assert normalize_k("Heading")[0] == "heading"


def test_fold_common_carries_the_shared_cf_dash_whitespace_and_nfkc_table() -> None:
    assert fold_common("a\u200bb", casefold=False, quotes=False) == "ab"
    assert fold_common("a—b", casefold=False, quotes=False) == "a-b"
    assert fold_common(" a  \n b ", casefold=False, quotes=False) == "a b"
    assert fold_common("ﬁx", casefold=False, quotes=False) == "fix"


def test_fold_common_requires_both_flags_by_name() -> None:
    """A default is how two normalisers converge; the plan's two call sites both name both."""
    with pytest.raises(TypeError):
        fold_common("x")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        fold_common("x", casefold=False)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        fold_common("x", False, True)  # type: ignore[misc]


def test_fold_common_does_not_carry_operation_1() -> None:
    """Operation 1 is the grounding normaliser's and is stated only there; here U+00AD is a
    category-`Cf` character and is stripped as one, and the line break collapses to a space."""
    assert fold_common("hyphen­\nation", casefold=True, quotes=False) == "hyphen ation"
    assert normalize_k("hyphen­\nation")[0] == "hyphenation"


# --------------------------------------------------------------------------------------------
# The fuzz. 100,000 (text, quote) pairs over an adversarial alphabet.
# --------------------------------------------------------------------------------------------

#: Ligatures, eszett, soft hyphens, every line-break form, zero-width characters, combining
#: marks, an NFC/NFD pair, tabs, dashes, full-width Latin, a Turkish dotted I, CJK and Cyrillic.
ALPHABET = (
    "a",
    "B",
    " ",
    "\t",
    "\n",
    "\r",
    "\r\n",
    "\x85",
    " ",
    "­",
    "ß",
    "ẞ",
    "ﬁ",
    "ﬂ",
    "ﬀ",
    "\u200b",
    "‍",
    "́",
    "̧",
    "ͅ",
    "é",
    "é",
    "‐",
    "—",
    "Ａ",
    "İ",
    "中",
    "д",
    "া",
    "ᅡ",
)


class _Blake2Stream:
    """A reproducible keystream. `random` is banned repo-wide; sampling is blake2b."""

    def __init__(self, seed: bytes) -> None:
        self._seed = seed
        self._counter = 0
        self._buf = b""
        self._pos = 0

    def byte(self) -> int:
        if self._pos >= len(self._buf):
            block = self._seed + self._counter.to_bytes(8, "big")
            self._buf = hashlib.blake2b(block, digest_size=64).digest()
            self._counter += 1
            self._pos = 0
        value = self._buf[self._pos]
        self._pos += 1
        return value

    def below(self, n: int) -> int:
        return self.byte() % n

    def word(self, max_pieces: int) -> str:
        return "".join(ALPHABET[self.below(len(ALPHABET))] for _ in range(self.below(max_pieces)))


FUZZ_CASES = 100_000


def test_fuzz_the_back_map_over_100000_adversarial_pairs() -> None:
    """`len(out) == len(back)`, every index in range, the map non-decreasing, every index
    naming a character that actually survives, and the span a `ground()` derives from it
    well-formed and — whenever the post-condition passes — exact.

    The unconditional slice round trip is NOT asserted, and must not be: operation 1 can bring
    a combining mark into contact with a base character, so a one-character output span can
    renormalise to something else. See
    `test_op1_can_enable_a_composition_so_a_slice_round_trip_is_not_unconditional`. What IS
    unconditional is that `ground()` returns a right span or `None`, which is the property
    below.
    """
    rng = _Blake2Stream(b"omniweave/ident/normalize_k/P1")
    grounded = 0
    for case in range(FUZZ_CASES):
        text = rng.word(9)
        quote = text[rng.below(len(text) + 1) :] if rng.below(2) else rng.word(5)

        out, back = normalize_k(text)
        assert len(out) == len(back), (case, text)
        assert (back == ()) == (out == ""), (case, text)
        assert all(0 <= i < len(text) for i in back), (case, text)
        assert all(back[i] <= back[i + 1] for i in range(len(back) - 1)), (case, text)
        for i in back:
            assert text[i] != "­", (case, text)
            assert unicodedata.category(text[i]) != "Cf", (case, text)

        hit = _reference_ground(text, quote)
        if hit is None:
            continue
        grounded += 1
        ts_a, ts_b, occurrences = hit
        assert 0 <= ts_a < ts_b <= len(text), (case, text, quote)
        assert occurrences >= 1
        assert normalize_k(text[ts_a:ts_b])[0] == normalize_k(quote)[0], (case, text, quote)
    assert grounded > FUZZ_CASES // 10, f"only {grounded} of {FUZZ_CASES} pairs grounded"


def test_fuzz_normalize_key_is_idempotent_charset_closed_and_caseless_stable() -> None:
    """`derive_identity`'s three properties over a generated corpus (06 section 11)."""
    rng = _Blake2Stream(b"omniweave/ident/normalize_key/P1")
    for case in range(20_000):
        s = rng.word(9)
        key = normalize_key(s)
        assert normalize_key(key) == key, (case, s)
        assert normalize_key(s.casefold()) == key, (case, s)
        assert normalize_key(s.upper()) == normalize_key(s.upper().casefold()), (case, s)
        assert re.fullmatch(r"\w*", key, re.UNICODE), (case, s)
        assert key == key.strip("_")
        assert "__" not in key


def test_fuzz_the_two_normalisers_share_one_fold_table() -> None:
    """13 section 8.2 rule 2, mechanically: a dash added to one is added to both."""
    rng = _Blake2Stream(b"omniweave/ident/fold_common/P1")
    for case in range(20_000):
        s = rng.word(9).replace("­", "")
        assert fold_common(s, casefold=True, quotes=False) == normalize_k(s)[0], (case, s)


def test_fuzz_nfc_implies_the_normalized_predicate() -> None:
    """P-23 half (a) over generated pairs rather than the five hand-written ones."""
    rng = _Blake2Stream(b"omniweave/ident/p23/P1")
    checked = 0
    for case in range(20_000):
        decoded = rng.word(7)
        text = nfc(decoded)
        assert normalize_k(decoded)[0] == normalize_k(text)[0], (case, decoded)
        checked += 1
    assert checked == 20_000
