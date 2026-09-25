"""`pack()`: one retrieval to one `Answer`. Row 28's composition, which nothing performed. 02:252.

W6.6 shipped every stage 02:252 lists for this row -- `worth`, `allocate` (the tier table, the
cliff, reserve-then-render), `untrusted` (defanging on a copy), `render` (the nine sections) -- and
each is tested by handing it values. Nothing turned a `Response` into the `Candidate`s `allocate()`
reads or the `RenderedBlock`s `render()` prints. That step is here, and it is the last one between
`retrieve()` and a document an agent can read.

## WHAT IT READS, AND WHY NOT `Response` ALONE

`Candidate` needs the document a block belongs to and `worth()`'s four enums; `RenderedBlock` needs
the document, the page, the kind and the method. `Hit` carries none of the first three and not
`method` (07:2274's fourteen fields), so `pack()` reads `execute.Retrieval`, which carries the rows
the hits were hydrated from in the same snapshot. D523.

## THE STAGES, IN ORDER

1. **Defang each block's text on a copy** (`untrusted.defang`), and lower its served `quote`
   (`serve_quote`) when anything changed: 07:2588 -- *"a defanged block is emitted as `normalized`,
   marked, and counted"*. `byte_exact` is dropped with it, because the served text no longer equals
   the source bytes.
2. **Weigh and allocate**: one `Candidate` per hit, `worth()` over its row, `allocate()` over the
   tier `tier_for(indexed_blocks)` picks. The packed documents' blocks become the evidence in rank
   order.
3. **Everything that did not pack becomes a pointer**: a cliffed document is `cliffed`, a block
   dropped for room inside a packed document is `truncated`, each with the `ow_open` call that
   fetches it, so nothing that matched leaves the answer without a row saying where it went.
4. **The Verdict becomes the blocking lines and the trailer**: one `ow:blocking` line per
   `DegradeCause`, with its detail and its fix, and the trailer rows 10:676-686 print.

What this module does not do is withhold: `ow:sent-earlier` needs the session's emission ledger,
and no surface holds one yet (D525).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

from omniweave_core.answer.allocate import (
    BLOCK_OVERHEAD,
    DOC_OVERHEAD,
    Allocation,
    Candidate,
    allocate,
)
from omniweave_core.answer.budget import AnswerBudget, effective_max_chars, tier_for
from omniweave_core.answer.render import EN_DASH, Answer, Pointer, RenderedBlock
from omniweave_core.answer.untrusted import defang, serve_quote
from omniweave_core.answer.worth import worth

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omniweave_core.retrieve.execute import Hit, Retrieval
    from omniweave_core.retrieve.verdict import DegradeCause, Verdict
    from omniweave_core.store.reader import HydratedRow

__all__ = ["Packed", "doc_name", "pack"]

_NO_DRIVER: Final[str] = EN_DASH
"""`RenderedBlock.origin_driver` for every block, and D524 is why: the header prints the driver
(10:629) and 07:2305's hydration SELECT does not select `block.origin_driver`. An en dash is the
document's own spelling for a value it does not have (10:740)."""


@dataclass(frozen=True, slots=True)
class Packed:
    """The `Answer`, and the character envelope `render()` must be called with."""

    answer: Answer
    max_chars: int


def doc_name(uri: str) -> str:
    """The name a reader recognises: the last path segment of the document's URI.

    The worked Answer prints `policy.pdf p.14` and a `doc` column of `policy.pdf` (10:629, 10:657),
    not `file:///corpus/policy.pdf`. A URI with no path segment is printed whole.
    """
    path = urlsplit(uri).path or uri
    name = PurePosixPath(path).name
    return name or uri


def _cite(corpus: str, cite: str, *, qualify: bool) -> str:
    """10 section 6.1's per-surface emission rule: qualified when the deployment has two corpora."""
    return f"{corpus}:{cite}" if qualify else cite


def _block(hit: Hit, row: HydratedRow, *, corpus: str, qualify: bool) -> tuple[RenderedBlock, int]:
    """One evidence block, defanged on a copy. Returns the block and its sentinel count."""
    served = defang(row.text or "")
    changed = served.changed
    block = RenderedBlock(
        cite=_cite(corpus, row.cite, qualify=qualify),
        addr=row.addr,
        doc_uri=doc_name(row.uri),
        page=row.page,
        kind=row.kind.value,
        text=served.text,
        quote=serve_quote(row.quote, defanged=changed),
        trust=row.trust.name.lower(),
        method=row.method.value,
        origin_driver=_NO_DRIVER,
        byte_exact=hit.byte_exact and not changed,
        restriction=str(row.restriction_bits) if row.restriction_bits else EN_DASH,
        identity_grade=hit.identity_grade,
        defanged=changed,
    )
    return block, served.sentinels if changed else 0


def _pointers(
    allocation: Allocation, rows: Mapping[str, HydratedRow], *, corpus: str, qualify: bool
) -> tuple[Pointer, ...]:
    """Every document that did not pack, and every block dropped for room, as a fetchable row."""
    out: list[Pointer] = []
    for cliffed in allocation.cliffed:
        out.append(
            _pointer(
                cliffed.doc_key,
                cliffed.blocks,
                rows=rows,
                corpus=corpus,
                qualify=qualify,
                reason="cliffed",
            )
        )
    for plan in allocation.packed:
        if plan.dropped:
            out.append(
                _pointer(
                    plan.doc_key,
                    plan.dropped,
                    rows=rows,
                    corpus=corpus,
                    qualify=qualify,
                    reason="truncated",
                )
            )
    return tuple(out)


def _pointer(
    doc_key: str,
    blocks: Sequence[Candidate],
    *,
    rows: Mapping[str, HydratedRow],
    corpus: str,
    qualify: bool,
    reason: str,
) -> Pointer:
    cites = tuple(_cite(corpus, block.cite, qualify=qualify) for block in blocks)
    pages = tuple(sorted({rows[block.cite].page for block in blocks if block.cite in rows}))
    return Pointer(
        doc_uri=doc_name(doc_key),
        pages=pages,
        cites=cites,
        blocks=len(blocks),
        fetch=f'ow_open ref="{cites[0]}"' if cites else "",
        reason=reason,  # type: ignore[arg-type]
    )


def _blocking(causes: Sequence[DegradeCause]) -> tuple[str, ...]:
    """One `ow:blocking` line per failed gate, with its fix. 10:620's `> ... Fix: ...` form."""
    lines: list[str] = []
    for cause in causes:
        line = f"> {cause.gate}: {cause.detail}."
        if cause.fix:
            line += f" Fix: `{cause.fix}`"
        if cause.diag_codes:
            line += f" [{', '.join(cause.diag_codes)}]"
        lines.append(line)
    return tuple(lines)


def _trailer(verdict: Verdict, reasons: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """10:676-686's `verdict.*` rows after `verdict.state`, which `render` prints itself.

    An `off` Channel prints its reason, `semantic:off(vectors)`, as 10:678 does: `off` is an
    operator choice and the reason is which one."""
    channels = " ".join(
        f"{name}:{status.value}({reasons[name]})"
        if status.value == "off" and reasons.get(name)
        else f"{name}:{status.value}"
        for name, status in verdict.channels.items()
    )
    scanned = ", ".join(f"{key}: {value}" for key, value in verdict.scanned.items())
    best = "-" if verdict.best_score is None else f"{verdict.best_score:.4f}"
    cov = verdict.coverage
    return (
        ("verdict.gates", "[" + ", ".join(verdict.gates) + "]"),
        ("verdict.channels", channels),
        ("verdict.scanned", "{" + scanned + "}"),
        (
            "verdict.best_score",
            f"{best}  ceiling {verdict.score_ceiling:.4f}  scorer {verdict.scorer_version}",
        ),
        (
            "verdict.coverage",
            f"{{discovered: {cov.discovered}, indexed: {cov.indexed}, partial: {cov.partial}, "
            f"failed: {cov.failed}}}",
        ),
    )


def pack(
    retrieval: Retrieval,
    *,
    corpus: str,
    qualify: bool = False,
    max_chars: int | None = None,
    next_command: str = "",
) -> Packed:
    """One `Retrieval` to one `Answer`, and the envelope to render it in.

    `max_chars` is the caller's request (`ow_query`'s `max_chars`, 10:476); `None` takes the tier's.
    """
    response = retrieval.response
    verdict = response.verdict
    tier_index, tier = tier_for(retrieval.indexed_blocks)
    envelope = effective_max_chars(max_chars, tier)

    by_cite: dict[str, HydratedRow] = {}
    candidates: list[Candidate] = []
    blocks: dict[str, tuple[RenderedBlock, int]] = {}
    for hit in response.hits:
        row = retrieval.rows.get(hit.block_id)
        if row is None:
            continue
        by_cite[row.cite] = row
        blocks[row.cite] = _block(hit, row, corpus=corpus, qualify=qualify)
        candidates.append(
            Candidate(
                doc_key=row.uri,
                cite=row.cite,
                chars=row.chars or 0,
                score=hit.score,
                worth=worth(layer=row.layer, kind=row.kind, trust=row.trust, quote=row.quote),
                trust=row.trust,
                channels=frozenset(hit.channel_ranks),
            )
        )
    allocation = allocate(candidates, tier=tier, max_chars=max_chars)
    evidence = tuple(blocks[block.cite][0] for plan in allocation.packed for block in plan.blocks)
    sentinels = sum(blocks[block.cite][1] for plan in allocation.packed for block in plan.blocks)
    answer = Answer(
        state=verdict.state.value,
        corpus=corpus,
        generation=verdict.snapshot_gen,
        freshness=verdict.freshness,
        evidence=evidence,
        pointers=_pointers(allocation, by_cite, corpus=corpus, qualify=qualify),
        blocking=_blocking(verdict.degraded_because),
        trailer_extra=_trailer(verdict, retrieval.reasons),
        degradations=verdict.degradations,
        defanged_blocks=sum(1 for block in evidence if block.defanged),
        instruction_shaped=sentinels,
        blocks_matched=verdict.matches_before_packing,
        docs_matched=len({row.uri for row in by_cite.values()}),
        scorer_version=verdict.scorer_version,
        budget=AnswerBudget(
            tier_index=tier_index,
            blocks_below=tier.blocks_below,
            max_chars=envelope,
            chars_used=allocation.spent,
            max_docs=tier.max_docs,
            docs_used=allocation.docs_used,
            calls_allowed=tier.calls,
            call_ord=1,
            chars_deduped=0,
            doc_overhead=DOC_OVERHEAD,
            block_overhead=BLOCK_OVERHEAD,
        ),
        next_command=next_command,
    )
    return Packed(answer=answer, max_chars=envelope)
