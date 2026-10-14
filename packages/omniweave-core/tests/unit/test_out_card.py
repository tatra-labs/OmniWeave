"""`omniweave_core.out.card`: `[compile]` read strictly, and the target listing.

09-generation.md section 12.4: `[compile]` is hard-error-on-unknown-key, `[capability.compile]`
ignores what it does not know with a degradation, and `ow out targets` prints the target, the flag
and the reason. The cards are the two shipped compile cards, read from their packages, and each
refusal is that card's text with one line changed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from omniweave_core.discovery import discover
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.errors import DriverHostError
from omniweave_core.out.card import CompileCard, targets

PACKAGES = Path(__file__).resolve().parents[3]
VIDEO = PACKAGES / "omniweave-target-video" / "src" / "omniweave_target_video" / "driver.toml"
OWTEXT = (
    PACKAGES / "omniweave-conform" / "src" / "omniweave_conform" / "suites" / "target" / "owtext"
)
VIDEO_TEXT = VIDEO.read_text(encoding="utf-8")


def card(text: str, source: str = "driver.toml") -> DriverCard:
    loaded = load_card(text.encode("utf-8"), origin="driver_path", source=source)
    assert isinstance(loaded, DriverCard)
    return loaded


def video(old: str, new: str) -> DriverCard:
    assert VIDEO_TEXT.count(old) == 1, old
    return card(VIDEO_TEXT.replace(old, new))


# ---------------------------------------------------------------------------
# The two shipped cards
# ---------------------------------------------------------------------------


def test_the_video_card_is_an_unimplemented_target_with_its_reason() -> None:
    c = CompileCard.of(card(VIDEO_TEXT))
    assert (c.driver, c.target, c.implemented) == ("compile.video.native", "video", False)
    assert c.reason.startswith("the hyperframes mining")
    assert (c.carrier, c.il, c.unit, c.fidelity) == ("html", "owmotion/1", "scene", "none")
    assert c.determinism == ("part", "frame")
    assert c.laws == ("r1", "r5", "r6", "r7")
    assert c.degradations == ()


def test_the_reference_card_is_an_implemented_target() -> None:
    c = CompileCard.of(card((OWTEXT / "driver.toml").read_text(encoding="utf-8")))
    assert (c.target, c.implemented, c.reason) == ("owtext", True, "")
    assert c.constructs_digest.startswith("sha256:")


# ---------------------------------------------------------------------------
# [compile] is closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "said"),
    [
        ('unit = "scene"\n', 'unit = "scene"\ncodec = "vp9"\n', "unknown key(s) ['codec']"),
        ('unit = "scene"\n', "", "is missing ['unit']"),
        ("reason = ", "# reason = ", "reason is required exactly when implemented = false"),
        ('carrier = "html"', 'carrier = "pdf"', "carrier = 'pdf' is not one of"),
        ('il = "owmotion/1"', 'il = "owmotion"', "il = 'owmotion' does not match"),
        ('citations = "sidecar"', 'citations = "footnotes"', "citations = 'footnotes'"),
        ('bake = "unavailable"', 'bake = "maybe"', "bake = 'maybe'"),
        ("\nmax_units = 64", "\nmax_units = 0", "max_units = 0 is not a positive integer"),
        ("\nmax_units = 64", "\nmax_units = true", "is not a positive integer"),
        ("\nimplemented = false\n", '\nimplemented = "no"\n', "'no' is not a boolean"),
        ('kind_map = ""', 'kind_map = ""\nwhen = 1', "[compile.round_trip] keys"),
        ('laws = ["r1", "r5", "r6", "r7"]', 'laws = ["r1", "r2"]', "r2 is not meaningful"),
        ('laws = ["r1", "r5", "r6", "r7"]', 'laws = "r1"', "is not a list of law names"),
        ('fidelity = "none"', 'fidelity = "lossless"', "fidelity 'lossless'"),
        ('determinism = ["part", "frame"]', 'determinism = ["frame"]', "must include part"),
    ],
)
def test_a_compile_table_that_breaks_its_grammar_is_a_card_error(
    old: str, new: str, said: str
) -> None:
    with pytest.raises(DriverHostError, match=re.escape(said)) as caught:
        CompileCard.of(video(old, new))
    assert caught.value.code() == "OW_CARD_INVALID"
    assert caught.value.fix == "ow drivers check driver.toml"


def test_an_implemented_target_may_not_carry_a_reason_or_lack_a_table() -> None:
    implemented = video("\nimplemented = false\n", "\nimplemented = true\n")
    with pytest.raises(DriverHostError, match="reason is only for a target with implemented"):
        CompileCard.of(implemented)
    unreasoned = VIDEO_TEXT.replace("\nimplemented = false\n", "\nimplemented = true\n")
    unreasoned = unreasoned.replace("reason = ", "# reason = ")
    with pytest.raises(DriverHostError, match="names its constructs and a sha256 digest"):
        CompileCard.of(card(unreasoned))


def test_an_implemented_target_declares_its_agent_doc_budget() -> None:
    """Ruling 5 (D762): 09 section 3.5 item 5 gates every target's agent document at it."""
    owtext = (OWTEXT / "driver.toml").read_text(encoding="utf-8")
    assert CompileCard.of(card(owtext)).agent_doc_tokens_max == 1200
    line = "agent_doc_tokens_max = 1200"
    assert owtext.count(line) == 1
    with pytest.raises(DriverHostError, match=r"declares agent_doc_tokens_max \(09 section 3.5\)"):
        CompileCard.of(card(owtext.replace(line, "# " + line)))
    with pytest.raises(DriverHostError, match="agent_doc_tokens_max = 0 is not a positive"):
        CompileCard.of(card(owtext.replace(line, "agent_doc_tokens_max = 0")))
    #  An unimplemented target with no table has nothing to document, so it may leave the key out.
    assert "agent_doc_tokens_max" not in VIDEO_TEXT
    assert CompileCard.of(card(VIDEO_TEXT)).agent_doc_tokens_max == 0


def test_an_unimplemented_target_that_names_a_table_declares_its_budget() -> None:
    """Ruling 5, as D781 reads it: a table is documented under a budget, implemented or not."""
    tabled = video('constructs = ""', 'constructs = "constructs.toml"')
    with pytest.raises(DriverHostError, match=r"naming a table declares agent_doc_tokens_max"):
        CompileCard.of(tabled)
    budgeted = VIDEO_TEXT.replace('constructs = ""', 'constructs = "constructs.toml"').replace(
        "\nmax_units = 64\n", "\nmax_units = 64\nagent_doc_tokens_max = 900\n"
    )
    assert CompileCard.of(card(budgeted)).agent_doc_tokens_max == 900


@pytest.mark.parametrize(
    ("old", "new", "said"),
    [
        (
            'media_type = "text/plain"',
            '# media_type = "text/plain"',
            "declares its media_type and suffix",
        ),
        ('suffix = ".txt"', '# suffix = ".txt"', "declares its media_type and suffix"),
        (
            'media_type = "text/plain"',
            'media_type = "plain text"',
            "media_type = 'plain text' does not match",
        ),
        ('suffix = ".txt"', 'suffix = "txt"', "suffix = 'txt' does not match"),
        ('suffix = ".txt"', 'suffix = ".TXT"', "suffix = '.TXT' does not match"),
    ],
)
def test_an_implemented_target_declares_its_artefacts_media_type_and_suffix(
    old: str, new: str, said: str
) -> None:
    """Ruling 6 (D770): the row's NOT NULL media_type and the path's suffix."""
    owtext = (OWTEXT / "driver.toml").read_text(encoding="utf-8")
    c = CompileCard.of(card(owtext))
    assert (c.media_type, c.suffix) == ("text/plain", ".txt")
    assert owtext.count(old) == 1
    with pytest.raises(DriverHostError, match=re.escape(said)):
        CompileCard.of(card(owtext.replace(old, new)))


def test_an_unimplemented_target_may_leave_its_media_type_out() -> None:
    assert "media_type" not in VIDEO_TEXT
    c = CompileCard.of(card(VIDEO_TEXT))
    assert (c.media_type, c.suffix) == ("", "")


def test_capability_compile_ignores_what_it_does_not_know_and_records_it() -> None:
    c = CompileCard.of(
        video(
            'assets = ["image", "font", "video", "audio"]',
            'assets = ["image", "hologram"]',
        )
    )
    assert c.assets == ("image",)
    assert c.degradations == ("asset role 'hologram' is unknown and was ignored",)
    c = CompileCard.of(video('determinism = ["part", "frame"]', 'determinism = ["part", "smell"]'))
    assert c.determinism == ("part",)
    assert c.degradations == ("determinism 'smell' is unknown and was ignored",)


# ---------------------------------------------------------------------------
# targets(): what `ow out targets` prints
# ---------------------------------------------------------------------------


def test_targets_lists_every_compile_card_with_its_flag_and_reason() -> None:
    cards = [
        card(VIDEO_TEXT, "video/driver.toml"),
        card((OWTEXT / "driver.toml").read_text(encoding="utf-8"), "owtext/driver.toml"),
    ]
    rows = targets(cards)
    assert [(r.target, r.implemented) for r in rows] == [("owtext", True), ("video", False)]
    video_row = rows[1].as_json()
    assert video_row["implemented"] is False
    assert video_row["reason"].startswith("the hyperframes mining")
    assert json.loads(json.dumps([r.as_json() for r in rows]))[1]["target"] == "video"
    #  The determinism class 10's roster names, as the card declares it (D761).
    assert rows[0].determinism == ("part", "byte")
    assert rows[0].as_json()["determinism"] == ["part", "byte"]
    assert rows[1].line().startswith("video    compile.video.native")
    assert "implemented = false: the hyperframes" in rows[1].line()


def test_targets_skips_every_other_port() -> None:
    parse_card = next(c for c in discover(env={}).cards if str(c.identity.port) != "compile")
    assert targets([parse_card]) == ()
