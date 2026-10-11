"""`compile.video.native` at release 1: a card that says `implemented = false`, and a driver
that refuses with the card's own reason (09-generation.md section 12.4; 16-roadmap.md W9.6).
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.errors import TargetError, explain
from omniweave_core.out.card import CompileCard, targets
from omniweave_core.out.compile import CompileV1
from omniweave_ports import ProbeStatus
from omniweave_target_video.driver import CARD, REASON, VideoCompiler

DIST_ROOT = Path(__file__).resolve().parents[2]


def _card() -> DriverCard:
    loaded = load_card(CARD.read_bytes(), origin="driver_path", source=str(CARD))
    assert isinstance(loaded, DriverCard)
    return loaded


def test_the_card_says_not_implemented_and_why() -> None:
    compile_ = CompileCard.of(_card())
    assert (compile_.target, compile_.implemented, compile_.reason) == ("video", False, REASON)
    [row] = targets([_card()])
    assert row.as_json()["implemented"] is False
    assert row.as_json()["reason"] == REASON


def test_the_card_names_the_seam_09_fixes() -> None:
    """Section 12.4's table: html / owmotion/1, unit scene, sidecar citations, frame, no R3."""
    compile_ = CompileCard.of(_card())
    assert (compile_.carrier, compile_.il, compile_.unit) == ("html", "owmotion/1", "scene")
    assert compile_.citations == "sidecar"
    assert "frame" in compile_.determinism
    assert "r3" not in compile_.laws
    assert compile_.fidelity == "none"


def test_the_package_declares_the_driver_and_the_target() -> None:
    project = tomllib.loads((DIST_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    entry_points = project["entry-points"]
    assert entry_points["omniweave.drivers"] == {"compile.video.native": "omniweave_target_video"}
    assert entry_points["omniweave.targets"] == {"video": "omniweave_target_video"}


def test_the_probe_is_unavailable_and_names_the_reason() -> None:
    verdict = VideoCompiler.probe(None)  # type: ignore[arg-type]
    assert verdict.status is ProbeStatus.UNAVAILABLE
    assert REASON in verdict.detail
    assert verdict.fix_hint == "ow out targets"


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.carrier("il/s01.html", "<section/>"),
        lambda c: c.rules(),
        lambda c: c.measure(),
        lambda c: c.lower(None, None, None, None),
        lambda c: c.postflight("out.webm", None),
        lambda c: c.project(None, None),
    ],
)
def test_every_method_refuses_with_the_cards_reason(call: Callable[[Any], object]) -> None:
    compiler: CompileV1 = VideoCompiler()
    with pytest.raises(TargetError, match="implemented = false") as caught:
        call(compiler)
    assert caught.value.code() == "OW_TARGET_NOT_IMPLEMENTED"
    assert REASON in str(caught.value)
    assert explain("OW_TARGET_NOT_IMPLEMENTED").numeric == "OW-T-514"
