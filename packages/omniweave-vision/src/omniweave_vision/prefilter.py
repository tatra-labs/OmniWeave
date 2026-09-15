"""The pre-filter: olmocr's `PdfFilter` measurements, inverted from a drop into an admission.

05:1410-1412 is the whole brief and it is a rule comment in the shipped policy:

> olmocr's PdfFilter drops every form and every non-English document by default with a
> `logger.info` only, behind `--apply_filter` (`action="store_true"`, off). Ours runs always, its
> verdict **ADMITS A LANE**, and any rule mapping a verdict to skip records `{reason, key,
> threshold}`.

Three inversions, and each is a line of that sentence:

1. **Ours runs always.** Upstream's is behind a flag that defaults off
   (`olmocr/pipeline.py`'s `--apply_filter`), so the shipped behaviour of the code that computes
   these numbers is that nobody reads them.
2. **A form ADMITS the `fields` lane** rather than dropping the document. `gate.form-admits-fields`
   (05:1406-1414) is the rule: `corpus.is_form = true` sets `lane = "fields"` and
   `render = "structure"`. Dropping a form is dropping the single document class most likely to be
   the reason somebody installed this.
3. **Language is recorded, never a filter.** `PdfFilter.languages_to_keep` defaults to
   `[Language.ENGLISH]` (`filter/filter.py:24`), which drops every other language in the world by
   default. `corpus.lang` is one of `[slice] by`'s four components (05:1276), so here a language is
   an accounting dimension and a slice a scoreboard reports on -- not a reason to refuse a page.

## What this module does NOT do, and it is most of upstream's file

No `lingua`, no `pypdf`, no `subprocess` -- upstream imports all three at `filter/filter.py:1-8`,
and the third is banned framework-wide outside two exempt modules (G8). Language detection is a
model, and `corpus.lang` has a provider of its own in the signal registry; form detection needs the
PDF's AcroForm dictionary, which is pdfium's side of the seam and reaches this driver as the
`corpus.is_form` signal. What is left -- and what this file is -- is the **download-spam score**,
which is twelve words and a division, and the verdict record that carries all three.

Specified in 05-ingest-and-routing.md sections 4.4 and 5.1; 16-roadmap.md section 16's row.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Final

__all__ = [
    "SEO_WORDS",
    "SPAM_THRESHOLD",
    "Verdict",
    "spam_score",
    "verdict",
]

SEO_WORDS: Final[frozenset[str]] = frozenset(
    {
        "download",
        "pdf",
        "epub",
        "mobi",
        "free",
        "ebook",
        "file",
        "save",
        "casino",
        "viagra",
        "cialis",
        "ciprofloxacin",
    }
)
"""The twelve, transcribed from `_collections/olmocr/olmocr/filter/filter.py:34-47`.

05:2190 counts them for us -- *"a 12-word SEO lexicon at threshold 0.004"* -- and the count is the
point of quoting it: a lexicon this size is a heuristic with a named false-positive class, not a
classifier. A pharmacology paper mentioning ciprofloxacin, a casino's annual report and any
document about file formats all score on it, which is why the verdict is an accounting dimension
and never a refusal."""

SPAM_THRESHOLD: Final[float] = 0.004
"""`PdfFilter.download_spam_threshold` (`filter/filter.py:21`), and 05:2190 prints the same number.

Four SEO words in a thousand. Kept rather than tuned: it is the threshold the published olmOCR
numbers were measured under, and moving it here would make our `corpus.spam_score` incomparable to
theirs while looking like the same signal."""

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"\W+")


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the pre-filter observed. Three facts, no decision.

    `is_form` and `language` are carried rather than computed here -- they arrive as the
    `corpus.is_form` and `corpus.lang` signals -- so that this record is the single place the three
    meet and the rule that reads them reads one shape. The methods say what a RULE would do with
    them, and nothing here does it: `gate.form-admits-fields` is the rule, `[[rule]]` blocks are
    data, and a driver that branched on its own verdict would be routing.
    """

    spam_score: float = 0.0
    is_form: bool = False
    language: str = ""

    @property
    def is_download_spam(self) -> bool:
        """`_is_download_spam` (`filter/filter.py:33`), as a comparison rather than a drop."""
        return self.spam_score > SPAM_THRESHOLD

    @property
    def admits_fields(self) -> bool:
        """05:1413's own clause: `when = { "corpus.is_form" = true }`."""
        return self.is_form

    def render(self) -> str:
        return (
            f"spam_score={self.spam_score:.4f}{' >' if self.is_download_spam else ' <='}"
            f"{SPAM_THRESHOLD} is_form={self.is_form} lang={self.language or '-'}"
        )


def spam_score(text: str) -> float:
    """SEO words over total words, on the whitespace-normalised lowercase text. `[0.0, 1.0]`.

    `_is_download_spam`'s arithmetic (`filter/filter.py:49-62`), extracted from its threshold: the
    upstream function returns a boolean and throws the number away, and the number is the one
    05:2188 wants -- `corpus.spam_score` is a registered signal, so a slice can be sorted by it.

    An empty document scores 0.0 rather than raising, which is upstream's `total_words == 0`
    branch, and is the right answer for the same reason: a page with no words has no words that
    are SEO words.
    """
    clean = _WORD_RE.sub(" ", text.strip().lower())
    words = clean.split()
    if not words:
        return 0.0
    counts = Counter(words)
    hits = sum(counts[word] for word in SEO_WORDS if word in counts)
    return hits / len(words)


def verdict(text: str, *, is_form: bool = False, language: str = "") -> Verdict:
    """The three facts as one record. Pure, and it is the only entry point."""
    return Verdict(spam_score=spam_score(text), is_form=is_form, language=language)
