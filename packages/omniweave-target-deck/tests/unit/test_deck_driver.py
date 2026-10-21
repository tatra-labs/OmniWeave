"""`compile.deck.native` at release 1: a card that says `implemented = false`, and a driver that
refuses with the card's own reason. A user ruling of 2026-10-21 took 16-roadmap.md R-Q8's fallback
(D910); the shape is video's (09-generation.md section 12.4, D760).
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.errors import TargetError
from omniweave_core.out.card import CompileCard, targets
from omniweave_core.out.compile import CompileV1
from omniweave_ports import ProbeStatus
from omniweave_target_deck.driver import CARD, REASON, DeckCompiler

DIST_ROOT = Path(__file__).resolve().parents[2]


def _card() -> DriverCard:
    loaded = load_card(CARD.read_bytes(), origin="driver_path", source=str(CARD))
    assert isinstance(loaded, DriverCard)
    return loaded


def test_the_card_says_not_implemented_and_why() -> None:
    compile_ = CompileCard.of(_card())
    assert (compile_.target, compile_.implemented, compile_.reason) == ("deck", False, REASON)
    assert "R-Q8" in REASON
    assert "2026-10-21" in REASON
    [row] = targets([_card()])
    assert row.as_json()["implemented"] is False
    assert row.as_json()["reason"] == REASON


def test_the_card_keeps_the_seam_09_section_12_fixes() -> None:
    """The deck column: html / owdeck/1, unit page, embedded citations, runtime rules, the deck
    Toolchain, `render` determinism, `structure` fidelity and R4 refused."""
    compile_ = CompileCard.of(_card())
    assert (compile_.carrier, compile_.il, compile_.unit) == ("html", "owdeck/1", "page")
    assert (compile_.citations, compile_.toolchain) == ("embedded", "deck")
    assert compile_.runtime_rules is True
    assert {"part", "render"} <= set(compile_.determinism)
    assert compile_.fidelity == "structure"
    assert compile_.laws == ("r1", "r2", "r3", "r5", "r6", "r7")


def test_no_reader_and_no_table_is_claimed() -> None:
    """`parse.deck.native` and the ~90-row table are W9.5's, unbuilt: the card names neither."""
    compile_ = CompileCard.of(_card())
    assert (compile_.read_back, compile_.constructs, compile_.constructs_digest) == ("", "", "")
    assert (compile_.media_type, compile_.suffix) == ("", "")


def test_the_package_declares_the_driver_and_the_target() -> None:
    project = tomllib.loads((DIST_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    entry_points = project["entry-points"]
    assert entry_points["omniweave.drivers"] == {"compile.deck.native": "omniweave_target_deck"}
    assert entry_points["omniweave.targets"] == {"deck": "omniweave_target_deck"}


def test_the_probe_is_unavailable_and_names_the_reason() -> None:
    verdict = DeckCompiler.probe(None)  # type: ignore[arg-type]
    assert verdict.status is ProbeStatus.UNAVAILABLE
    assert REASON in verdict.detail
    assert verdict.missing == ("the deck Toolchain",)
    assert verdict.fix_hint == "ow out targets"


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.carrier("il/p01.html", "<section/>"),
        lambda c: c.rules(),
        lambda c: c.measure(),
        lambda c: c.lower(None, None, None, None),
        lambda c: c.postflight("deck/index.html", None),
        lambda c: c.project(None, None),
    ],
)
def test_every_method_refuses_with_the_cards_reason(call: Callable[[Any], object]) -> None:
    compiler: CompileV1 = DeckCompiler()
    with pytest.raises(TargetError, match="implemented = false") as caught:
        call(compiler)
    assert caught.value.code() == "OW_TARGET_NOT_IMPLEMENTED"
    assert str(caught.value).startswith("compile.deck.native cannot")
    assert REASON in str(caught.value)
