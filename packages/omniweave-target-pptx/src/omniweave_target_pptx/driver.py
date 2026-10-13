"""`compile.pptx.native`, the flagship target: owsvg/1's carrier and rules. **D789.**

09-generation.md section 12.1. *"A closed SVG subset. The `viewBox` is the canvas and one `<svg>`
root is one slide."* The card, `constructs.toml`, `kind_map.toml` and `normalizers.py` sit beside
this file, and the hand-written rules in `rules/`, one rule a file. This cell builds what
`ow out check` runs: the carrier, the table's rules and the structural band; D790 adds the
grammar band, and D791 the references, effects and cite rules. D792 adds `measure.py`, D795 to
D801 the lowering family by family (`lower/`), and D802 its manual regions and citations, the
last of the table's families: the card says `implemented = true`.

## Rulings

1. **The carrier is the framework's `svg` carrier, read with recovery for the check.** Its
   `visible_text` is 09 section 3.1's `svg` row, a line for each top-most `<text>`, which is what
   `ow out stamp` addresses and R2 compares.
2. **The pack is two halves.** `omniweave_core.out.conformance.table_pack()` builds the forbidden
   rows, `id` with `<style>` (`OW-T-402`), the closed set, the normalize warnings and the bake
   rows from the table, and `cite_pack()` the cite facts and the cite batch (D791). `rules/`
   holds the rest. The card's `bake` is the pack's, so a bake construct is an error while
   `bake = "unavailable"` (09 section 3.3).
3. **The table is read once, when the rules are first asked for.** `__init__` loads nothing, as
   every Port's constructor (18-api-sketch.md section 6.2).
4. **`measure()` is `measure.py`'s one estimator, over the faces the config names** (D792).
   `[drivers."compile.pptx.native".config] font_dirs` lists absolute directories, and an empty
   list, the default, or a uharfbuzz that will not import, is `None`: every rule declaring
   `needs={"measure"}` is then a recorded skip and the gate `unverified`, never `passed`.
   Repeated calls return the identical object, which the kit asserts (09 section 4.4), and the
   fonts are read on first use, not in `__init__`. A relative directory is refused when the
   compiler is built, because a target resolves no path against the working directory (G8).

## Rulings (D795)

5. **`lower()` is `lower._pack.build()`, over the job's clock.** 09 section 12.1 writes the
   package's `dcterms` from `job.determinism.clock_ns`, and `lower()`'s four arguments carry no
   clock, so the clock is the JobDir's own, `il.root`'s parent, as docx reads it. Families not yet
   lowered are preflight check 1's refusal (`omniweave_core.out.lowering`), so the card stays
   `implemented = false` while they land.
6. **`postflight()` re-reads the package and asserts 09 section 5.3's preconditions.**
   `check_package()` raises on a member that does not decompress, a dangling relationship or a
   part with no content type, and `slide_count` is the presentation's `p:sldId` count against
   `plan.unit_count`. 09 section 12.1 names the rows: `zip_integrity`, `slide_count`, and
   `internal_relationships: enforced-at-build`, whose fixture is the test that breaks the part
   graph and watches `lower._pack` raise. The receipt reports `classify_and_assert()`'s outcomes
   with every edited unit visually changed: `lower()` rebuilds every slide, and patches none in
   place.
7. **`project()` is refused by name**, as docx's is: the card says `[compile.round_trip]
   project = false` (09 Q2).
"""

from __future__ import annotations

import hashlib
import tomllib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final

from lxml import etree  # type: ignore[attr-defined] -- lxml ships no stubs
from omniweave_core.errors import ConfigError, TargetError
from omniweave_core.out import (
    ArtefactDeterminism,
    CheckValue,
    ConstructTable,
    Receipt,
    classify_and_assert,
    part_digest,
)
from omniweave_core.out import provenance as channel
from omniweave_core.out.carrier.xml import svg_carrier
from omniweave_core.out.conformance import cite_pack, table_pack
from omniweave_core.out.job import Job
from omniweave_core.out.opc import check_package, check_unit_count
from omniweave_core.out.receipt import receipt_part_digest
from omniweave_ports import ArtifactRef, DriverResult, ProbeEnv, ProbeStatus, ProbeVerdict, Scalar
from pptx.oxml.ns import qn

from omniweave_target_pptx import normalizers, rules
from omniweave_target_pptx.lower._pack import build

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
    "BAKE",
    "CARD",
    "HERE",
    "MAX_UNITS",
    "NORMALIZERS",
    "PROVENANCE",
    "PptxCompiler",
    "table",
]

HERE: Final = Path(__file__).parent
CARD: Final = HERE / "driver.toml"
_COMPILE: Final = tomllib.loads(CARD.read_text(encoding="utf-8"))["compile"]
PROVENANCE: Final[str] = _COMPILE["provenance_part"]
"""`customXml/omniweave-provenance.json`: the embedded channel, named once, by the card."""
BAKE: Final[str] = _COMPILE["bake"]
"""Ruling 2: the card's `[compile] bake`, which decides a bake row's severity."""
MAX_UNITS: Final[int] = _COMPILE["max_units"]
_PRESENTATION: Final = "ppt/presentation.xml"
_SLIDE_ID: Final = qn("p:sldId")
_SLIDE_SIZE: Final = qn("p:sldSz")
_PARSER: Final = etree.XMLParser(resolve_entities=False, no_network=True)
_ENFORCED: Final = (
    "packages/omniweave-target-pptx/tests/unit/test_pptx_lower.py"
    "::test_a_dangling_relationship_is_refused_at_build"
)
"""Ruling 6: the kit test that proves `internal_relationships` is enforced at build."""

NORMALIZERS: Final[Mapping[str, Callable[[str], str]]] = normalizers.BY_NAME


@cache
def table() -> ConstructTable:
    """Ruling 3: `constructs.toml`, loaded and asserted once."""
    return ConstructTable.load(HERE / "constructs.toml", NORMALIZERS)


class PptxCompiler:
    """owsvg/1's carrier, rules and lowering to DrawingML, and the package read back."""

    PORT: ClassVar[str] = "compile/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        del env
        return ProbeVerdict(
            status=ProbeStatus.OK,
            detail="python-pptx and lxml; uharfbuzz measures where font_dirs names faces",
        )

    def __init__(self, **config: Scalar | list[str]) -> None:
        """STATIC CONFIG ONLY. Loads nothing, opens nothing (rulings 3 and 4)."""
        self.config = config
        raw = config.get("font_dirs") or []
        dirs = [Path(str(d)) for d in (raw if isinstance(raw, list) else [raw])]
        relative = [str(d) for d in dirs if not d.is_absolute()]
        if relative:
            raise ConfigError(
                f"font_dirs {relative} are not absolute: a target resolves no path against the "
                "working directory",
                fix='ow config set drivers."compile.pptx.native".config.font_dirs '
                '["<absolute directory>"]',
            )
        self._font_dirs = tuple(dirs)
        self._measure: TextMeasure | None = None

    def carrier(self, path: str, text: str) -> CarrierDoc:
        """Ruling 1."""
        return svg_carrier(path, text, strict=False)

    def rules(self) -> Mapping[str, Sequence[RuleSpec]]:
        """Ruling 2: the table's halves under `construct` and `cite`, then `rules/`'s."""
        return {
            "construct": table_pack(table(), "pptx", NORMALIZERS, bake=BAKE),
            "cite": cite_pack(table(), "pptx"),
            **rules.rules(),
        }

    def measure(self) -> TextMeasure | None:
        """Ruling 4: one estimator a compiler, or `None` without fonts or uharfbuzz."""
        if not self._font_dirs:
            return None
        if self._measure is None:
            try:
                from omniweave_target_pptx.measure import (  # noqa: PLC0415 -- ruling 4
                    FontBook,
                    HarfBuzzMeasure,
                )
            except ImportError:
                return None
            self._measure = HarfBuzzMeasure(FontBook(self._font_dirs))
        return self._measure

    def lower(self, plan: Plan, il: ILBundle, ledger: AssetLedger, io: DriverIO) -> DriverResult:
        """Ruling 5: preflight, a slide for every unit in Plan order, then one `.pptx`."""
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
        deck = etree.fromstring(members[_PRESENTATION], _PARSER)
        slides = sum(1 for _ in deck.iter(_SLIDE_ID))
        check_unit_count(slides, plan.unit_count)
        size = deck.find(_SLIDE_SIZE)
        classified = classify_and_assert(plan, baked={}, visual_changed=lambda _unit: True)
        return Receipt(
            schema="omniweave.out-receipt/1",
            target="pptx",
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
                CheckValue("slide_count", "passed", f"{slides} slides == unit_count"),
                CheckValue(
                    "internal_relationships",
                    "enforced-at-build",
                    "lower._pack checks the package it builds",
                    fixture=_ENFORCED,
                ),
                CheckValue("content_types", "passed", "every part has a content type"),
                CheckValue(
                    "slide_size",
                    "passed",
                    "none" if size is None else f"{size.get('cx')}x{size.get('cy')} EMU",
                ),
                channel.citations(members, PROVENANCE),
                CheckValue("bake_used", "not-applicable", 'bake = "unavailable"'),
                CheckValue(
                    "measure_available",
                    "not-applicable",
                    "the lowering shapes no text; measurement is the gate's",
                ),
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
        """Ruling 7: `[compile.round_trip] project = false`, refused by name."""
        del doc, io
        raise TargetError(
            "compile.pptx.native cannot project a Doc back to owsvg/1: its card says "
            "[compile.round_trip] project = false",
            symbol="OW_TARGET_PROJECT_UNAVAILABLE",
            fix="ow out back <slug> --gen <gen>   # edit from the retained IL, not a projection",
        )
