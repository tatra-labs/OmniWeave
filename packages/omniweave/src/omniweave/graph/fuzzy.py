"""The fuzzy stages' arithmetic: entropy, MinHash bands, Jaro-Winkler, the label guards. D685.

06-structure-extraction.md section 5.1 stages [3]-[5] and [7], and section 5.2's guards, as pure
functions over labels. `omniweave.graph.resolve` runs them over the store. The constants are
graphify's measured values (`dedup.py:242-248`, 06:1793), transcribed.

A label here is an entity's `key` -- `normalize_key` of its canonical surface -- with its `_`
separators read as spaces (`label()`), which is graphify's own `_norm` form. Standard library only;
`random` is banned in this repository, so every hash is blake2b.

## Rulings (the ledger's D685)

1. **The bands are the blocking, and `LSH_THRESHOLD` is not a second filter.** 06:1716 prints
   `NUM_PERM 128, BANDS 32, LSH_THRESHOLD 0.7`. Thirty-two bands of four rows put the S-curve's
   midpoint near `(1/32) ** (1/4)` = 0.42 Jaccard, not 0.7; read as a post-filter on the estimated
   Jaccard, 0.7 would drop `acme holdings ltd` / `acme holdings limited` (3-gram Jaccard 0.58,
   Jaro-Winkler 95) before verification ever saw them. The band layout is the schema's
   (`entity_band`) and the verifier at 92.0 is the precision step, so the bands decide candidacy
   alone. `LSH_THRESHOLD` stays in the resolve signature, so changing it still rebuilds.
2. **Only the key is fuzzy.** `entity_band`'s key is `(band, bucket, entity_id)` with no name
   column: one signature per entity. Aliases take part in the exact stage, where a shared alias is
   already a merge.
3. **Entropy is over the label with its separators**: Shannon bits per character of
   `name_norm`'s characters, `_` included, as 06:1710 prints it.
4. **The guards, made precise** (06:1825-1829 gives each one line):
   * `prefix_containment` -- the longer label starts with the shorter and they differ.
   * `numeric_tokens_differ` -- the multisets of digit runs differ.
   * `content_token_swap` -- the same multiset of words in a different order.
   * `variant_suffix` -- both labels under 12 characters, the same number of words (two or more),
     equal but for the last, and both last words three characters or fewer (`model x` /
     `model s`, `cortex a55` / `cortex a53`).
   * `short_label_substitution` -- when either label is under 12 characters, a merge needs equal
     lengths and exactly one substituted character.
   A guard returns whether it BLOCKS; `GUARDS` is the order they are tried and reported in.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

__all__ = [
    "BANDS",
    "ENTROPY_MIN",
    "GUARDS",
    "LONG_LABEL",
    "LSH_THRESHOLD",
    "MERGE_THRESHOLD",
    "NUM_PERM",
    "ROWS",
    "SHINGLE_K",
    "bands",
    "blocked_by",
    "entropy",
    "jaro",
    "jaro_winkler",
    "label",
    "shingles",
    "signature",
    "verify",
]

ENTROPY_MIN: Final = 2.5
LSH_THRESHOLD: Final = 0.7
MERGE_THRESHOLD: Final = 92.0
NUM_PERM: Final = 128
BANDS: Final = 32
ROWS: Final = NUM_PERM // BANDS
SHINGLE_K: Final = 3
LONG_LABEL: Final = 12
"""06:1720 and 06:1828: `max(len) >= 12` is plain Jaro across documents; under 12 is short."""
COOCCURRENCE_THRESHOLD: Final = 97.0
"""06:1834: two entities mentioned distinctly in one Segment need 97, not 92."""
AMBIGUOUS_LOW: Final = 75.0
"""06:1730: `[75, 92)` is the LLM band. Not built: such a pair is counted and left (D685)."""
COHESION_SPLIT_DELTA: Final = 10.0
_PRIME: Final = (1 << 61) - 1
_WORD: Final = re.compile(r"[^\W_]+")
_DIGITS: Final = re.compile(r"\d+")


def label(key: str) -> str:
    """`acme_holdings_ltd` -> `acme holdings ltd`: graphify's `_norm` form of a blocking key."""
    return " ".join(key.split("_"))


def entropy(name: str) -> float:
    """Ruling 3: Shannon bits per character of `name`."""
    if not name:
        return 0.0
    counts = Counter(name)
    total = len(name)
    return -sum(c / total * math.log2(c / total) for c in counts.values())


def shingles(text: str, k: int = SHINGLE_K) -> frozenset[str]:
    """Character k-grams with every separator stripped (06:1796): `graph extractor` and
    `graphextractor` share them. A label shorter than k is one shingle, itself."""
    bare = "".join(ch for ch in text if ch not in " _")
    if len(bare) <= k:
        return frozenset({bare}) if bare else frozenset()
    return frozenset(bare[i : i + k] for i in range(len(bare) - k + 1))


def _coefficients() -> tuple[tuple[int, int], ...]:
    out = []
    for i in range(NUM_PERM):
        raw = hashlib.blake2b(f"ow.minhash.{i}".encode(), digest_size=16).digest()
        a = int.from_bytes(raw[:8], "big") % (_PRIME - 1) + 1
        b = int.from_bytes(raw[8:], "big") % _PRIME
        out.append((a, b))
    return tuple(out)


_COEFFICIENTS: Final = _coefficients()


def signature(grams: Iterable[str]) -> tuple[int, ...]:
    """MinHash over `NUM_PERM` universal hashes `(a*x + b) mod (2**61 - 1)`, x a blake2b of the
    shingle. Empty input has no signature."""
    xs = [int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big") for g in grams]
    if not xs:
        return ()
    return tuple(min((a * x + b) % _PRIME for x in xs) for a, b in _COEFFICIENTS)


def bands(sig: Sequence[int]) -> tuple[bytes, ...]:
    """One bucket per band: blake2b over the band's `ROWS` values. `BANDS` of them, or none."""
    if len(sig) != NUM_PERM:
        return ()
    out = []
    for band in range(BANDS):
        rows = sig[band * ROWS : (band + 1) * ROWS]
        raw = b"".join(v.to_bytes(8, "big") for v in rows)
        out.append(hashlib.blake2b(raw, digest_size=8).digest())
    return tuple(out)


def jaro(s: str, t: str) -> float:
    """Jaro similarity in [0, 1]."""
    if s == t:
        return 1.0
    if not s or not t:
        return 0.0
    window = max(max(len(s), len(t)) // 2 - 1, 0)
    s_hit = [False] * len(s)
    t_hit = [False] * len(t)
    matches = 0
    for i, ch in enumerate(s):
        for j in range(max(0, i - window), min(len(t), i + window + 1)):
            if not t_hit[j] and t[j] == ch:
                s_hit[i] = t_hit[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    s_seq = [ch for ch, hit in zip(s, s_hit, strict=True) if hit]
    t_seq = [ch for ch, hit in zip(t, t_hit, strict=True) if hit]
    transpositions = sum(a != b for a, b in zip(s_seq, t_seq, strict=True)) / 2
    return (matches / len(s) + matches / len(t) + (matches - transpositions) / matches) / 3


def jaro_winkler(s: str, t: str, *, scale: float = 0.1, max_prefix: int = 4) -> float:
    """Jaro-Winkler in [0, 1]: Jaro plus the common-prefix bonus (up to four characters)."""
    base = jaro(s, t)
    prefix = 0
    for a, b in zip(s, t, strict=False):
        if a != b or prefix == max_prefix:
            break
        prefix += 1
    return base + prefix * scale * (1 - base)


def verify(left: str, right: str, *, cross_document: bool) -> float:
    """Stage [5]'s score in [0, 100]: plain Jaro across documents when either label is long
    (06:1720, `dedup.py:903-907`), Jaro-Winkler otherwise."""
    if cross_document and max(len(left), len(right)) >= LONG_LABEL:
        return 100.0 * jaro(left, right)
    return 100.0 * jaro_winkler(left, right)


def _prefix_containment(lo: str, hi: str) -> bool:
    short, long_ = sorted((lo, hi), key=len)
    return long_.startswith(short) and long_ != short


def _numeric_tokens_differ(left: str, right: str) -> bool:
    return Counter(_DIGITS.findall(left)) != Counter(_DIGITS.findall(right))


def _content_token_swap(left: str, right: str) -> bool:
    lw, rw = _WORD.findall(left), _WORD.findall(right)
    return lw != rw and Counter(lw) == Counter(rw)


def _variant_suffix(left: str, right: str) -> bool:
    if max(len(left), len(right)) >= LONG_LABEL:
        return False
    lw, rw = left.split(), right.split()
    return (
        len(lw) == len(rw) >= 2  # noqa: PLR2004 -- a stem and a suffix
        and lw[:-1] == rw[:-1]
        and lw[-1] != rw[-1]
        and max(len(lw[-1]), len(rw[-1])) <= 3  # noqa: PLR2004 -- a version or SKU tail
    )


def _short_label_substitution(left: str, right: str) -> bool:
    if min(len(left), len(right)) >= LONG_LABEL:
        return False
    if len(left) != len(right):
        return True
    return sum(a != b for a, b in zip(left, right, strict=True)) != 1


GUARDS: Final[tuple[tuple[str, Callable[[str, str], bool]], ...]] = (
    ("prefix_containment", _prefix_containment),
    ("numeric_tokens_differ", _numeric_tokens_differ),
    ("content_token_swap", _content_token_swap),
    ("variant_suffix", _variant_suffix),
    ("short_label_substitution", _short_label_substitution),
)
"""06:1825-1829's five label guards, in the table's order. `scoped_label_crossdoc` and
`cooccurrence_in_segment` read the store and are applied in `resolve`; `file_anchored_crossdoc`
has nothing to guard (no extractor writes file-anchored entities); `cross_trust_class` is owed."""


def blocked_by(left: str, right: str) -> str | None:
    """The first guard that blocks the pair, or `None` when every one passes."""
    for name, blocks in GUARDS:
        if blocks(left, right):
            return name
    return None
