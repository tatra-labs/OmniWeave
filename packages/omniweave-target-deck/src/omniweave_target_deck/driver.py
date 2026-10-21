"""`compile.deck.native` at release 1: a `CompileV1` that refuses, and says why. **D910.**

A user ruling of 2026-10-21 took 16-roadmap.md R-Q8's fallback for the deck Toolchain: the target
"demotes to `[compile] implemented = false` like `video`". So the shape is video's (D760): the card
is the claim, this class is what its `entrypoint` names, and a host that resolves the target despite
the flag gets a refusal naming the card's reason, never a half-built deck. `probe()` answers
`unavailable` with the same reason, which prunes the target from a Plan before anything is lowered.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, NoReturn

from omniweave_core.errors import TargetError
from omniweave_ports import ProbeEnv, ProbeStatus, ProbeVerdict, Scalar

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

__all__ = ["CARD", "REASON", "DeckCompiler"]

CARD: Final = Path(__file__).with_name("driver.toml")
REASON: Final[str] = tomllib.loads(CARD.read_text(encoding="utf-8"))["compile"]["reason"]
"""The card's own sentence, read once: the refusal and the listing say the same thing."""


def _refuse(what: str) -> NoReturn:
    raise TargetError(
        f"compile.deck.native cannot {what}: [compile] implemented = false, because {REASON}",
        symbol="OW_TARGET_NOT_IMPLEMENTED",
        fix="ow out targets   # lists the targets that are implemented",
    )


class DeckCompiler:
    """Every method refuses with the card's reason; the probe reports it as unavailable."""

    PORT: ClassVar[str] = "compile/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        del env
        return ProbeVerdict(
            status=ProbeStatus.UNAVAILABLE,
            detail=f"implemented = false: {REASON}",
            missing=("the deck Toolchain",),
            fix_hint="ow out targets",
        )

    def __init__(self, **config: Scalar) -> None:
        self.config = config

    def carrier(self, path: str, text: str) -> CarrierDoc:
        del path, text
        _refuse("parse an owdeck/1 unit")

    def rules(self) -> Mapping[str, Sequence[RuleSpec]]:
        _refuse("enumerate its rules")

    def measure(self) -> TextMeasure | None:
        _refuse("measure")

    def lower(self, plan: Plan, il: ILBundle, ledger: AssetLedger, io: DriverIO) -> DriverResult:
        del plan, il, ledger, io
        _refuse("lower a Plan")

    def postflight(self, artifact: str, plan: Plan) -> Receipt:
        del artifact, plan
        _refuse("verify an artefact")

    def project(self, doc: Doc, io: DriverIO) -> ILBundle:
        del doc, io
        _refuse("project a Doc")
