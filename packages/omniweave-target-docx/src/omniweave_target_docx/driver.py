"""`compile.docx.native`, the flow target: owflow/1's carrier, rules and lowering. **D781-D783.**

09-generation.md section 12.3. *"It is the falsification test. A flow document has no canvas, no
z-order, no `viewBox`, no absolute geometry and no bake tier."* The card, `constructs.toml`,
`kind_map.toml` and `normalizers.py` sit beside this file, and `lower/` beside them. D781
built what `ow out check` runs: the carrier, the ConstructTable's rules and the six section 12.3
names. D782 builds `lower()` and `postflight()`, and D783 notes and embedded citations, which
make the card `implemented = true`.

## Rulings

1. **The carrier's block and invisible sets come from owflow/1.** `html_carrier()` inserts
   `"\n"` at each block boundary and drops each invisible element's text (09 section 3.1's `html`
   row). The blocks are the table's block constructs, and the invisible elements are the tags of
   its `visible = false` rows: a note body renders in the notes area, never in the text.
2. **The pack is two halves.** `omniweave_core.out.conformance.table_pack()` builds the
   forbidden rows, the closed set and the normalize warnings from the table, and `cite_pack()`
   the cite facts and the cite batch (D791). `rules.py` holds the structural and grammar rules.
   The `pos.*` forbidden rows are section 12.3's sixth rule, *"no positioning construct
   present"*.
3. **The table is read once, when the rules are first asked for.** `__init__` loads nothing, as
   every Port's constructor (18-api-sketch.md section 6.2), so the table is read lazily and kept.
4. **`measure()` is `None`.** A flow document's line breaks are the renderer's, and no owflow/1
   rule measures, so nothing is skipped for want of an estimator.

## Rulings (D782)

5. **`lower()` reads the job's clock from `job.json`.** 09 section 12.3 writes `dcterms` from
   `job.determinism.clock_ns`, and `lower()`'s four arguments carry no clock. The bundle's root is
   the JobDir's `il/`, so the clock is the JobDir's own, which the worker and `ow out verify`
   read too.
6. **`postflight()` reads the package back and asserts 09 section 5.3's four preconditions.**
   `check_package()` raises on a member that does not decompress, a dangling relationship and a
   part with no content type. The unit count is the document's `w:sectPr` count, one a unit,
   against `plan.unit_count`. The receipt reports `classify_and_assert()`'s outcomes with every
   edited unit visually changed, as owtext's does (D777): `lower()` rebuilds every part, so it
   patches none in place.
7. **A canvas format with no page is a receipt warning, not a refusal.** The Brief's
   `## canvas - format` is free text, and a Brief written for a deck says `16:9`. The page is
   then the template's letter, and the receipt's `page_box` row says which page was used and why.

## Rulings (D783)

8. **The probe is OK.** python-docx and lxml are the distribution's own dependencies, so an
   installed target has them, and nothing else is needed: no Node, no browser, no service.
9. **`project()` refuses by name**, as owtext's does: the card says `[compile.round_trip]
   project = false`, because no Doc-to-owflow/1 projection is built. `read_back` is a parse
   driver's, `parse.docx.native`.
10. **The receipt's `citations_channel` is read from the part.** The provenance part is written
    whether or not anything is cited, so postflight counts its rows. A package without it is a
    `failed` row, never a refusal: the four hard preconditions are 09 section 5.3's, and
    postflight decides no gate.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final

from docx.oxml.ns import qn
from lxml import etree  # type: ignore[attr-defined] -- lxml ships no stubs
from omniweave_core.errors import TargetError
from omniweave_core.out import (
    ArtefactDeterminism,
    CheckValue,
    ConstructTable,
    Receipt,
    classify_and_assert,
    html_carrier,
    part_digest,
)
from omniweave_core.out.carrier import parse_selector
from omniweave_core.out.conformance import cite_pack, table_pack
from omniweave_core.out.job import Job
from omniweave_core.out.opc import check_package, check_unit_count
from omniweave_core.out.receipt import receipt_part_digest
from omniweave_ports import ArtifactRef, DriverResult, ProbeEnv, ProbeStatus, ProbeVerdict, Scalar

from omniweave_target_docx import normalizers, rules
from omniweave_target_docx.lower._pack import build, page_of
from omniweave_target_docx.rules import BLOCKS

if TYPE_CHECKING:
    from omniweave_core.model.doc import Doc
    from omniweave_core.out import (
        AssetLedger,
        CarrierDoc,
        ILBundle,
        Plan,
        RuleSpec,
        TextMeasure,
    )
    from omniweave_ports import DriverIO

__all__ = [
    "BLOCKS",
    "CARD",
    "HERE",
    "MAX_UNITS",
    "NORMALIZERS",
    "PROVENANCE",
    "DocxCompiler",
    "table",
]

HERE: Final = Path(__file__).parent
CARD: Final = HERE / "driver.toml"
_COMPILE: Final = tomllib.loads(CARD.read_text(encoding="utf-8"))["compile"]
MAX_UNITS: Final[int] = _COMPILE["max_units"]
PROVENANCE: Final[str] = _COMPILE["provenance_part"]
"""`customXml/omniweave-provenance.json`: the embedded channel, named once, by the card."""
_DOCUMENT: Final = "word/document.xml"
_SECT: Final = qn("w:sectPr")
_PARSER: Final = etree.XMLParser(resolve_entities=False, no_network=True)
"""The card's own sentence, read once: the refusal and `ow out targets` say the same thing."""

NORMALIZERS: Final[Mapping[str, Callable[[str], str]]] = {
    "bcp47_case": normalizers.bcp47_case,
    "collapse_space": normalizers.collapse_space,
    "int_text": normalizers.int_text,
}


@cache
def table() -> ConstructTable:
    """Ruling 3: `constructs.toml`, loaded and asserted once."""
    return ConstructTable.load(HERE / "constructs.toml", NORMALIZERS)


@cache
def _invisible() -> frozenset[str]:
    return frozenset(
        parse_selector(row.selector, "html").tag.removeprefix("html|")
        for row in table().rows
        if not row.visible
    )


class DocxCompiler:
    """owflow/1's carrier, rules and lowering; the card says what is not lowered yet."""

    PORT: ClassVar[str] = "compile/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        del env
        return ProbeVerdict(status=ProbeStatus.OK, detail="python-docx and lxml only (ruling 8)")

    def __init__(self, **config: Scalar) -> None:
        """STATIC CONFIG ONLY. Loads nothing, opens nothing (ruling 3)."""
        self.config = config

    def carrier(self, path: str, text: str) -> CarrierDoc:
        return html_carrier(path, text, strict=False, blocks=BLOCKS, invisible=_invisible())

    def rules(self) -> Mapping[str, Sequence[RuleSpec]]:
        """Ruling 2: the table's halves under `construct` and `cite`, then `rules.py`'s."""
        return {
            "construct": table_pack(table(), "docx", NORMALIZERS),
            "cite": cite_pack(table(), "docx"),
            **rules.rules(),
        }

    def measure(self) -> TextMeasure | None:
        """Ruling 4."""
        return None

    def lower(self, plan: Plan, il: ILBundle, ledger: AssetLedger, io: DriverIO) -> DriverResult:
        """Preflight, every unit in Plan order, then one `.docx` (ruling 5 for its clock)."""
        payload = build(
            plan,
            il,
            ledger,
            carrier=self.carrier,
            table=table(),
            normalizers=NORMALIZERS,
            clock_ns=Job.load(Path(il.root).parent).determinism.clock_ns,
            max_units=MAX_UNITS,
            provenance=PROVENANCE,
        )
        return DriverResult(outcome="ok", produced=(ArtifactRef.of("artifact", payload, io),))

    def postflight(self, artifact: str, plan: Plan) -> Receipt:
        """Ruling 6: the package re-read, never the gate re-run (OUT23)."""
        data = Path(artifact).read_bytes()
        members = check_package(data)
        document = etree.fromstring(members[_DOCUMENT], _PARSER)
        sections = sum(1 for _ in document.iter(_SECT))
        check_unit_count(sections, plan.unit_count)
        classified = classify_and_assert(plan, baked={}, visual_changed=lambda _unit: True)
        canvas = plan.brief.value("canvas", "format")
        page = page_of(canvas)
        return Receipt(
            schema="omniweave.out-receipt/1",
            target="docx",
            slug=plan.slug,
            artifact_gen=plan.artifact_gen,
            output={
                "path": artifact,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
            part_digest=receipt_part_digest(part_digest(members)),
            determinism=(ArtefactDeterminism.PART, ArtefactDeterminism.BYTE),
            gate_status=plan.gate_status,
            delivery=plan.delivery,
            checks=(
                CheckValue("zip_integrity", "passed", f"{len(members)} members decompress"),
                CheckValue("unit_count", "passed", f"{sections} sections == unit_count"),
                CheckValue("internal_relationships", "passed", "every target is a member"),
                CheckValue("content_types", "passed", "every part has a content type"),
                CheckValue(
                    "page_box",
                    "passed" if page is not None else "warning",
                    page or f"canvas format {canvas!r} names no page; the page is letter",
                ),
                _citations(members),
                CheckValue("bake_used", "not-applicable", "owflow/1 has no bake row"),
                CheckValue("measure_available", "not-applicable", 'measure = "none"'),
            ),
            units={unit: c.outcome for unit, c in classified.items()},
            counts=dict(Counter(c.outcome for c in classified.values())),
            portability={
                "generic_only_font_stacks": (),
                "unresolved_brief_tokens": (),
                "external_asset_refs": (),
                "unsafe_exported_faces": (),
            },
            normalizations=(),
            degradations=(),
            skipped_checks=(),
            truncations=(),
        )

    def project(self, doc: Doc, io: DriverIO) -> ILBundle:
        """Ruling 9: `[compile.round_trip] project = false`, refused by name."""
        del doc, io
        raise TargetError(
            "compile.docx.native cannot project a Doc back to owflow/1: its card says "
            "[compile.round_trip] project = false",
            symbol="OW_TARGET_PROJECT_UNAVAILABLE",
            fix="ow out back <slug> --gen <gen>   # edit from the retained IL, not a projection",
        )


def _citations(members: Mapping[str, bytes]) -> CheckValue:
    """Ruling 10: the embedded channel's rows, counted from the part itself."""
    raw = members.get(PROVENANCE)
    if raw is None:
        return CheckValue("citations_channel", "failed", f"no {PROVENANCE} in the package")
    rows = json.loads(raw).get("cites", [])
    return CheckValue("citations_channel", "passed", f"embedded: {len(rows)} cite row(s)")
