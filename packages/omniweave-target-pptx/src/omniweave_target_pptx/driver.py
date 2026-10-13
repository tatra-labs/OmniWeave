"""`compile.pptx.native`, the flagship target: owsvg/1's carrier and rules. **D789.**

09-generation.md section 12.1. *"A closed SVG subset. The `viewBox` is the canvas and one `<svg>`
root is one slide."* The card, `constructs.toml`, `kind_map.toml` and `normalizers.py` sit beside
this file, and the hand-written rules in `rules/`, one rule a file. This cell builds what
`ow out check` runs: the carrier, the table's rules and the structural band; D790 adds the
grammar band, and D791 the references, effects and cite rules. `measure.py` and the lowering to
DrawingML are later cells, so the card says `implemented = false` with that reason, and
`lower()`, `postflight()` and `project()` refuse with it, as `compile.docx.native` did before its
lowering.

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
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, NoReturn

from omniweave_core.errors import ConfigError, TargetError
from omniweave_core.out import ConstructTable
from omniweave_core.out.carrier.xml import svg_carrier
from omniweave_core.out.conformance import cite_pack, table_pack
from omniweave_ports import ProbeEnv, ProbeStatus, ProbeVerdict, Scalar

from omniweave_target_pptx import normalizers, rules

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

__all__ = ["BAKE", "CARD", "HERE", "NORMALIZERS", "REASON", "PptxCompiler", "table"]

HERE: Final = Path(__file__).parent
CARD: Final = HERE / "driver.toml"
_COMPILE: Final = tomllib.loads(CARD.read_text(encoding="utf-8"))["compile"]
REASON: Final[str] = _COMPILE["reason"]
"""The card's own sentence, read once: the refusal and `ow out targets` say the same thing."""
BAKE: Final[str] = _COMPILE["bake"]
"""Ruling 2: the card's `[compile] bake`, which decides a bake row's severity."""

NORMALIZERS: Final[Mapping[str, Callable[[str], str]]] = normalizers.BY_NAME


@cache
def table() -> ConstructTable:
    """Ruling 3: `constructs.toml`, loaded and asserted once."""
    return ConstructTable.load(HERE / "constructs.toml", NORMALIZERS)


def _refuse(what: str) -> NoReturn:
    raise TargetError(
        f"compile.pptx.native cannot {what}: [compile] implemented = false, because {REASON}",
        symbol="OW_TARGET_NOT_IMPLEMENTED",
        fix="ow out check --target pptx --stage early   # the gate runs; the compile does not",
    )


class PptxCompiler:
    """owsvg/1's carrier and rules; the compile itself is refused until it is built."""

    PORT: ClassVar[str] = "compile/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        del env
        return ProbeVerdict(
            status=ProbeStatus.UNAVAILABLE,
            detail=f"implemented = false: {REASON}",
            missing=("lower() to DrawingML",),
            fix_hint="ow out targets",
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
        del plan, il, ledger, io
        _refuse("lower a Plan")

    def postflight(self, artifact: str, plan: Plan) -> Receipt:
        del artifact, plan
        _refuse("read an artefact back")

    def project(self, doc: Doc, io: DriverIO) -> ILBundle:
        del doc, io
        _refuse("project a Doc to owsvg/1")
