"""V01-17: every format class in 00 section 2.1 is served by an enabled card, or named out.

00:718: *"Every format class in §2.1 either has an enabled Driver whose card's `formats` list covers
it, or is absent from the shipped scope with a named reason -- asserted mechanically against
`[drivers] enabled`. **`Kind.SECTION` is excluded by name**"*.

**The map from class to formats is not written here; the shipped routing policy's rules are.**
Section 2.1 names each class in prose, with Word, PowerPoint and so on. The policy names each
class's formats as tokens, in the rule that routes them (`decode.office-native`,
`decode.raster-image`, ...). So each class below names the rules that carry it, and the tokens
are read out of `00-builtin-route.toml`. A class covers its formats when:
- every rule's driver is in `[drivers] enabled`;
- the driver has a card in the shipped roster;
- every token the rule names is in that card's served set, `served_tokens()`, which is the
  comparison `ow route lint` check 11 makes (04 section 2.2).

**The roster is every first-party `driver.toml` in this tree, not this checkout's discovery
catalog.** `omniweave-vision` is installed only on the nightly GPU cell (11:1666) and declares no
entry point (D575), so a catalog read here would never see `parse.page.olmocr`. That is a fact
about discovery, not about the shipped card. D611 records it, so a PASS here is not read as
"olmOCR resolves".

A class with no covering card must be on the named-reason branch. Its reason cites the open
question section 2.1's own gate column names, and the test asserts the branch is still true: no
enabled card serves any of its tokens. So a driver landing for HTML fails this test until the
class moves to the covered branch, which is what makes the branch mechanical rather than
editorial (00:835).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import pytest
from omniweave.route.detect import format_token_for
from omniweave_core.config import load
from omniweave_core.drivers.card import DriverCard, load_card, served_tokens
from omniweave_core.model.enums import Kind

if TYPE_CHECKING:
    from pathlib import Path

    from conftest import PlanDocs

POLICY: Final = "packages/omniweave/src/omniweave/route/policies/00-builtin-route.toml"


@dataclass(frozen=True, slots=True)
class FormatClass:
    """One row of 00 section 2.1, keyed by the text before its first dash or colon."""

    name: str
    rules: tuple[str, ...]
    """The shipped policy rules that carry this class's formats."""
    reason: str = ""
    """Empty on the covered branch; the open question that names it out, on the other."""


CLASSES: Final[tuple[FormatClass, ...]] = (
    FormatClass("Office containers", ("decode.office-native",)),
    FormatClass("Born-digital PDF", ("decode.pdf-text-layer",)),
    FormatClass("Scanned PDF, page images", ("decode.no-text-layer", "decode.raster-image")),
    #  `decode.text-native` routes `html` and `xhtml` to `parse.text.builtin`, which ships in
    #  `omniweave-office` since D646, so HTML is covered and the class's named-out half is email:
    #  `decode.container-expanded` expands a container and parses nothing.
    FormatClass(
        "HTML, email",
        ("decode.text-native", "decode.container-expanded"),
        reason="V-Q6: no first-party parse/1 Driver at release 1; a third party ships one",
    ),
    FormatClass(
        "Audio, video",
        ("gate.unsupported-media",),
        reason="V-Q7: no parse Lane transcribes; time-based media waits on a SCHEMA major",
    ),
)
"""Section 2.1's five format classes, in its order."""

CLASS_TOKENS: Final[dict[str, frozenset[str]]] = {
    "HTML, email": frozenset({"eml", "msg", "mbox"}),
}
"""A named-out class whose rules also route formats outside it: only these tokens are named out.

`HTML, email` is half covered since D646: 00 section 2.1's row now names `parse.text.builtin` for
HTML and XHTML, and V-Q6 for email. So the named-out tokens are email's, and
`test_html_is_served_by_the_text_driver` holds the covered half."""

NOT_FORMAT_CLASSES: Final[dict[str, str]] = {
    "Locators": (
        "acquisition produces bytes and a roster, never Blocks (00 section 2.1's own provenance "
        "cell), so no card's `formats` can cover a locator; the fs roster is core code "
        "(04 section 10.2) and `acquire/1` ships no first-party driver (04 section 10.3, D611)"
    ),
}
"""Section 2.1 rows that are input classes but not format classes, each with why."""

EXCLUDED_BY_NAME: Final[dict[str, str]] = {
    "Kind.SECTION": (
        "a member of the closed read vocabulary with no release-1 producer, not a format class "
        "(04 section 10.1, ADR-3 D6)"
    ),
}


def _rules(repo_root: Path) -> dict[str, dict[str, object]]:
    policy = tomllib.loads((repo_root / POLICY).read_text(encoding="utf-8"))
    return {str(rule["id"]): rule for rule in policy["rule"]}


def _tokens(rule: dict[str, object]) -> frozenset[str]:
    """The `unit.format` literals a rule names: one string, or an `in` list."""
    when = rule["when"]
    assert isinstance(when, dict)
    literal = when["unit.format"]
    if isinstance(literal, str):
        return frozenset({literal})
    assert isinstance(literal, dict)
    return frozenset(str(token) for token in literal["in"])


def _roster(repo_root: Path) -> dict[str, DriverCard]:
    cards: dict[str, DriverCard] = {}
    for path in sorted(repo_root.glob("packages/*/src/**/driver.toml")):
        if "omniweave-conform" in path.parts:  # the conformance kit's template, not a driver
            continue
        card = load_card(path.read_bytes(), origin="driver_path", source=str(path))
        assert isinstance(card, DriverCard), path
        cards[card.identity.id] = card
    return cards


@pytest.fixture(scope="module")
def enabled(tmp_path_factory: pytest.TempPathFactory) -> frozenset[str]:
    """`[drivers] enabled` as a fresh install resolves it: no project file, no environment."""
    value = load(cwd=tmp_path_factory.mktemp("fresh"), env={}).get("drivers.enabled")
    assert isinstance(value, tuple)
    return frozenset(str(one) for one in value)


def _served(card: DriverCard) -> frozenset[str]:
    return served_tokens(card, format_token_for)


@pytest.mark.parametrize("klass", [c for c in CLASSES if not c.reason], ids=lambda c: c.name)
def test_a_covered_class_is_served_by_an_enabled_card(
    klass: FormatClass, repo_root: Path, enabled: frozenset[str]
) -> None:
    rules, roster = _rules(repo_root), _roster(repo_root)
    for rule_id in klass.rules:
        then = rules[rule_id]["then"]
        assert isinstance(then, dict)
        driver = str(then["driver"])
        assert driver in enabled, f"{rule_id} routes to {driver}, which is not in [drivers] enabled"
        assert driver in roster, f"{rule_id} routes to {driver}, which has no card in the tree"
        missing = _tokens(rules[rule_id]) - _served(roster[driver])
        assert not missing, f"{driver}'s card does not cover {sorted(missing)} ({rule_id})"


@pytest.mark.parametrize("klass", [c for c in CLASSES if c.reason], ids=lambda c: c.name)
def test_a_named_out_class_is_still_served_by_no_enabled_card(
    klass: FormatClass, repo_root: Path, enabled: frozenset[str]
) -> None:
    """The named-reason branch is true only while nothing covers the class. When a driver
    lands, this fails, and the class moves to the covered branch in the same commit."""
    rules, roster = _rules(repo_root), _roster(repo_root)
    named = set().union(*(_tokens(rules[rule_id]) for rule_id in klass.rules))
    tokens = CLASS_TOKENS.get(klass.name, frozenset(named))
    assert tokens <= named, f"{klass.name}'s tokens are not all in its rules"
    for driver in enabled & roster.keys():
        served = tokens & _served(roster[driver])
        assert not served, f"{driver} serves {sorted(served)}: {klass.name} is no longer named out"


def test_html_is_served_by_the_text_driver(repo_root: Path, enabled: frozenset[str]) -> None:
    """D646: the covered half of `HTML, email`. `decode.text-native` routes `html` and `xhtml` to
    `parse.text.builtin`, which is enabled and whose card serves both."""
    then = _rules(repo_root)["decode.text-native"]["then"]
    assert isinstance(then, dict)
    driver = str(then["driver"])
    assert driver == "parse.text.builtin"
    assert driver in enabled
    assert {"html", "xhtml"} <= _served(_roster(repo_root)[driver])


def test_audio_and_video_are_refused_at_gate_rather_than_parsed(repo_root: Path) -> None:
    then = _rules(repo_root)["gate.unsupported-media"]["then"]
    assert isinstance(then, dict)
    assert (then["outcome"], then["failure_class"]) == ("refuse", "unsupported_format")


def test_every_rule_a_class_names_exists_and_carries_formats(repo_root: Path) -> None:
    rules = _rules(repo_root)
    for klass in CLASSES:
        for rule_id in klass.rules:
            assert rule_id in rules, f"{klass.name} names {rule_id}, which the policy lacks"
            assert _tokens(rules[rule_id])


def test_kind_section_is_kept_and_excluded_by_name(repo_root: Path) -> None:
    """ADR-3 D6: the member stays in the read vocabulary, and no shipped card produces it. Both
    halves are asserted, because "excluded by name" is only honest while the vacancy is real."""
    assert Kind.SECTION.value == "section"
    assert "Kind.SECTION" in EXCLUDED_BY_NAME
    assert all(klass.name != "section" for klass in CLASSES)
    producers = [
        card.identity.id
        for card in _roster(repo_root).values()
        if card.parse is not None and card.parse.sections == "typed_levels"
    ]
    assert producers == [], f"{producers} declare typed_levels: Kind.SECTION now has a producer"


def _section_2_1_rows(plan: PlanDocs) -> list[tuple[str, str]]:
    """Section 2.1's table as `(class key, gate cell)`, the key being the text before the first
    em dash or colon of the first cell, with any bold removed."""
    lines = plan.lines("00-vision.md")
    start = lines.index("### 2.1 The input surface at release 1")
    rows: list[tuple[str, str]] = []
    for line in lines[start + 1 :]:
        if line.startswith("### "):
            break
        if not line.startswith("| ") or line.startswith(("| Input class", "|---")):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        first = cells[0].replace("**", "")
        key = first.split(" — ")[0].split(":")[0].strip()
        rows.append((key, cells[-1]))
    return rows


def test_the_classes_are_exactly_section_2_1s_rows(plan: PlanDocs) -> None:
    """The transcription half: every row of 00 section 2.1 is a class here, or a named non-class,
    and every named-out class cites the open question its row's gate cell names."""
    plan.require()
    rows = _section_2_1_rows(plan)
    assert [key for key, _gate in rows if key not in NOT_FORMAT_CLASSES] == [
        klass.name for klass in CLASSES
    ]
    assert set(NOT_FORMAT_CLASSES) <= {key for key, _gate in rows}
    gates = dict(rows)
    for klass in CLASSES:
        if klass.reason:
            assert klass.reason.startswith(gates[klass.name] + ":"), (klass.name, gates[klass.name])


def test_v01_17_excludes_kind_section_by_name_in_the_plan_too(plan: PlanDocs) -> None:
    plan.require()
    (row,) = [line for line in plan.lines("00-vision.md") if line.startswith("| V01-17 |")]
    assert "**`Kind.SECTION` is excluded by name**" in row
