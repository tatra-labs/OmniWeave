"""`compile.docx.native`, the flow target: owflow/1's carrier and rules. **D781.**

09-generation.md section 12.3. *"It is the falsification test. A flow document has no canvas, no
z-order, no `viewBox`, no absolute geometry and no bake tier."* The card, `constructs.toml`,
`kind_map.toml` and `normalizers.py` sit beside this file. This cell builds what `ow out check`
runs: the carrier, the ConstructTable's rules and the six section 12.3 names. Lowering to
WordprocessingML is the next cell's, so the card says `implemented = false` with that reason,
and `lower()`, `postflight()` and `project()` refuse with it, as `compile.video.native` does.

## Rulings

1. **The carrier's block and invisible sets come from owflow/1.** `html_carrier()` inserts
   `"\n"` at each block boundary and drops each invisible element's text (09 section 3.1's `html`
   row). The blocks are the table's block constructs, and the invisible elements are the tags of
   its `visible = false` rows: a note body renders in the notes area, never in the text.
2. **The pack is two halves.** `omniweave_core.out.conformance.table_pack()` builds the
   forbidden rows, the closed set and the normalize warnings from the table, and `rules.py` holds
   the structural and grammar rules. The `pos.*` forbidden rows are section 12.3's sixth rule,
   *"no positioning construct present"*.
3. **The table is read once, when the rules are first asked for.** `__init__` loads nothing, as
   every Port's constructor (18-api-sketch.md section 6.2), so the table is read lazily and kept.
4. **`measure()` is `None`.** A flow document's line breaks are the renderer's, and no owflow/1
   rule measures, so nothing is skipped for want of an estimator.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, NoReturn

from omniweave_core.errors import TargetError
from omniweave_core.out import ConstructTable, html_carrier
from omniweave_core.out.carrier import parse_selector
from omniweave_core.out.conformance import table_pack
from omniweave_ports import ProbeEnv, ProbeStatus, ProbeVerdict, Scalar

from omniweave_target_docx import normalizers, rules

if TYPE_CHECKING:
    from omniweave_core.model.doc import Doc
    from omniweave_core.out import (
        AssetLedger,
        CarrierDoc,
        ILBundle,
        Plan,
        Receipt,
        RuleSpec,
        TextMeasure,
    )
    from omniweave_ports import DriverIO, DriverResult

__all__ = ["BLOCKS", "CARD", "HERE", "NORMALIZERS", "REASON", "DocxCompiler", "table"]

HERE: Final = Path(__file__).parent
CARD: Final = HERE / "driver.toml"
REASON: Final[str] = tomllib.loads(CARD.read_text(encoding="utf-8"))["compile"]["reason"]
"""The card's own sentence, read once: the refusal and `ow out targets` say the same thing."""

NORMALIZERS: Final[Mapping[str, Callable[[str], str]]] = {
    "bcp47_case": normalizers.bcp47_case,
    "collapse_space": normalizers.collapse_space,
    "int_text": normalizers.int_text,
}
BLOCKS: Final = frozenset(
    {
        "section", "h1", "h2", "h3", "h4", "h5", "h6", "p", "blockquote", "pre", "hr", "ul",
        "ol", "li", "dl", "dt", "dd", "table", "caption", "thead", "tbody", "tr", "th", "td",
        "figure", "figcaption", "div", "aside",
    }
)  # fmt: skip
"""Ruling 1: owflow/1's block constructs, by local name."""


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


def _refuse(what: str) -> NoReturn:
    raise TargetError(
        f"compile.docx.native cannot {what}: [compile] implemented = false, because {REASON}",
        symbol="OW_TARGET_NOT_IMPLEMENTED",
        fix="ow out check --target docx --stage early   # the gate runs; the compile does not",
    )


class DocxCompiler:
    """owflow/1's carrier and rules; the compile itself is refused until it is built."""

    PORT: ClassVar[str] = "compile/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        del env
        return ProbeVerdict(
            status=ProbeStatus.UNAVAILABLE,
            detail=f"implemented = false: {REASON}",
            missing=("lower() to WordprocessingML",),
            fix_hint="ow out targets",
        )

    def __init__(self, **config: Scalar) -> None:
        """STATIC CONFIG ONLY. Loads nothing, opens nothing (ruling 3)."""
        self.config = config

    def carrier(self, path: str, text: str) -> CarrierDoc:
        return html_carrier(path, text, strict=False, blocks=BLOCKS, invisible=_invisible())

    def rules(self) -> Mapping[str, Sequence[RuleSpec]]:
        """Ruling 2: the table's half under `construct`, then `rules.py`'s."""
        return {"construct": table_pack(table(), "docx", NORMALIZERS), **rules.rules()}

    def measure(self) -> TextMeasure | None:
        """Ruling 4."""
        return None

    def lower(self, plan: Plan, il: ILBundle, ledger: AssetLedger, io: DriverIO) -> DriverResult:
        del plan, il, ledger, io
        _refuse("lower a Plan")

    def postflight(self, artifact: str, plan: Plan) -> Receipt:
        del artifact, plan
        _refuse("read an artefact back")

    def project(self, doc: Doc, io: DriverIO) -> ILBundle:
        del doc, io
        _refuse("project a Doc to owflow/1")
