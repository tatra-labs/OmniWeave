"""`structure_f1`'s reference and the F1 that scores against it. **D982.**

13-quality.md:1097-1098 gives the metric two rows -- `office/*` at a 0.90 floor and
`pdf/born_digital/*` at 0.85 -- and one definition: *"F1 over `(kind, layer, parent_kind)` triples:
predicted Blocks matched to reference Blocks by `normalize_eval(text)` within the assertion's
`max_diffs`, precision and recall over the matched set, macro over documents then over slices"*.
:1104 says where the reference comes from: *"each corpus document carries a `structure.jsonl` of
`(page, kind, layer, parent_kind, normalize_eval(text))` tuples, authored by a human reading a
`soffice`/pdfium render, and `checked` in {verified, rejected, NULL} exactly as an assertion is"*.
No fixture carried one, so until this module `ow eval run --suite parse` named `structure_f1` in
every run's `not_measured` and computed nothing (`eval_run` ruling 24).

`omniweave_conform.rollup` cannot hold this metric: its three rows are pass rates over assertion
verdicts, and an F1 over a labelled tree has no verdict to count. This module is the second rollup,
and the only one that reads a `Doc` rather than a `Verdict`.

## Rulings

1. **The reference is `<fixture>.structure.jsonl` beside the fixture**, as its assertions file and
   its `.meta.toml` sidecar are, and the plan names the extension. Its FIRST line is the header
   `{"schema": "omniweave.structure/1"}` and every other line is one tuple, because a JSONL file
   with no version is a file whose shape cannot be changed later; the assertions file carries
   `schema` for the same reason.
2. **A row is `id`, `page`, `kind`, `layer`, `parent_kind`, `text`, and optionally `checked`,
   `max_diffs` and `slices`.** `page` is 1-based as a reader counts, as an assertion's is;
   `Block.page` is 0-based and the comparison converts rather than storing a second convention.
   `kind` and `layer` are `Kind` and `Layer` members -- a value outside either is a `QualityError`
   naming the row, never an `UNKNOWN` fallback, because a reference that silently degrades scores a
   parser against a typo. `parent_kind` is the parent Block's `kind` and `null` exactly for a block
   with no parent (a page root).
3. **A document scores only when EVERY row of its reference is `verified`.** An assertion signs one
   claim and scores alone (13:1022); a precision denominator does not. One unsigned row makes every
   unmatched prediction unjudgeable -- it may be a false positive, or it may be the thing that row
   would have named -- so the signature unit here is the document, and a part-signed reference is
   reported unscored with its count, never scored over the signed part.
4. **Matching is one-to-one, least distance first.** For each reference row, the predicted Blocks on
   its page in its layer that are within `max_diffs` edits of it under `normalize_eval`, by
   `assertions.distance` over whole strings -- not `find()`'s approximate substring search, which
   would let one long paragraph match every line inside it. The least distance wins, and reading
   order (`ord`) breaks a tie. A taken Block is not offered twice.
5. **The triple decides the match's truth, the match decides the population.** A matched pair whose
   `(kind, layer, parent_kind)` are equal is a true positive. `precision = tp / predicted` and
   `recall = tp / reference`, so an unmatched prediction costs precision, an unmatched reference row
   costs recall, and a matched pair with the wrong kind costs both -- which is the reading of
   *"precision and recall over the matched set"* that cannot be gamed by emitting one Block per page
   or one per glyph. `f1 = 0.0` when both are zero.
6. **The population is the TEXT-BEARING Blocks, and the structure is measured through
   `parent_kind`.** :1097 matches *"by `normalize_eval(text)`"*, so a Block with no text cannot be
   matched by text at all: `parse.office.anydoc` emits a `table`, its `table_cell`s, a `list`, a
   `list_item`, a `picture` and a `footnote` carrying no text of their own (03's M-INV-4 keeps a
   parent's text out of its descendants'), and 12 of `rich.docx`'s 25 Blocks are such nodes.
   Counting them would cap precision at 13/25 whatever the parse got right, so a text-less Block is
   outside both denominators -- and its kind is still scored, because the row for the text inside it
   carries it as `parent_kind`. A reference row therefore reads "this text, at this kind, under
   this one", which is also the only form a reviewer can check against a render.
7. **A slice's value is the mean of its documents' F1, with the closed-form `se`**, and the headline
   is `stats.macro()` over the slices (13:402, and :1097's "macro over documents then over slices").
   Never `stats.rate()`: a Wilson interval is defined over 0/1 trials and an F1 is not one. A slice
   under `min_slice_n` is `unknown` with no value, as every other metric's is.
8. **A driver that declares no structure is not applicable, not failing.** `[capability.parse]`
   `sections = "none"` with `tables = "none"` says the code emits no heading, no table and no cell
   -- for `parse.pdf.pdfium` by 02:266 and F4, "no licence-clean detector" -- so its predicted tree
   is paragraphs under a root whatever the page holds. Scoring it against a labelled tree would
   measure the declaration and not the parse. `inapplicable()` returns the card's own reason and the
   suite reports it the way a target reports an undeclared law: not applicable, with the clause that
   made it so, never a silent zero and never a floor breach.

Specified in 13-quality.md sections 8.1, 8.2 and 8.3.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Protocol

from omniweave_core.drivers.card import MIN_SLICE_N
from omniweave_core.errors import QualityError
from omniweave_core.model.enums import Kind, Layer
from omniweave_core.store.oweval import Metric

from omniweave_conform.assertions import distance
from omniweave_conform.normalize import normalize_eval
from omniweave_conform.stats import Slice, macro

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence
    from pathlib import Path

    from omniweave_core.drivers.card import DriverCard
    from omniweave_core.model.block import Block, BlockId
    from omniweave_core.store.oweval import Run

    from omniweave_conform.stats import Estimate


class Tree(Protocol):
    """What the F1 reads of a document: `omniweave_core.model.doc.Doc` is one, as `cells.py`'s
    `TableSource` is -- a Protocol so a scoring test can hand it a hand-built tree."""

    def blocks(
        self,
        *,
        pages: range | None = None,
        kinds: Iterable[Kind] | None = None,
        layers: Iterable[Layer] = (Layer.BODY,),
        under: BlockId | None = None,
    ) -> Iterator[Block]: ...

    def block(self, id: BlockId) -> Block: ...  # noqa: A002 -- Doc.block's own parameter name.


__all__ = [
    "METRIC",
    "SCHEMA",
    "SUFFIX",
    "TRUTH_KIND",
    "Scored",
    "Tree",
    "Triple",
    "inapplicable",
    "load",
    "metrics",
    "reference_of",
    "score",
]

METRIC: Final = "structure_f1"
TRUTH_KIND: Final = "rendered"
"""13:1097's column: the tuples were authored against a render, independent of our text path."""
SUFFIX: Final = ".structure.jsonl"
SCHEMA: Final = "omniweave.structure/1"
VERIFIED: Final = "verified"
CHECKED: Final = frozenset({"verified", "rejected"})
MACRO: Final = "__macro__"
UNSLICED: Final = "*"
_ROW: Final = frozenset(
    {"id", "page", "kind", "layer", "parent_kind", "text", "checked", "max_diffs", "slices"}
)
_FIX: Final = "see packages/omniweave-conform/src/omniweave_conform/structure.py's rulings"


@dataclass(frozen=True, slots=True)
class Triple:
    """Ruling 2: one reference tuple, and the reviewer's signature on it."""

    id: str
    page: int
    kind: str
    layer: str
    parent_kind: str | None
    text: str
    checked: str | None = None
    max_diffs: int = 0
    slices: tuple[str, ...] = ()

    @property
    def triple(self) -> tuple[str, str, str | None]:
        """The three fields the F1 is over (13:1097)."""
        return (self.kind, self.layer, self.parent_kind)


@dataclass(frozen=True, slots=True)
class Scored:
    """One document's F1, or the reason it does not score (rulings 3, 5 and 6)."""

    doc: str
    slices: tuple[str, ...]
    tp: int
    predicted: int
    reference: int
    f1: float | None
    why: str = ""

    @property
    def scored(self) -> bool:
        """Whether this document's F1 counts toward a slice."""
        return self.f1 is not None


def reference_of(fixture: Path) -> Path:
    """Ruling 1: the reference file a fixture's structure tuples live in."""
    return fixture.with_name(fixture.name + SUFFIX)


def load(fixture: Path, *, slices: Sequence[str] = ()) -> tuple[Triple, ...]:
    """Rulings 1 and 2: the fixture's reference tuples, or `()` when it carries no file.

    `slices` is the fixture's sidecar slices, which a row with none of its own inherits, exactly as
    an assertion inherits them (`labels` ruling 4).
    """
    path = reference_of(fixture)
    if not path.is_file():
        return ()
    where = path.name
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise QualityError(f"{where} is empty: a reference with no header is not one", fix=_FIX)
    header = _object(lines[0], where=f"{where} line 1")
    if header.get("schema") != SCHEMA:
        raise QualityError(f"{where}: schema is {header.get('schema')!r}, not {SCHEMA!r}", fix=_FIX)
    if set(header) != {"schema"}:
        raise QualityError(f"{where}: the header carries schema and nothing else", fix=_FIX)
    out: list[Triple] = []
    seen: set[str] = set()
    for at, line in enumerate(lines[1:], 2):
        row = _row(_object(line, where=f"{where} line {at}"), where=f"{where} line {at}")
        if row.id in seen:
            raise QualityError(f"{where} line {at}: id {row.id!r} repeats", fix=_FIX)
        seen.add(row.id)
        out.append(row if row.slices else replace(row, slices=tuple(slices)))
    return tuple(out)


def _object(line: str, *, where: str) -> Mapping[str, object]:
    try:
        loaded = json.loads(line)
    except json.JSONDecodeError as error:
        raise QualityError(f"{where} does not load: {error}", fix=_FIX) from error
    if not isinstance(loaded, dict):
        raise QualityError(f"{where} is not a JSON object", fix=_FIX)
    return loaded


def _row(raw: Mapping[str, object], *, where: str) -> Triple:
    """Ruling 2: one row, every field closed against its vocabulary."""
    unknown = sorted(set(raw) - _ROW)
    if unknown:
        raise QualityError(f"{where}: unknown key(s) {unknown}", fix=_FIX)
    local = raw.get("id")
    if not isinstance(local, str) or not local:
        raise QualityError(f"{where}: id {local!r} is a non-empty string", fix=_FIX)
    page = raw.get("page")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise QualityError(f"{where} ({local}): page {page!r} is a 1-based page number", fix=_FIX)
    kind = _member(raw.get("kind"), Kind, "kind", where=where, local=local)
    layer = _member(raw.get("layer"), Layer, "layer", where=where, local=local)
    raw_parent = raw.get("parent_kind")
    parent = (
        None
        if raw_parent is None
        else _member(raw_parent, Kind, "parent_kind", where=where, local=local)
    )
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        raise QualityError(
            f"{where} ({local}): text is a non-empty string; a tuple with no text matches every "
            "Block",
            fix=_FIX,
        )
    raw_checked = raw.get("checked")
    if raw_checked is not None and raw_checked not in CHECKED:
        raise QualityError(
            f"{where} ({local}): checked {raw_checked!r} is verified or rejected, or absent",
            fix=_FIX,
        )
    checked = None if raw_checked is None else str(raw_checked)
    max_diffs = raw.get("max_diffs", 0)
    if isinstance(max_diffs, bool) or not isinstance(max_diffs, int) or max_diffs < 0:
        raise QualityError(f"{where} ({local}): max_diffs {max_diffs!r} is an int >= 0", fix=_FIX)
    own = raw.get("slices")
    if own is not None and (
        not isinstance(own, list) or not all(isinstance(s, str) and s for s in own)
    ):
        raise QualityError(f"{where} ({local}): slices is a list of slice names", fix=_FIX)
    return Triple(
        id=local,
        page=page,
        kind=kind,
        layer=layer,
        parent_kind=parent,
        text=text,
        checked=checked,
        max_diffs=max_diffs,
        slices=tuple(own) if own is not None else (),
    )


def _member(
    value: object, enum: type[Kind] | type[Layer], field: str, *, where: str, local: str
) -> str:
    """One closed vocabulary, checked by value and never coerced (ruling 2)."""
    if not isinstance(value, str) or value not in {member.value for member in enum}:
        raise QualityError(
            f"{where} ({local}): {field} {value!r} is not a {enum.__name__} member", fix=_FIX
        )
    return value


def inapplicable(card: DriverCard) -> str:
    """Ruling 8: the card's own reason this subject has no structure to predict, or `""`."""
    parse = card.parse
    if parse is None:
        return ""
    if parse.sections == "none" and parse.tables == "none":
        return (
            f'{card.identity.id} declares [capability.parse] sections = "none" and '
            'tables = "none", so it emits no heading, table or cell to score against a labelled '
            "tree (13:1097, 02:266)"
        )
    return ""


def score(doc_name: str, doc: Tree, reference: Sequence[Triple]) -> Scored:
    """Rulings 3, 4 and 5: one document's F1 over its reference, or why it does not score."""
    slices = tuple(sorted({one for row in reference for one in row.slices})) or (UNSLICED,)
    if not reference:
        return Scored(doc_name, slices, 0, 0, 0, None, "carries no structure.jsonl reference")
    unsigned = [row.id for row in reference if row.checked != VERIFIED]
    if unsigned:
        return Scored(
            doc_name,
            slices,
            0,
            0,
            len(reference),
            None,
            f"{len(unsigned)} of {len(reference)} reference row(s) unsigned (ruling 3)",
        )
    pages = {row.page for row in reference}
    layers = {Layer(row.layer) for row in reference}
    predicted = [
        block
        for block in doc.blocks(
            pages=range(min(pages) - 1, max(pages)), layers=tuple(sorted(layers))
        )
        if block.page + 1 in pages and normalize_eval(block.text or "").strip()
    ]
    tp = _true_positives(predicted, reference, doc)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(reference)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return Scored(doc_name, slices, tp, len(predicted), len(reference), f1)


def _true_positives(predicted: Sequence[Block], reference: Sequence[Triple], doc: Tree) -> int:
    """Rulings 4 and 5: the one-to-one match, then triple equality over the matched pairs."""
    folded = [(block, normalize_eval(block.text or "")) for block in predicted]
    taken: set[int] = set()
    tp = 0
    for row in reference:
        needle = normalize_eval(row.text)
        best: tuple[int, int, int] | None = None
        for at, (block, text) in enumerate(folded):
            if at in taken or block.page + 1 != row.page or block.layer != row.layer:
                continue
            edits = distance(needle, text)
            if edits > row.max_diffs:
                continue
            candidate = (edits, block.ord, at)
            if best is None or candidate < best:
                best = candidate
        if best is None:
            continue
        taken.add(best[2])
        matched = folded[best[2]][0]
        parent = doc.block(matched.parent) if matched.parent is not None else None
        found = (matched.kind, matched.layer, None if parent is None else parent.kind)
        tp += found == row.triple
    return tp


def metrics(run: Run, scored: Sequence[Scored], *, min_n: int = MIN_SLICE_N) -> tuple[Metric, ...]:
    """Ruling 7: one row per slice, then `__macro__`. An `unknown` run yields `unknown` rows."""
    by_slice: dict[str, list[float]] = {}
    for one in scored:
        if one.f1 is None:
            continue
        for key in one.slices or (UNSLICED,):
            by_slice.setdefault(key, []).append(one.f1)
    if not by_slice:
        return (_unknown(run, MACRO, 0),)
    unknown_run = run.status == "unknown"
    rows = [
        _slice_row(run, key, values, min_n=min_n, unknown=unknown_run)
        for key, values in sorted(by_slice.items())
    ]
    headline = macro(
        (Slice.of(key, values) for key, values in sorted(by_slice.items())), min_n=min_n
    )
    total = sum(len(values) for values in by_slice.values())
    if unknown_run or headline.estimate.value is None:
        rows.append(_unknown(run, MACRO, total))
    else:
        rows.append(_ok(run, MACRO, headline.estimate))
    return tuple(rows)


def _slice_row(run: Run, key: str, values: Sequence[float], *, min_n: int, unknown: bool) -> Metric:
    """One slice's row: the mean of its documents' F1, or `unknown` under `min_slice_n`."""
    one = macro([Slice.of(key, values)], min_n=min_n)
    if unknown or one.estimate.value is None:
        return _unknown(run, key, len(values))
    return _ok(run, key, one.estimate)


def _ok(run: Run, key: str, estimate: Estimate) -> Metric:
    return Metric(
        run_id=run.run_id,
        metric=METRIC,
        slice_key=key,
        value=estimate.value,
        n=estimate.n,
        ci_lo=estimate.ci_lo,
        ci_hi=estimate.ci_hi,
        method=estimate.method,
        truth_kind=TRUTH_KIND,
        state="ok",
    )


def _unknown(run: Run, key: str, n: int) -> Metric:
    return Metric(
        run_id=run.run_id,
        metric=METRIC,
        slice_key=key,
        value=None,
        n=n,
        ci_lo=None,
        ci_hi=None,
        method="none",
        truth_kind=TRUTH_KIND,
        state="unknown",
    )
